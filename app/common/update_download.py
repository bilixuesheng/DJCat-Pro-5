import hashlib
import hmac
import queue
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, Signal

from app.config.paths import UPDATE_DIR


INITIAL_THREAD_COUNT = 32
MAX_THREAD_COUNT = 256
MAX_GLOBAL_THREAD_COUNT = 64
SMART_THREAD_STEP = 4
MIN_REASSIGN_SIZE = 64 * 1024
CHUNK_SIZE = 64 * 1024
REQUEST_TIMEOUT = (10, 30)
MAX_RETRIES = 3
DOWNLOAD_RETRY_COUNT = 3
MAX_UPDATE_BYTES = 1024 * 1024 * 1024
PROGRESS_EMIT_INTERVAL = 0.05
PERMANENT_STATUS = frozenset({400, 401, 403, 404, 405, 410, 451})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DOWNLOAD_THREAD_SLOTS = threading.BoundedSemaphore(MAX_GLOBAL_THREAD_COUNT)


def isHttpsResponseChain(response, requestedUrl: str) -> bool:
    urls = [requestedUrl]
    history = getattr(response, "history", ())
    if isinstance(history, (list, tuple)):
        for item in history:
            url = getattr(item, "url", None)
            if isinstance(url, str):
                urls.append(url)
    effectiveUrl = getattr(response, "url", None)
    urls.append(effectiveUrl if isinstance(effectiveUrl, str) else requestedUrl)
    for url in urls:
        try:
            if urlparse(url).scheme.lower() != "https":
                return False
        except ValueError:
            return False
    return True


def clearUpdateDirectory(directory: Path = UPDATE_DIR) -> list[Path]:
    """Remove every leftover update file while keeping the update directory."""
    failed = []
    try:
        directory.mkdir(parents=True, exist_ok=True)
        paths = tuple(directory.iterdir())
    except OSError:
        return [directory]
    for path in paths:
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError:
            failed.append(path)
    return failed


class DownloadCanceled(Exception):
    pass


class RangeNotSupportedError(Exception):
    pass


@dataclass
class DownloadSegment:
    index: int
    start: int
    end: int
    receivedBytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def position(self) -> int:
        return self.start + self.receivedBytes

    @property
    def remainingBytes(self) -> int:
        return max(0, self.end - self.position + 1)


class SmartAccelerationController:
    """Ghost Downloader's stable-speed thread growth policy."""

    def __init__(self):
        self.speedHistory = []
        self.checkTime = 0.0
        self.initialWorkers = 0
        self.initialSpeed = 0.0
        self.disabled = False

    def sample(self, speed: int, workerCount: int, now: float) -> int:
        if self.disabled:
            return 0

        self.speedHistory.append(speed)
        if len(self.speedHistory) > 5:
            self.speedHistory.pop(0)
        if len(self.speedHistory) < 5:
            return 0

        averageSpeed = sum(self.speedHistory) / len(self.speedHistory)
        if averageSpeed == 0:
            return 0

        maxDeviation = max(
            abs(value - averageSpeed) / averageSpeed
            for value in self.speedHistory
        )
        if maxDeviation > 0.15:
            return 0

        if self.checkTime == 0:
            self.initialWorkers = workerCount
            self.initialSpeed = averageSpeed
            self.checkTime = now
            return SMART_THREAD_STEP

        if now - self.checkTime <= 5:
            return 0

        workerRatio = (
            (workerCount - self.initialWorkers) / self.initialWorkers
            if self.initialWorkers
            else 0
        )
        speedRatio = (
            (averageSpeed - self.initialSpeed) / self.initialSpeed
            if self.initialSpeed
            else 0
        )

        if speedRatio < 0.8 * workerRatio:
            self.disabled = True
            return 0

        self.checkTime = 0
        return SMART_THREAD_STEP


