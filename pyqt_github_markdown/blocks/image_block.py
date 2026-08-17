import http.client
import ipaddress
import math
import queue
import socket
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_MAX_WIDTH = 760
_MAX_BYTES = 10 * 1024 * 1024
_MAX_PIXELS = 20_000_000
_MAX_DIMENSION = 8192
_MAX_RENDER_DIMENSION = 4096
_MAX_RENDER_PIXELS = 1_000_000
_TIMEOUT_MS = 10_000
_TOTAL_TIMEOUT_SECONDS = 30
_MAX_REDIRECTS = 5
_READ_CHUNK_SIZE = 64 * 1024
_REMOTE_THREAD_SLOTS = threading.BoundedSemaphore(8)
_DNS_THREAD_SLOTS = threading.BoundedSemaphore(4)


class _RemoteCanceled(Exception):
    pass


def _remoteParts(url: str) -> tuple[str, str, int, str]:
    encoded = bytes(QUrl(url).toEncoded()).decode("ascii")
    parsed = urlsplit(encoded)
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OSError("远程图片链接无效")
    try:
        port = parsed.port or 443
        host = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError) as error:
        raise OSError("远程图片链接无效") from error
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return encoded, host, port, target


def _lookupPublicAddresses(host: str, port: int) -> tuple[str, ...]:
    addresses = []
    for _family, _type, _protocol, _name, socketAddress in socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    ):
        value = socketAddress[0].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise OSError("远程图片地址无效") from error
        if not address.is_global or address.is_multicast:
            raise OSError("远程图片地址不安全")
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise OSError("无法解析远程图片地址")
    return tuple(addresses)


def _resolvePublicAddresses(
    host: str,
    port: int,
    deadline: float | None = None,
    cancelEvent=None,
) -> tuple[str, ...]:
    deadline = deadline or time.monotonic() + _TOTAL_TIMEOUT_SECONDS
    if not _DNS_THREAD_SLOTS.acquire(blocking=False):
        raise OSError("远程图片解析任务已满")
    resultQueue = queue.Queue(maxsize=1)

    def resolve():
        try:
            result = _lookupPublicAddresses(host, port), None
        except Exception as error:
            result = None, error
        finally:
            _DNS_THREAD_SLOTS.release()
        resultQueue.put_nowait(result)

    try:
        threading.Thread(
            target=resolve,
            daemon=True,
            name="markdown-image-dns",
        ).start()
    except Exception:
        _DNS_THREAD_SLOTS.release()
        raise

    while True:
        if cancelEvent is not None and cancelEvent.is_set():
            raise _RemoteCanceled()
        try:
            addresses, error = resultQueue.get(
                timeout=min(0.05, _remainingSeconds(deadline))
            )
        except queue.Empty:
            continue
        if error is not None:
            raise error
        return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        address: str,
        port: int,
        timeout: float,
        cancelEvent=None,
    ):
        self._pinnedAddress = address
        self._cancelEvent = cancelEvent
        super().__init__(host, port, timeout=timeout)

    def _connectPinned(self, _address, timeout, sourceAddress):
        if self._cancelEvent is not None and self._cancelEvent.is_set():
            raise _RemoteCanceled()
        connection = socket.create_connection(
            (self._pinnedAddress, self.port),
            timeout,
            sourceAddress,
        )
        self.sock = connection
        if self._cancelEvent is not None and self._cancelEvent.is_set():
            self.close()
            raise _RemoteCanceled()
        return connection

    def connect(self):
        try:
            self._connectPinned(
                (self.host, self.port),
                self.timeout,
                self.source_address,
            )
            serverHostname = self._tunnel_host or self.host
            if self._tunnel_host:
                self._tunnel()
            encrypted = self._context.wrap_socket(
                self.sock,
                server_hostname=serverHostname,
            )
            self.sock = encrypted
            if self._cancelEvent is not None and self._cancelEvent.is_set():
                self.close()
                raise _RemoteCanceled()
        except Exception:
            self.close()
            raise


