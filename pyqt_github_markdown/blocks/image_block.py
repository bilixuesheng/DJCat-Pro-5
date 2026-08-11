from PySide6.QtCore import QBuffer, QIODevice, Qt, QUrl
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

_MAX_WIDTH = 760
_MAX_BYTES = 10 * 1024 * 1024
_MAX_PIXELS = 20_000_000
_MAX_DIMENSION = 8192
_TIMEOUT_MS = 10_000


def _loadLocalPixmap(src: str) -> QPixmap | None:
    # Local files stay synchronous; network images use the async path below.
    url = QUrl(src)
    if url.scheme() in ("http", "https"):
        return None
    path = url.toLocalFile() if url.isLocalFile() else src
    pixmap = QPixmap(path)
    return pixmap if not pixmap.isNull() else None


class ImagePlaceholder(QWidget):
    def __init__(self, alt: str, src: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._alt = alt
        self._src = src
        self._manager = None
        self._reply = None
        self._data = bytearray()
        # instant widget
        self._label = QLabel()
        # instant layout
        self._rootLayout = QVBoxLayout(self)
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
        return QUrl(self._src).scheme().lower() in {"http", "https"}

    def _setPlaceholder(self, text: str) -> None:
        self.setObjectName("image-placeholder")
        self._label.setText(text)
        self._label.setObjectName("paragraph")

    def _loadRemote(self) -> None:
        url = QUrl(self._src)
        self._manager = QNetworkAccessManager(self)
        request = QNetworkRequest(url)
        request.setAttribute(
            QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setTransferTimeout(_TIMEOUT_MS)
        self._reply = self._manager.get(request)
        self._reply.readyRead.connect(self._readRemoteData)
        self._reply.redirected.connect(self._checkRedirect)
        self._reply.finished.connect(self._finishRemoteLoad)

    def _readRemoteData(self) -> None:
        if self._reply is None:
            return
        self._data.extend(bytes(self._reply.readAll()))
        if len(self._data) > _MAX_BYTES:
            self._reply.abort()

    def _checkRedirect(self, url: QUrl) -> None:
        if self._reply is None:
            return
        if url.scheme().lower() not in {"http", "https"}:
            self._reply.abort()
            return
        if (
            QUrl(self._src).scheme().lower() == "https"
            and url.scheme().lower() != "https"
        ):
            self._reply.abort()

    def _finishRemoteLoad(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        self._data.extend(bytes(reply.readAll()))
        data = bytes(self._data)
        self._data.clear()
        failed = (
            reply.error() != QNetworkReply.NetworkError.NoError
            or len(data) > _MAX_BYTES
        )
        reply.deleteLater()
        if failed:
            self._setPlaceholder(f"\U0001f5bc  {self._alt or self._src}")
            return

        pixmap = self._decode(data)
        if pixmap is None:
            self._setPlaceholder(f"\U0001f5bc  {self._alt or self._src}")
            return
        self._label.clear()
        self._label.setPixmap(pixmap)

    @staticmethod
    def _decode(data: bytes) -> QPixmap | None:
        buffer = QBuffer()
        buffer.setData(data)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        size = reader.size()
        if size.isValid() and (
            size.width() > _MAX_DIMENSION
            or size.height() > _MAX_DIMENSION
            or size.width() * size.height() > _MAX_PIXELS
        ):
            buffer.close()
            return None
        image = reader.read()
        buffer.close()
        if (
            image.isNull()
            or image.width() > _MAX_DIMENSION
            or image.height() > _MAX_DIMENSION
        ):
            return None
        if image.width() * image.height() > _MAX_PIXELS:
            return None
        if image.width() > _MAX_WIDTH:
            image = image.scaledToWidth(_MAX_WIDTH, Qt.SmoothTransformation)
        return QPixmap.fromImage(image)