class UpdateDownloadWorker(QObject):
    """Download the installer with Ghost-style Range workers and acceleration.

    The segment reassignment and smart acceleration policy is adapted from
    the latest cloud Ghost Downloader 3 source
    (XiaoYouChR/Ghost-Downloader-3, commit 57430ca), which is GPL-3.0
    licensed like this project.
    """

    progressChanged = Signal(int, int, int, int)
    retrying = Signal(int, int, str)
    finished = Signal(str, str, bool)

    def __init__(
        self,
        url: str,
        targetPath: Path,
        validator: Callable[[Path], None] | None = None,
        requireHttps: bool = False,
        maxBytes: int | None = None,
        expectedSha256: str | None = None,
        checksumUrl: str | None = None,
    ):
        super().__init__()
        self.url = url
        self.targetPath = Path(targetPath)
        self.validator = validator or self._validateExecutable
        self.requireHttps = requireHttps
        if maxBytes is not None and maxBytes <= 0:
            raise ValueError("下载大小上限必须大于 0")
        self.maxBytes = maxBytes
        expectedSha256 = str(expectedSha256 or "").strip().lower()
        if expectedSha256 and not _SHA256.fullmatch(expectedSha256):
            raise ValueError("SHA-256 校验值无效")
        checksumUrl = str(checksumUrl or "").strip()
        try:
            checksumScheme = urlparse(checksumUrl).scheme.lower() if checksumUrl else ""
        except ValueError:
            checksumScheme = ""
        if checksumUrl and checksumScheme != "https":
            raise ValueError("校验文件链接必须使用 HTTPS")
        self._expectedSha256 = expectedSha256 or None
        self.checksumUrl = checksumUrl or None
        self.partialPath = self.targetPath.with_suffix(
            f"{self.targetPath.suffix}.part"
        )
        self._cancelEvent = threading.Event()
        self._rangeStopEvent = threading.Event()
        self._responsesLock = threading.Lock()
        self._responses = set()
        self._segmentsLock = threading.Lock()
        self._progressLock = threading.Lock()
        self._progressEmitLock = threading.Lock()
        self._segments = []
        self._downloaded = 0
        self._currentSpeed = 0
        self._activeWorkers = 0
        self._lastProgressEmit = 0.0

    def cancel(self) -> None:
        self._cancelEvent.set()
        self._closeResponses()

    def run(self) -> None:
        resultPath = ""
        errorMessage = ""
        canceled = False

        for retry in range(DOWNLOAD_RETRY_COUNT + 1):
            try:
                self._prepareAttempt()
                resultPath = self._downloadAttempt()
                errorMessage = ""
                break
            except DownloadCanceled:
                canceled = True
                break
            except Exception as error:
                if self._cancelEvent.is_set():
                    canceled = True
                    break
                errorMessage = str(error)
                if retry == DOWNLOAD_RETRY_COUNT:
                    break
                self.retrying.emit(
                    retry + 1,
                    DOWNLOAD_RETRY_COUNT,
                    errorMessage,
                )
                if self._cancelEvent.wait(1):
                    canceled = True
                    errorMessage = ""
                    break
            finally:
                self._rangeStopEvent.set()
                self._closeResponses()
                if not resultPath:
                    for path in (self.partialPath, self.targetPath):
                        try:
                            self._removeFile(path)
                        except OSError as cleanupError:
                            if not canceled and not errorMessage:
                                errorMessage = str(cleanupError)

        self.finished.emit(resultPath, errorMessage, canceled)

    def _prepareAttempt(self) -> None:
        self._rangeStopEvent.clear()
        self._segments = []
        self._activeWorkers = 0
        self._resetProgress()
        self.targetPath.parent.mkdir(parents=True, exist_ok=True)
        self._removeFile(self.partialPath)
        self._removeFile(self.targetPath)

    def _downloadAttempt(self) -> str:
        if self._expectedSha256 is None and self.checksumUrl:
            self._expectedSha256 = self._fetchChecksum()
        effectiveUrl, total, supportsRange = self._probeDownload()
        self._ensureSizeAllowed(total)
        if self.requireHttps and urlparse(effectiveUrl).scheme.lower() != "https":
            raise OSError("下载链接必须保持 HTTPS")
        if self._cancelEvent.is_set():
            raise DownloadCanceled()

        if supportsRange and total > 0:
            try:
                self._downloadRanged(effectiveUrl, total)
            except RangeNotSupportedError:
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()
                self._rangeStopEvent.clear()
                self._resetProgress()
                self._downloadSingle(effectiveUrl, total)
        else:
            self._downloadSingle(effectiveUrl, total)

        if self._cancelEvent.is_set():
            raise DownloadCanceled()

        self.validator(self.partialPath)
        if self._cancelEvent.is_set():
            raise DownloadCanceled()
        self._validateChecksum(self.partialPath)
        if self._cancelEvent.is_set():
            raise DownloadCanceled()

        self.partialPath.replace(self.targetPath)
        return str(self.targetPath)

    def _fetchChecksum(self) -> str:
        response = requests.get(
            self.checksumUrl,
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
        self._trackResponse(response)
        try:
            self._ensureResponseHttps(response, self.checksumUrl)
            response.raise_for_status()
            contentLength = str(response.headers.get("Content-Length", ""))
            if contentLength.isdigit() and int(contentLength) > 4096:
                raise OSError("校验文件过大")
            content = bytearray()
            for chunk in response.iter_content(chunk_size=1024):
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > 4096:
                    raise OSError("校验文件过大")
            fields = bytes(content).decode("ascii").split(maxsplit=1)
            value = fields[0].lower() if fields else ""
            if not _SHA256.fullmatch(value):
                raise OSError("校验文件格式无效")
            return value
        finally:
            self._untrackResponse(response)
            response.close()

    def _validateChecksum(self, path: Path) -> None:
        if self._expectedSha256 is None:
            return
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()
                digest.update(chunk)
        if not hmac.compare_digest(digest.hexdigest(), self._expectedSha256):
            raise OSError("下载文件 SHA-256 校验失败")

    def _ensureResponseHttps(self, response, requestedUrl: str) -> None:
        if self.requireHttps and not isHttpsResponseChain(response, requestedUrl):
            raise OSError("下载链接必须保持 HTTPS")

    def _probeDownload(self) -> tuple[str, int, bool]:
        statusCode, headers, effectiveUrl = self._requestProbe("bytes=1-1")
        total = self._rangeTotal(headers)
        supportsRange = statusCode == 206 and bool(
            headers.get("Content-Range")
        )
        if supportsRange:
            return effectiveUrl, total, True

        total = self._bodyLength(headers)
        if statusCode == 200 and total in {0, 1}:
            fallbackStatus, fallbackHeaders, fallbackUrl = self._requestProbe(
                "bytes=0-0"
            )
            fallbackTotal = self._rangeTotal(fallbackHeaders)
            if fallbackStatus == 206 and fallbackHeaders.get("Content-Range"):
                return fallbackUrl, fallbackTotal, True
            if total == 0:
                total = self._bodyLength(fallbackHeaders)
                if total == 0 and fallbackStatus == 416:
                    total = fallbackTotal

        return effectiveUrl, total, False

    def _requestProbe(self, rangeValue: str) -> tuple[int, dict, str]:
        response = requests.get(
            self.url,
            headers={
                "Range": rangeValue,
                "Accept-Encoding": "identity",
            },
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )
        self._trackResponse(response)
        try:
            self._ensureResponseHttps(response, self.url)
            statusCode = response.status_code
            if statusCode not in {200, 206, 416}:
                response.raise_for_status()
                raise requests.HTTPError(f"服务器返回 HTTP {statusCode}")
            return (
                statusCode,
                dict(response.headers),
                str(getattr(response, "url", self.url)),
            )
        finally:
            self._untrackResponse(response)
            response.close()

    @staticmethod
    def _rangeTotal(headers: dict) -> int:
        contentRange = headers.get("Content-Range", "")
        if "/" not in contentRange:
            return 0
        total = contentRange.rpartition("/")[2]
        return int(total) if total.isdigit() and int(total) > 0 else 0

    @staticmethod
    def _bodyLength(headers: dict) -> int:
        contentLength = headers.get("Content-Length", "")
        return (
            int(contentLength)
            if contentLength.isdigit() and int(contentLength) > 0
            else 0
        )

    def _downloadSingle(self, url: str, total: int) -> None:
        self._activeWorkers = 1
        startedAt = time.monotonic()
        response = requests.get(
            url,
            headers={"Accept-Encoding": "identity"},
            stream=True,
            timeout=REQUEST_TIMEOUT,
        )
        self._trackResponse(response)
        try:
            self._ensureResponseHttps(response, url)
            response.raise_for_status()
            contentLength = response.headers.get("Content-Length", "")
            responseTotal = int(contentLength) if contentLength.isdigit() else 0
            self._ensureSizeAllowed(responseTotal)
            if not total:
                total = responseTotal

            with self.partialPath.open("wb") as file:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if self._cancelEvent.is_set():
                        raise DownloadCanceled()
                    if not chunk:
                        continue
                    self._ensureSizeAllowed(self._downloaded + len(chunk))
                    file.write(chunk)
                    with self._progressLock:
                        self._downloaded += len(chunk)
                        downloaded = self._downloaded
                    elapsed = max(time.monotonic() - startedAt, 0.001)
                    speed = int(downloaded / elapsed)
                    self._emitProgress(downloaded, total, speed, 1)
        finally:
            self._activeWorkers = 0
            self._untrackResponse(response)
            response.close()

        if total and self._downloaded != total:
            raise OSError(
                f"下载大小不完整：应为 {total} 字节，实际 {self._downloaded} 字节"
            )

    def _downloadRanged(self, url: str, total: int) -> None:
        self._ensureSizeAllowed(total)
        self._segments = self._buildSegments(total, INITIAL_THREAD_COUNT)
        self.partialPath.touch()
        with self.partialPath.open("r+b") as file:
            file.truncate(total)

        completionQueue = queue.Queue()
        workerThreads = []
        controller = SmartAccelerationController()
        lastDownloaded = 0
        nextSample = time.monotonic() + 1

        def submit(segment: DownloadSegment) -> None:
            while not _DOWNLOAD_THREAD_SLOTS.acquire(timeout=0.1):
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()
                if self._rangeStopEvent.is_set():
                    return
            if self._cancelEvent.is_set() or self._rangeStopEvent.is_set():
                _DOWNLOAD_THREAD_SLOTS.release()
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()
                return
            self._activeWorkers += 1

            def runSegment():
                try:
                    self._downloadSegment(url, segment)
                except Exception as error:
                    completionQueue.put(error)
                else:
                    completionQueue.put(None)
                finally:
                    _DOWNLOAD_THREAD_SLOTS.release()

            thread = threading.Thread(
                target=runSegment,
                daemon=True,
                name=f"djcat-update-{segment.index}",
            )
            workerThreads.append(thread)
            try:
                thread.start()
            except Exception:
                workerThreads.pop()
                self._activeWorkers -= 1
                _DOWNLOAD_THREAD_SLOTS.release()
                raise

        try:
            for segment in self._segments:
                submit(segment)

            while self._activeWorkers:
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()

                now = time.monotonic()
                timeout = max(0, min(0.1, nextSample - now))
                try:
                    error = completionQueue.get(timeout=timeout)
                except queue.Empty:
                    error = None
                    completed = False
                else:
                    completed = True

                if completed:
                    self._activeWorkers -= 1
                    if error is not None:
                        raise error
                    if not self._rangeStopEvent.is_set():
                        newSegment = self._splitSlowest()
                        if newSegment is not None:
                            submit(newSegment)

                now = time.monotonic()
                if now >= nextSample:
                    with self._progressLock:
                        downloaded = self._downloaded
                    self._currentSpeed = max(0, downloaded - lastDownloaded)
                    lastDownloaded = downloaded
                    extraThreads = controller.sample(
                        self._currentSpeed,
                        self._activeWorkers,
                        now,
                    )
                    for _ in range(extraThreads):
                        if self._activeWorkers >= MAX_THREAD_COUNT:
                            break
                        newSegment = self._splitSlowest()
                        if newSegment is None:
                            break
                        submit(newSegment)
                    self._emitProgress(
                        downloaded,
                        total,
                        self._currentSpeed,
                        self._activeWorkers,
                    )
                    nextSample = now + 1
        except Exception:
            self._rangeStopEvent.set()
            self._closeResponses()
            raise
        finally:
            self._rangeStopEvent.set()
            self._closeResponses()
            for thread in workerThreads:
                thread.join()
            self._activeWorkers = 0

        if self._downloaded != total:
            raise OSError(
                f"下载大小不完整：应为 {total} 字节，实际 {self._downloaded} 字节"
            )

    def _downloadSegment(self, url: str, segment: DownloadSegment) -> None:
        attempts = 0
        while True:
            if self._cancelEvent.is_set():
                raise DownloadCanceled()
            if self._rangeStopEvent.is_set():
                return

            with segment.lock:
                requestStart = segment.position
                requestEnd = segment.end
            if requestStart > requestEnd:
                return

            response = None
            try:
                response = requests.get(
                    url,
                    headers={
                        "Range": f"bytes={requestStart}-{requestEnd}",
                        "Accept-Encoding": "identity",
                    },
                    stream=True,
                    timeout=REQUEST_TIMEOUT,
                )
                self._trackResponse(response)
                self._ensureResponseHttps(response, url)
                if response.status_code == 200:
                    raise RangeNotSupportedError()
                response.raise_for_status()
                contentRange = response.headers.get("Content-Range", "")
                contentEncoding = response.headers.get("Content-Encoding", "")
                if response.status_code != 206 or not contentRange.startswith(
                    f"bytes {requestStart}-"
                ):
                    raise RangeNotSupportedError()
                if contentEncoding.lower() not in {"", "identity"}:
                    raise RangeNotSupportedError()

                with self.partialPath.open("r+b", buffering=0) as file:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if self._cancelEvent.is_set():
                            raise DownloadCanceled()
                        if self._rangeStopEvent.is_set():
                            return
                        if not chunk:
                            continue

                        with segment.lock:
                            remaining = segment.remainingBytes
                            if remaining <= 0:
                                break
                            data = chunk[:remaining]
                            writePosition = segment.position
                            file.seek(writePosition)
                            file.write(data)
                            segment.receivedBytes += len(data)

                        with self._progressLock:
                            self._downloaded += len(data)
                            downloaded = self._downloaded
                        self._emitProgress(
                            downloaded,
                            self._totalSize(),
                            self._currentSpeed,
                            self._activeWorkers,
                        )

                        if len(data) < len(chunk):
                            break

                with segment.lock:
                    if segment.remainingBytes == 0:
                        return
                attempts += 1
                if attempts >= MAX_RETRIES:
                    raise OSError("分段下载响应不完整")
                if self._cancelEvent.wait(1):
                    raise DownloadCanceled()
            except (DownloadCanceled, RangeNotSupportedError):
                raise
            except requests.RequestException:
                if self._cancelEvent.is_set():
                    raise DownloadCanceled()
                if self._rangeStopEvent.is_set():
                    return
                if (
                    response is not None
                    and response.status_code in PERMANENT_STATUS
                ):
                    raise
                attempts += 1
                if attempts >= MAX_RETRIES:
                    raise
                if self._cancelEvent.wait(1):
                    raise DownloadCanceled()
            finally:
                if response is not None:
                    self._untrackResponse(response)
                    response.close()

    def _buildSegments(self, total: int, count: int) -> list[DownloadSegment]:
        count = min(max(1, count), total)
        chunkSize = total // count
        segments = []
        start = 0
        for index in range(count - 1):
            end = start + chunkSize - 1
            segments.append(DownloadSegment(index, start, end))
            start = end + 1
        segments.append(DownloadSegment(count - 1, start, total - 1))
        return segments

    def _splitSlowest(self) -> DownloadSegment | None:
        with self._segmentsLock:
            if not self._segments:
                return None

            remaining = []
            for segment in self._segments:
                with segment.lock:
                    remaining.append((segment.remainingBytes, segment))
            remainingBytes, slowest = max(remaining, key=lambda item: item[0])
            if remainingBytes < MIN_REASSIGN_SIZE:
                return None

            with slowest.lock:
                remainingBytes = slowest.remainingBytes
                if remainingBytes < MIN_REASSIGN_SIZE:
                    return None
                firstHalf = (remainingBytes + 1) // 2
                oldEnd = slowest.end
                slowest.end = slowest.position + firstHalf - 1
                newSegment = DownloadSegment(
                    index=len(self._segments),
                    start=slowest.end + 1,
                    end=oldEnd,
                )
            insertAt = self._segments.index(slowest) + 1
            self._segments.insert(insertAt, newSegment)
            return newSegment

    def _resetProgress(self) -> None:
        with self._progressLock:
            self._downloaded = 0
            self._currentSpeed = 0
        with self._progressEmitLock:
            self._lastProgressEmit = 0.0

    def _emitProgress(self, downloaded, total, speed, workers) -> None:
        now = time.monotonic()
        complete = total > 0 and downloaded >= total
        with self._progressEmitLock:
            if not complete and now - self._lastProgressEmit < PROGRESS_EMIT_INTERVAL:
                return
            self._lastProgressEmit = now
        self.progressChanged.emit(downloaded, total, speed, workers)

    def _ensureSizeAllowed(self, size: int) -> None:
        if self.maxBytes is not None and size > self.maxBytes:
            raise OSError("下载文件超过安全大小限制")

    def _totalSize(self) -> int:
        with self._segmentsLock:
            return sum(segment.end - segment.start + 1 for segment in self._segments)

    def _segmentCount(self) -> int:
        with self._segmentsLock:
            return len(self._segments)

    def _trackResponse(self, response) -> None:
        with self._responsesLock:
            self._responses.add(response)

    def _untrackResponse(self, response) -> None:
        with self._responsesLock:
            self._responses.discard(response)

    def _closeResponses(self) -> None:
        with self._responsesLock:
            responses = tuple(self._responses)
        for response in responses:
            try:
                response.close()
            except Exception:
                pass

    @staticmethod
    def _removeFile(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _validateExecutable(path: Path) -> None:
        with path.open("rb") as file:
            if file.read(2) != b"MZ":
                raise ValueError("下载文件不是有效的 Windows 安装程序")