def _remainingSeconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("远程图片加载超时")
    return remaining


def _fetchRemoteImage(url: str, cancelEvent, setConnection) -> bytes:
    currentUrl = url
    deadline = time.monotonic() + _TOTAL_TIMEOUT_SECONDS
    for redirectCount in range(_MAX_REDIRECTS + 1):
        _remainingSeconds(deadline)
        currentUrl, host, port, target = _remoteParts(currentUrl)
        addresses = _resolvePublicAddresses(
            host,
            port,
            deadline,
            cancelEvent,
        )
        _remainingSeconds(deadline)
        connection = None
        response = None
        lastError = None
        for address in addresses:
            if cancelEvent.is_set():
                raise _RemoteCanceled()
            candidate = _PinnedHTTPSConnection(
                host,
                address,
                port,
                min(_TIMEOUT_MS / 1000, _remainingSeconds(deadline)),
                cancelEvent,
            )
            if not setConnection(candidate):
                candidate.close()
                raise _RemoteCanceled()
            if cancelEvent.is_set():
                candidate.close()
                setConnection(None)
                raise _RemoteCanceled()
            try:
                candidate.request(
                    "GET",
                    target,
                    headers={
                        "Accept": "image/*",
                        "Accept-Encoding": "identity",
                        "Connection": "close",
                    },
                )
                response = candidate.getresponse()
                connection = candidate
                break
            except (OSError, http.client.HTTPException) as error:
                lastError = error
                candidate.close()
                setConnection(None)
        if response is None or connection is None:
            raise OSError("无法连接远程图片地址") from lastError

        try:
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirectCount >= _MAX_REDIRECTS:
                    raise OSError("远程图片重定向无效")
                currentUrl = urljoin(currentUrl, location)
                continue
            if not 200 <= response.status < 300:
                raise OSError(f"远程图片请求失败（{response.status}）")
            if (response.getheader("Content-Encoding") or "").lower() not in {
                "",
                "identity",
            }:
                raise OSError("远程图片响应编码不受支持")
            contentLength = response.getheader("Content-Length") or ""
            if contentLength.isdigit() and int(contentLength) > _MAX_BYTES:
                raise OSError("远程图片超过大小限制")

            data = bytearray()
            while True:
                if cancelEvent.is_set():
                    raise _RemoteCanceled()
                remaining = _remainingSeconds(deadline)
                if connection.sock is not None:
                    connection.sock.settimeout(
                        min(_TIMEOUT_MS / 1000, remaining)
                    )
                chunk = response.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > _MAX_BYTES:
                    raise OSError("远程图片超过大小限制")
            if cancelEvent.is_set():
                raise _RemoteCanceled()
            return bytes(data)
        finally:
            response.close()
            connection.close()
            setConnection(None)

    raise OSError("远程图片重定向过多")


def _loadLocalPixmap(src: str) -> QPixmap | None:
    url = QUrl(src)
    if url.scheme() in ("http", "https"):
        return None
    if not src.startswith(":/"):
        return None
    pixmap = QPixmap(src)
    return pixmap if not pixmap.isNull() else None


class ImagePlaceholder(QWidget):
    _remoteLoaded = Signal(object)

    def __init__(self, alt: str, src: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._alt = alt
        self._src = src
        self._remoteCancelEvent = threading.Event()
        self._remoteConnectionLock = threading.Lock()
        self._remoteConnection = None
        self._remoteThread = None
        self._label = QLabel()
        self._rootLayout = QVBoxLayout(self)
        self.destroyed.connect(self._remoteCancelEvent.set)
        self._remoteLoaded.connect(
            self._finishRemoteLoad,
            Qt.ConnectionType.QueuedConnection,
        )
        self._initWidget()
        self._initLayout()

    def _initWidget(self) -> None:
        pixmap = _loadLocalPixmap(self._src)
        if self._isRemote():
            self._setPlaceholder(f"⏳ {self._alt or self._src}")
            self._loadRemote()
        elif pixmap is not None:
            if pixmap.width() > _MAX_WIDTH:
                pixmap = pixmap.scaledToWidth(_MAX_WIDTH, Qt.SmoothTransformation)
            self._label.setPixmap(pixmap)
        else:
            self._setPlaceholder(f"\U0001f5bc  {self._alt or self._src}")

    def _initLayout(self) -> None:
        self._rootLayout.setContentsMargins(0, 0, 0, 0)
        self._rootLayout.addWidget(self._label, 0, Qt.AlignLeft)

    def _isRemote(self) -> bool:
        return self._isSafeRemote(QUrl(self._src))

    @staticmethod
    def _isSafeRemote(url: QUrl) -> bool:
        if url.scheme().lower() != "https" or not url.host():
            return False
        host = url.host().rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True

    def _setPlaceholder(self, text: str) -> None:
        self.setObjectName("image-placeholder")
        self._label.setText(text)
        self._label.setObjectName("paragraph")

    def _loadRemote(self) -> None:
        if not _REMOTE_THREAD_SLOTS.acquire(blocking=False):
            self._rejectRemote()
            return
        try:
            thread = threading.Thread(
                target=self._downloadRemote,
                daemon=True,
                name="markdown-image",
            )
            self._remoteThread = thread
            thread.start()
        except Exception:
            self._remoteThread = None
            _REMOTE_THREAD_SLOTS.release()
            self._rejectRemote()

    def _rejectRemote(self) -> None:
        self._setPlaceholder(f"\U0001f5bc  {self._alt or self._src}")

    def _downloadRemote(self) -> None:
        try:
            data = _fetchRemoteImage(
                self._src,
                self._remoteCancelEvent,
                self._setRemoteConnection,
            )
        except Exception:
            data = None
        finally:
            self._setRemoteConnection(None)
            self._remoteThread = None
            _REMOTE_THREAD_SLOTS.release()
        if self._remoteCancelEvent.is_set():
            return
        try:
            self._remoteLoaded.emit(data)
        except RuntimeError:
            pass

    def _setRemoteConnection(self, connection) -> bool:
        with self._remoteConnectionLock:
            if connection is not None and self._remoteCancelEvent.is_set():
                return False
            self._remoteConnection = connection
            return True

    def _finishRemoteLoad(self, data) -> None:
        if not isinstance(data, bytes) or len(data) > _MAX_BYTES:
            self._setPlaceholder(f"\U0001f5bc  {self._alt or self._src}")
            return

        pixmap = self._decode(data)
        if pixmap is None:
            self._setPlaceholder(f"\U0001f5bc  {self._alt or self._src}")
            return
        self._label.clear()
        self._label.setPixmap(pixmap)

    def _cancelRemote(self) -> None:
        self._remoteCancelEvent.set()
        with self._remoteConnectionLock:
            connection = self._remoteConnection
            self._remoteConnection = None
        if connection is not None:
            connection.close()

    @staticmethod
    def _decode(data: bytes) -> QPixmap | None:
        buffer = QBuffer()
        buffer.setData(data)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        if not size.isValid() or (
            size.width() > _MAX_DIMENSION
            or size.height() > _MAX_DIMENSION
            or size.width() * size.height() > _MAX_PIXELS
        ):
            buffer.close()
            return None
        scale = min(
            1.0,
            _MAX_WIDTH / size.width(),
            _MAX_RENDER_DIMENSION / size.height(),
            math.sqrt(_MAX_RENDER_PIXELS / (size.width() * size.height())),
        )
        if scale < 1:
            reader.setScaledSize(
                QSize(
                    max(1, int(size.width() * scale)),
                    max(1, int(size.height() * scale)),
                )
            )
        image = reader.read()
        buffer.close()
        if (
            image.isNull()
            or image.width() > _MAX_WIDTH
            or image.height() > _MAX_RENDER_DIMENSION
        ):
            return None
        if image.width() * image.height() > _MAX_RENDER_PIXELS:
            return None
        return QPixmap.fromImage(image)

    def closeEvent(self, event) -> None:
        self._cancelRemote()
        super().closeEvent(event)
