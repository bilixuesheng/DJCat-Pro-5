import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

import requests

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QRect, QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

import djcat
from app.common import update_download as updateDownloadModule
from app.common.update_download import (
    DOWNLOAD_RETRY_COUNT,
    DownloadCanceled,
    DownloadSegment,
    INITIAL_THREAD_COUNT,
    MAX_RETRIES,
    MIN_REASSIGN_SIZE,
    SMART_THREAD_STEP,
    SmartAccelerationController,
    UpdateDownloadWorker,
    clearUpdateDirectory,
)
from app.config.cfg import cfg
from app.config.constants import (
    DOWNLOAD_URL,
    normalizeReleaseVersion,
)
from app.view.pages.setting_page import SettingPage
from app.view.shell.tray import SystemTrayIcon
from app.view.windows.main_window import (
    InstallerLaunchDialog,
    MainWindow,
    UpdateWorker,
)


class FakeResponse:
    def __init__(
        self,
        chunks,
        contentLength=None,
        statusCode=200,
        headers=None,
        url=DOWNLOAD_URL,
    ):
        self.chunks = chunks
        self.headers = dict(headers or {})
        if contentLength is not None:
            self.headers["Content-Length"] = str(contentLength)
        self.status_code = statusCode
        self.url = url
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        self.chunkSize = chunk_size
        yield from self.chunks

    def close(self):
        self.closed = True


class SignalStub:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class LayoutStub:
    def addSpacing(self, _):
        pass


class InfoBarStub:
    instances = []

    def __init__(self, *_, **__):
        self.widgetLayout = LayoutStub()
        self.destroyed = SignalStub()
        self.widgets = []
        self.closed = False
        self.shown = False
        self.instances.append(self)

    def addWidget(self, widget):
        self.widgets.append(widget)

    def close(self):
        self.closed = True

    def show(self):
        self.shown = True

    @classmethod
    def info(cls, *args, **kwargs):
        infoBar = cls(*args, **kwargs)
        infoBar.show()
        return infoBar


class ButtonStub:
    def __init__(self, *_, **__):
        self.clicked = SignalStub()


class StateToolTipStub:
    def __init__(self, title, content, parent):
        self.title = title
        self.content = content
        self.parent = parent
        self.state = None
        self.shown = False
        self.hidden = False
        self.contentLabel = Mock()
        self.contentLabel.sizeHint.return_value.width.return_value = 300
        self.titleLabel = Mock()
        self.titleLabel.sizeHint.return_value.width.return_value = 100
        self.closeButton = Mock()
        self.fixedWidth = 0
        self.closedSignal = SignalStub()
        self.destroyed = SignalStub()
        self.deleted = False
        self.position = (0, 0)
        self.suitablePosCalls = 0

    def getSuitablePos(self):
        self.suitablePosCalls += 1
        return (0, 0)

    def move(self, *position):
        if len(position) == 1:
            self.position = position[0]
        else:
            self.position = position

    def show(self):
        self.shown = True

    def hide(self):
        self.hidden = True

    def setContent(self, content):
        self.content = content

    def setState(self, state):
        self.state = state

    def setFixedWidth(self, width):
        self.fixedWidth = width

    def deleteLater(self):
        self.deleted = True

    def width(self):
        return self.fixedWidth

    def y(self):
        return self.position[1]


class DownloadWorkerStub:
    def __init__(self, url, targetPath):
        self.url = url
        self.targetPath = targetPath
        self.progressChanged = SignalStub()
        self.retrying = SignalStub()
        self.finished = SignalStub()
        self.canceled = False
        self.deleted = False

    def run(self):
        pass

    def cancel(self):
        self.canceled = True

    def deleteLater(self):
        self.deleted = True


class ThreadStub:
    def __init__(self, target, daemon):
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self):
        self.started = True


class InstallerLaunchDialogStub:
    def __init__(self):
        self.shown = False
        self.finished = False

    def show(self):
        self.shown = True

    def finish(self):
        self.finished = True


class UpdateDownloadTest(TestCase):
    def testStartupCleanupRemovesAllUpdateDirectoryContents(self):
        with tempfile.TemporaryDirectory() as tempDir:
            updateDir = Path(tempDir) / "Updata"
            nestedDir = updateDir / "nested"
            nestedDir.mkdir(parents=True)
            (updateDir / "old.exe").write_bytes(b"old")
            (nestedDir / "partial.tmp").write_bytes(b"partial")

            clearUpdateDirectory(updateDir)

            self.assertTrue(updateDir.is_dir())
            self.assertEqual(list(updateDir.iterdir()), [])

    def testStartupCleanupDoesNotFailWhenInstallerStillLocksAFile(self):
        with tempfile.TemporaryDirectory() as tempDir:
            updateDir = Path(tempDir) / "Updata"
            updateDir.mkdir()
            locked = updateDir / "DJCat-Pro.exe"
            locked.write_bytes(b"MZ")

            with patch.object(Path, "unlink", side_effect=PermissionError):
                failed = clearUpdateDirectory(updateDir)

            self.assertEqual(failed, [locked])
            self.assertTrue(locked.exists())

    def testDeclaredOversizedDownloadIsRejectedBeforeAllocation(self):
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
                maxBytes=1024,
            )
            with (
                patch.object(
                    worker,
                    "_probeDownload",
                    return_value=(DOWNLOAD_URL, 1025, True),
                ),
                patch.object(worker, "_downloadRanged") as ranged,
                self.assertRaisesRegex(OSError, "安全大小限制"),
            ):
                worker._downloadAttempt()

            ranged.assert_not_called()

    def testDownloadedFileMustMatchExpectedSha256(self):
        with tempfile.TemporaryDirectory() as tempDir:
            path = Path(tempDir) / "update.exe.part"
            path.write_bytes(b"MZ-test")
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
                expectedSha256="0" * 64,
            )

            with self.assertRaisesRegex(OSError, "SHA-256"):
                worker._validateChecksum(path)

    def testCancelDuringValidatorDoesNotPublishDownloadedFile(self):
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
            )

            def download(_url, _total):
                worker.partialPath.write_bytes(b"MZ")

            worker.validator = lambda _path: worker.cancel()
            with (
                patch.object(
                    worker,
                    "_probeDownload",
                    return_value=(DOWNLOAD_URL, 2, False),
                ),
                patch.object(worker, "_downloadSingle", side_effect=download),
                self.assertRaises(DownloadCanceled),
            ):
                worker._downloadAttempt()

            self.assertFalse(worker.targetPath.exists())

    def testChecksumDownloadStreamsAndStopsAtFourKilobytes(self):
        response = FakeResponse([b"a" * 4096, b"b"])
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
                checksumUrl=f"{DOWNLOAD_URL}.sha256",
            )
            with (
                patch(
                    "app.common.update_download.requests.get",
                    return_value=response,
                ) as get,
                self.assertRaisesRegex(OSError, "校验文件过大"),
            ):
                worker._fetchChecksum()

        self.assertTrue(get.call_args.kwargs["stream"])
        self.assertTrue(response.closed)

    def testUnknownLengthDownloadStopsAtSizeLimit(self):
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
                maxBytes=4,
            )
            response = FakeResponse([b"MZ12", b"3"], contentLength=0)
            with (
                patch(
                    "app.common.update_download.requests.get",
                    return_value=response,
                ),
                self.assertRaisesRegex(OSError, "安全大小限制"),
            ):
                worker._downloadSingle(DOWNLOAD_URL, 0)

            self.assertEqual(worker.partialPath.read_bytes(), b"MZ12")

    def testLoggingKeepsFourteenDays(self):
        with patch("loguru.logger.add") as add:
            djcat.configureLogging()

        self.assertEqual(add.call_args.kwargs["rotation"], "00:00")
        self.assertEqual(add.call_args.kwargs["retention"], "14 days")

    def testDownloadUsesBucketExeAndAtomicallyStoresValidInstaller(self):
        content = b"MZ" + b"installer-data"
        probe = FakeResponse([], len(content))
        response = FakeResponse([content[:4], content[4:]], len(content))

        with tempfile.TemporaryDirectory() as tempDir:
            target = Path(tempDir) / "Updata" / "DJCat-Pro.exe"
            worker = UpdateDownloadWorker(DOWNLOAD_URL, target)
            progress = []
            results = []
            worker.progressChanged.connect(lambda *args: progress.append(args))
            worker.finished.connect(lambda *args: results.append(args))

            with patch(
                "app.common.update_download.requests.get",
                side_effect=[probe, response],
            ) as get:
                worker.run()

            self.assertEqual(target.read_bytes(), content)
            self.assertFalse(target.with_suffix(".exe.part").exists())
            self.assertEqual(results, [(str(target), "", False)])
            self.assertEqual(progress[-1][:2], (len(content), len(content)))
            self.assertEqual(progress[-1][3], 1)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(
                get.call_args_list[0].kwargs["headers"]["Range"],
                "bytes=1-1",
            )
            self.assertTrue(DOWNLOAD_URL.endswith("/DJCat-Pro.exe"))

    def testWholeDownloadRetriesThreeTimesBeforeSucceeding(self):
        content = b"MZ" + b"installer-data"
        probe = FakeResponse([], len(content))
        response = FakeResponse([content], len(content))

        with tempfile.TemporaryDirectory() as tempDir:
            target = Path(tempDir) / "Updata" / "DJCat-Pro.exe"
            worker = UpdateDownloadWorker(DOWNLOAD_URL, target)
            retries = []
            results = []
            worker.retrying.connect(lambda *args: retries.append(args))
            worker.finished.connect(lambda *args: results.append(args))

            with (
                patch(
                    "app.common.update_download.requests.get",
                    side_effect=[
                        requests.ConnectionError("temporary")
                        for _ in range(DOWNLOAD_RETRY_COUNT)
                    ]
                    + [probe, response],
                ) as get,
                patch.object(worker._cancelEvent, "wait", return_value=False),
            ):
                worker.run()

            self.assertEqual(target.read_bytes(), content)
            self.assertEqual(results, [(str(target), "", False)])
            self.assertEqual(
                [retry[:2] for retry in retries],
                [(1, 3), (2, 3), (3, 3)],
            )
            self.assertEqual(get.call_count, 5)

    def testCanceledDownloadDeletesPartialAndFinalFilesBeforeFinishing(self):
        with tempfile.TemporaryDirectory() as tempDir:
            target = Path(tempDir) / "Updata" / "DJCat-Pro.exe"
            worker = UpdateDownloadWorker(DOWNLOAD_URL, target)

            def chunks():
                yield b"MZ-partial"
                worker.cancel()
                yield b"must-not-be-written"

            response = FakeResponse(chunks())
            probe = FakeResponse([], contentLength=100)
            results = []
            worker.finished.connect(
                lambda *args: results.append(
                    (args, target.exists(), worker.partialPath.exists())
                )
            )

            with patch(
                "app.common.update_download.requests.get",
                side_effect=[probe, response],
            ):
                worker.run()

            self.assertEqual(results, [(('', '', True), False, False)])
            self.assertTrue(response.closed)

    def testDefaultRangeDownloadUsesEightWorkers(self):
        content = b"MZ" + bytes((index % 251 for index in range(2 * 1024 * 1024)))
        state = {"active": 0, "maxActive": 0, "ranges": []}
        stateLock = threading.Lock()

        class RangeHandler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                rangeHeader = self.headers.get("Range")
                if not rangeHeader:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(content)
                    return

                startText, endText = rangeHeader.removeprefix("bytes=").split("-")
                start = int(startText)
                end = int(endText) if endText else len(content) - 1
                end = min(end, len(content) - 1)
                body = content[start : end + 1]

                with stateLock:
                    state["active"] += 1
                    state["maxActive"] = max(state["maxActive"], state["active"])
                    state["ranges"].append((start, end))
                try:
                    time.sleep(0.03)
                    self.send_response(206)
                    self.send_header(
                        "Content-Range",
                        f"bytes {start}-{end}/{len(content)}",
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                finally:
                    with stateLock:
                        state["active"] -= 1

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
        serverThread = threading.Thread(target=server.serve_forever, daemon=True)
        serverThread.start()
        try:
            with tempfile.TemporaryDirectory() as tempDir:
                target = Path(tempDir) / "Updata" / "DJCat-Pro.exe"
                url = f"http://127.0.0.1:{server.server_port}/DJCat-Pro.exe"
                worker = UpdateDownloadWorker(url, target)
                results = []
                worker.finished.connect(lambda *args: results.append(args))

                worker.run()

                self.assertEqual(target.read_bytes(), content)
                self.assertEqual(results, [(str(target), "", False)])
        finally:
            server.shutdown()
            server.server_close()
            serverThread.join(timeout=2)

        dataRanges = [item for item in state["ranges"] if item != (1, 1)]
        self.assertEqual(INITIAL_THREAD_COUNT, 8)
        self.assertGreaterEqual(len(dataRanges), INITIAL_THREAD_COUNT)
        self.assertGreater(state["maxActive"], 1)

    def testConcurrentDownloadsShareAGlobalWorkerLimit(self):
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
            )
            gate = threading.Event()
            saturated = threading.Event()
            state = {"active": 0, "peak": 0}
            stateLock = threading.Lock()
            errors = []

            def downloadSegment(_url, segment):
                with stateLock:
                    state["active"] += 1
                    state["peak"] = max(state["peak"], state["active"])
                    if state["active"] >= 2:
                        saturated.set()
                try:
                    gate.wait(1)
                    with segment.lock:
                        received = segment.remainingBytes
                        segment.receivedBytes += received
                    with worker._progressLock:
                        worker._downloaded += received
                finally:
                    with stateLock:
                        state["active"] -= 1

            def run():
                try:
                    worker._downloadRanged(DOWNLOAD_URL, 32)
                except Exception as error:
                    errors.append(error)

            with (
                patch.object(
                    updateDownloadModule,
                    "_DOWNLOAD_THREAD_SLOTS",
                    threading.BoundedSemaphore(2),
                    create=True,
                ),
                patch.object(
                    worker,
                    "_downloadSegment",
                    side_effect=downloadSegment,
                ),
            ):
                thread = threading.Thread(target=run)
                thread.start()
                self.assertTrue(saturated.wait(1))
                time.sleep(0.05)
                self.assertLessEqual(state["peak"], 2)
                gate.set()
                thread.join(3)

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(worker._downloaded, 32)

    def testRangeChunksDoNotFloodProgressSignalQueue(self):
        chunks = [b"x" * 64 for _ in range(200)]
        total = sum(map(len, chunks))
        response = FakeResponse(
            chunks,
            statusCode=206,
            headers={"Content-Range": f"bytes 0-{total - 1}/{total}"},
        )

        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
            )
            segment = DownloadSegment(0, 0, total - 1)
            worker._segments = [segment]
            worker._activeWorkers = 1
            worker.partialPath.touch()
            with worker.partialPath.open("r+b") as file:
                file.truncate(total)
            progress = []
            worker.progressChanged.connect(lambda *args: progress.append(args))

            with patch("app.common.update_download.requests.get", return_value=response):
                worker._downloadSegment(DOWNLOAD_URL, segment)

        self.assertLess(len(progress), len(chunks) // 10)
        self.assertEqual(progress[-1][:2], (total, total))

    def testEmptyPartialRangeResponseStopsAfterBoundedRetries(self):
        responses = [
            FakeResponse(
                [],
                statusCode=206,
                headers={"Content-Range": "bytes 0-9/10"},
            )
            for _ in range(MAX_RETRIES)
        ]
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
            )
            worker.partialPath.touch()
            worker.partialPath.write_bytes(b"\0" * 10)
            segment = DownloadSegment(0, 0, 9)
            with (
                patch(
                    "app.common.update_download.requests.get",
                    side_effect=responses,
                ) as get,
                patch.object(worker._cancelEvent, "wait", return_value=False),
            ):
                with self.assertRaisesRegex(OSError, "分段下载响应不完整"):
                    worker._downloadSegment(DOWNLOAD_URL, segment)

        self.assertEqual(get.call_count, MAX_RETRIES)
        self.assertTrue(all(response.closed for response in responses))

    def testEveryDownloadResponseMustRemainHttps(self):
        insecureUrl = "http://example.test/update.exe"
        single = FakeResponse([b"MZ"], contentLength=2, url=insecureUrl)
        ranged = FakeResponse(
            [b"MZ"],
            statusCode=206,
            headers={"Content-Range": "bytes 0-1/2"},
            url=insecureUrl,
        )
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
                requireHttps=True,
            )
            worker.partialPath.touch()
            worker.partialPath.write_bytes(b"\0\0")
            with patch(
                "app.common.update_download.requests.get",
                side_effect=[single, ranged],
            ):
                with self.assertRaisesRegex(OSError, "必须保持 HTTPS"):
                    worker._downloadSingle(DOWNLOAD_URL, 2)
                with self.assertRaisesRegex(OSError, "必须保持 HTTPS"):
                    worker._downloadSegment(
                        DOWNLOAD_URL,
                        DownloadSegment(0, 0, 1),
                    )

        self.assertTrue(single.closed)
        self.assertTrue(ranged.closed)

    def testDownloadRejectsHttpInIntermediateRedirect(self):
        response = FakeResponse([b"MZ"], contentLength=2)
        response.history = [Mock(url="http://mirror.example.test/update.exe")]
        with tempfile.TemporaryDirectory() as tempDir:
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
                requireHttps=True,
            )
            with patch(
                "app.common.update_download.requests.get",
                return_value=response,
            ):
                with self.assertRaisesRegex(OSError, "必须保持 HTTPS"):
                    worker._downloadSingle(DOWNLOAD_URL, 2)

        self.assertTrue(response.closed)

    def testSmartAccelerationMatchesCloudGhostPolicy(self):
        controller = SmartAccelerationController()

        additions = [
            controller.sample(1_000_000, 32, second)
            for second in range(1, 6)
        ]

        self.assertEqual(additions[-1], SMART_THREAD_STEP)
        self.assertFalse(controller.disabled)

        controller.sample(1_000_000, 36, 11)
        self.assertTrue(controller.disabled)

    def testCancelWaitsForOpenPartialFileBeforeFinishing(self):
        with tempfile.TemporaryDirectory() as tempDir:
            app = QApplication.instance() or QApplication([])
            worker = UpdateDownloadWorker(
                DOWNLOAD_URL,
                Path(tempDir) / "update.exe",
            )
            started = threading.Event()
            release = threading.Event()
            errors = []
            results = []

            def blockedSegment(_url, _segment):
                with worker.partialPath.open("r+b"):
                    started.set()
                    release.wait(2)

            worker.finished.connect(lambda *args: results.append(args))

            with (
                patch("app.common.update_download.INITIAL_THREAD_COUNT", 1),
                patch.object(
                    worker,
                    "_probeDownload",
                    return_value=(DOWNLOAD_URL, 1024, True),
                ),
                patch.object(worker, "_downloadSegment", side_effect=blockedSegment),
            ):
                thread = threading.Thread(
                    target=lambda: self._captureError(
                        errors,
                        worker.run,
                    )
                )
                try:
                    thread.start()
                    self.assertTrue(started.wait(1))
                    worker.cancel()
                    thread.join(0.4)
                    self.assertTrue(thread.is_alive())
                    self.assertEqual(results, [])
                    self.assertEqual(errors, [])
                finally:
                    release.set()
                    thread.join(2)
                    app.processEvents()

            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(results, [("", "", True)])
            self.assertFalse(worker.partialPath.exists())

    @staticmethod
    def _captureError(errors, callback, *args):
        try:
            callback(*args)
        except Exception as error:
            errors.append(error)

    def testSlowestSegmentSplitKeepsCompleteNonOverlappingCoverage(self):
        worker = UpdateDownloadWorker(DOWNLOAD_URL, Path("DJCat-Pro.exe"))
        total = 64 * 1024 * 1024
        worker._segments = worker._buildSegments(total, INITIAL_THREAD_COUNT)

        newSegment = worker._splitSlowest()

        self.assertIsNotNone(newSegment)
        self.assertEqual(MIN_REASSIGN_SIZE, 64 * 1024)
        ordered = sorted(worker._segments, key=lambda segment: segment.start)
        self.assertEqual(ordered[0].start, 0)
        self.assertEqual(ordered[-1].end, total - 1)
        for left, right in zip(ordered, ordered[1:]):
            self.assertEqual(left.end + 1, right.start)


class UpdateWindowLifecycleTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        self.quotaPatcher.start()
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)

    def tearDown(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.quotaPatcher.stop()

    def testClickingDownloadClosesVersionBarAndStartsStateToolTip(self):
        InfoBarStub.instances.clear()
        self.window.show()
        self.app.processEvents()
        worker = DownloadWorkerStub("", Path())
        thread = ThreadStub(lambda: None, True)

        with (
            patch("app.view.windows.main_window.InfoBar", InfoBarStub),
            patch("app.view.windows.main_window.PrimaryPushButton", ButtonStub),
            patch("app.view.windows.main_window.PushButton", ButtonStub),
            patch(
                "app.view.windows.main_window.StateToolTip",
                StateToolTipStub,
            ),
            patch(
                "app.view.windows.main_window.UpdateDownloadWorker",
                return_value=worker,
            ) as workerFactory,
            patch(
                "app.view.windows.main_window.threading.Thread",
                return_value=thread,
            ),
        ):
            self.window._onUpdateChecked(
                {"latest_version": "9999.0.0", "update_note": "note"},
                "",
                False,
            )
            versionBar = InfoBarStub.instances[-1]
            versionBar.widgets[0].clicked.emit()
            worker.progressChanged.emit(50, 100, 1024, 32)
            QTest.qWait(120)
            self.app.processEvents()
            firstY = self.window._downloadStateToolTip.y()
            worker.retrying.emit(1, 3, "temporary")
            self.assertIn("正在重试 1/3", self.window._downloadStateToolTip.content)
            worker.progressChanged.emit(60, 100, 2048, 32)
            QTest.qWait(120)
            self.app.processEvents()

        self.assertTrue(versionBar.closed)
        self.assertIsNone(self.window._updateInfoBar)
        self.assertTrue(thread.started)
        self.assertTrue(self.window._downloadStateToolTip.shown)
        self.assertIn("60%", self.window._downloadStateToolTip.content)
        self.assertIn("32 线程", self.window._downloadStateToolTip.content)
        self.assertEqual(self.window._downloadStateToolTip.y(), firstY)
        self.assertEqual(self.window._downloadStateToolTip.suitablePosCalls, 1)
        workerFactory.assert_called_once()
        self.assertEqual(workerFactory.call_args.args[0], DOWNLOAD_URL)
        self.assertTrue(workerFactory.call_args.kwargs["requireHttps"])
        self.assertEqual(workerFactory.call_args.kwargs["maxBytes"], 1024**3)
        self.assertNotIn("checksumUrl", workerFactory.call_args.kwargs)

    def testUpdateAlwaysUsesBucketInstaller(self):
        worker = DownloadWorkerStub("", Path())
        thread = ThreadStub(lambda: None, True)
        with (
            patch(
                "app.view.windows.main_window.StateToolTip",
                StateToolTipStub,
            ),
            patch(
                "app.view.windows.main_window.UpdateDownloadWorker",
                return_value=worker,
            ) as workerFactory,
            patch(
                "app.view.windows.main_window.threading.Thread",
                return_value=thread,
            ),
        ):
            self.window._startUpdateDownload("5.0.0-pre.22")

        self.assertEqual(workerFactory.call_args.args[0], DOWNLOAD_URL)

    def testStartingAnotherDownloadDisposesOnlyThePreviousTooltip(self):
        oldToolTip = StateToolTipStub("old", "old", self.window)
        oldToolTip.destroyed.connect(
            lambda _=None, current=oldToolTip: self.window._clearDownloadStateToolTip(
                current
            )
        )
        self.window._downloadStateToolTip = oldToolTip
        worker = DownloadWorkerStub("", Path())
        thread = ThreadStub(lambda: None, True)
        with (
            patch(
                "app.view.windows.main_window.StateToolTip",
                StateToolTipStub,
            ),
            patch(
                "app.view.windows.main_window.UpdateDownloadWorker",
                return_value=worker,
            ),
            patch(
                "app.view.windows.main_window.threading.Thread",
                return_value=thread,
            ),
        ):
            self.window._startUpdateDownload("5.0.0-pre.22")

        newToolTip = self.window._downloadStateToolTip
        self.assertIsNot(newToolTip, oldToolTip)
        self.assertTrue(oldToolTip.hidden)
        self.assertTrue(oldToolTip.deleted)
        oldToolTip.destroyed.emit(object())
        self.assertIs(self.window._downloadStateToolTip, newToolTip)

    def testDownloadProgressIsCoalescedBeforeUpdatingTooltip(self):
        toolTip = StateToolTipStub("", "", self.window)
        self.window._downloadStateToolTip = toolTip

        with patch.object(self.window, "_onUpdateDownloadProgress") as update:
            self.window._queueUpdateDownloadProgress(10, 100, 1, 4)
            self.window._queueUpdateDownloadProgress(20, 100, 2, 4)
            QTest.qWait(120)
            self.app.processEvents()

        update.assert_called_once_with(20, 100, 2, 4)

    def testDisposingAlreadyDeletedStateToolTipIsSafe(self):
        from qfluentwidgets import StateToolTip

        toolTip = StateToolTip("", "", self.window)
        self.window._downloadStateToolTip = toolTip
        delete(toolTip)
        tray = Mock()
        tray.parent.return_value = self.window

        with (
            patch("app.view.windows.main_window.cfg.set"),
            patch("app.view.windows.main_window.QApplication.quit") as quitApp,
        ):
            SystemTrayIcon._onQuitActionTriggered(tray)

        self.assertIsNone(self.window._downloadStateToolTip)
        quitApp.assert_called_once_with()

    def testDestroyedUpdateInfoBarClearsCapturedReference(self):
        InfoBarStub.instances.clear()
        self.window.show()
        self.app.processEvents()

        with (
            patch("app.view.windows.main_window.InfoBar", InfoBarStub),
            patch("app.view.windows.main_window.PrimaryPushButton", ButtonStub),
            patch("app.view.windows.main_window.PushButton", ButtonStub),
        ):
            self.window._onUpdateChecked(
                {"latest_version": "9999.0.0", "update_note": "note"},
                "",
                False,
            )
            infoBar = InfoBarStub.instances[-1]
            infoBar.destroyed.emit(object())

        self.assertIsNone(self.window._updateInfoBar)
        with patch("app.view.windows.main_window.QApplication.quit") as quitApp:
            self.window.requestQuit()
        quitApp.assert_called_once_with()

    def testSilentStartupRestoresGeometryWhenFirstShown(self):
        savedGeometry = QRect(80, 60, 900, 520)
        originalGeometry = cfg.geometry.value
        cfg.geometry.value = savedGeometry
        self.addCleanup(setattr, cfg.geometry, "value", originalGeometry)

        self.assertFalse(self.window._geometryApplied)
        self.window.show()
        self.app.processEvents()

        self.assertTrue(self.window._geometryApplied)
        self.assertEqual(self.window.geometry(), savedGeometry)

        self.window.setGeometry(100, 90, 820, 480)
        self.window.hide()
        self.window.show()
        self.app.processEvents()
        self.assertEqual(self.window.geometry(), QRect(100, 90, 820, 480))

    def testHiddenUpdateInfoBarWaitsForTrayShowAndUsesRestoredGeometry(self):
        savedGeometry = QRect(80, 60, 900, 520)
        originalGeometry = cfg.geometry.value
        cfg.geometry.value = savedGeometry
        self.addCleanup(setattr, cfg.geometry, "value", originalGeometry)

        self.window._onUpdateChecked(
            {"latest_version": "9999.0.0", "update_note": "note"},
            "",
            False,
        )

        self.assertIsNone(self.window._updateInfoBar)

        tray = Mock()
        tray.parent.return_value = self.window
        SystemTrayIcon._onShowActionTriggered(tray)
        self.app.processEvents()
        QTest.qWait(250)
        self.app.processEvents()

        infoBar = self.window._updateInfoBar
        self.assertIsNotNone(infoBar)
        self.assertEqual(
            infoBar.x(),
            self.window.width() - infoBar.width() - 24,
        )

    def testVisibleUpdateInfoBarUsesCurrentGeometry(self):
        self.window.show()
        self.app.processEvents()

        self.window._onUpdateChecked(
            {"latest_version": "9999.0.0", "update_note": "note"},
            "",
            False,
        )
        self.app.processEvents()
        QTest.qWait(250)
        self.app.processEvents()

        infoBar = self.window._updateInfoBar
        self.assertIsNotNone(infoBar)
        self.assertEqual(
            infoBar.x(),
            self.window.width() - infoBar.width() - 24,
        )

    def testOffscreenGeometryFallsBackToDefaultSize(self):
        originalGeometry = cfg.geometry.value
        cfg.geometry.value = QRect(5000, 5000, 900, 520)
        self.addCleanup(setattr, cfg.geometry, "value", originalGeometry)

        with patch.object(QApplication, "screenAt", return_value=None):
            self.window.show()
            self.app.processEvents()

        self.assertEqual(self.window.size(), QSize(800, 450))

    def testMaximizedWindowDoesNotOverwriteNormalGeometry(self):
        with (
            patch.object(self.window, "isMaximized", return_value=True),
            patch("app.view.windows.main_window.cfg.set") as setConfig,
        ):
            self.window._saveGeometry()

        setConfig.assert_not_called()

    def testClosingWindowDoesNotCancelDownload(self):
        worker = DownloadWorkerStub("", Path())
        self.window._downloadWorker = worker
        self.window.show()

        with patch("app.view.windows.main_window.cfg.set"):
            self.window.close()
            self.app.processEvents()

        self.assertFalse(self.window.isVisible())
        self.assertFalse(worker.canceled)

    def testCompletedDownloadRestoresHiddenWindowBeforeInfoBar(self):
        worker = DownloadWorkerStub("", Path())
        toolTip = StateToolTipStub("", "", self.window)
        self.window._downloadWorker = worker
        self.window._downloadStateToolTip = toolTip
        self.window._downloadVersion = "9999.0.0"
        self.window.hide()

        with tempfile.TemporaryDirectory() as tempDir:
            installer = Path(tempDir) / "DJCat-Pro.exe"
            installer.write_bytes(b"MZ")
            with patch.object(
                self.window,
                "_showInstallUpdateInfoBar",
            ) as showInfoBar:
                self.window._onUpdateDownloadFinished(
                    str(installer),
                    "",
                    False,
                )

        self.assertTrue(self.window.isVisible())
        self.assertTrue(worker.deleted)
        self.assertTrue(toolTip.state)
        showInfoBar.assert_called_once()

    def testTrayExitCancelsDownloadAndWaitsBeforeQuitting(self):
        worker = DownloadWorkerStub("", Path())
        self.window._downloadWorker = worker

        with (
            patch("app.view.windows.main_window.cfg.set"),
            patch("app.view.windows.main_window.QApplication.quit") as quitApp,
        ):
            self.window.requestQuit()

        self.assertTrue(worker.canceled)
        self.assertTrue(self.window._quitAfterDownload)
        quitApp.assert_not_called()

        with (
            patch("app.view.windows.main_window.clearUpdateDirectory") as clear,
            patch("app.view.windows.main_window.QApplication.quit") as quitApp,
        ):
            self.window._onUpdateDownloadFinished("", "", True)

        clear.assert_called_once_with()
        quitApp.assert_called_once_with()

    def testTrayActionDelegatesToControlledQuit(self):
        parent = Mock()
        tray = Mock()
        tray.parent.return_value = parent

        SystemTrayIcon._onQuitActionTriggered(tray)

        parent.requestQuit.assert_called_once_with()

    def testOnlyLatestOverlappingUpdateCheckCanChangeTheUi(self):
        firstWorker = Mock()
        secondWorker = Mock()
        self.window._updateRequestId = 2
        self.window._updateJobs = {
            1: (firstWorker, Mock(), False),
            2: (secondWorker, Mock(), True),
        }

        with patch.object(self.window, "_onUpdateChecked") as checked:
            self.window._onUpdateCheckFinished(1, {"latest_version": "1"}, "")
            checked.assert_not_called()
            self.window._onUpdateCheckFinished(2, {"latest_version": "2"}, "")

        firstWorker.deleteLater.assert_called_once_with()
        secondWorker.deleteLater.assert_called_once_with()
        checked.assert_called_once_with({"latest_version": "2"}, "", True)
        self.assertEqual(self.window._updateJobs, {})

    def testUpdateWorkerCarriesItsRequestIdToCompletion(self):
        response = Mock()
        response.json.return_value = {"latest_version": "9999.0.0"}
        results = []
        worker = UpdateWorker(17)
        worker.finished.connect(lambda *args: results.append(args))

        with patch(
            "app.view.windows.main_window.requests.get",
            return_value=response,
        ):
            worker.run()

        self.assertEqual(
            results,
            [(17, {"latest_version": "9999.0.0"}, "")],
        )
        response.close.assert_called_once_with()

    def testUpdateCheckRetriesThreeTimesBeforeSucceeding(self):
        response = Mock()
        response.json.return_value = {"latest_version": "9999.0.0"}
        results = []
        worker = UpdateWorker(18)
        worker.finished.connect(lambda *args: results.append(args))

        with (
            patch(
                "app.view.windows.main_window.requests.get",
                side_effect=[
                    requests.ConnectionError("temporary")
                    for _ in range(worker.RETRY_COUNT)
                ]
                + [response],
            ) as get,
            patch("app.view.windows.main_window.time.sleep") as sleep,
        ):
            worker.run()

        self.assertEqual(get.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(
            results,
            [(18, {"latest_version": "9999.0.0"}, "")],
        )
        response.close.assert_called_once_with()

    def testUpdateWorkerRejectsNonObjectJson(self):
        response = Mock()
        response.json.return_value = []
        results = []
        worker = UpdateWorker(19)
        worker.finished.connect(lambda *args: results.append(args))

        with (
            patch.object(worker, "RETRY_COUNT", 0),
            patch(
                "app.view.windows.main_window.requests.get",
                return_value=response,
            ),
        ):
            worker.run()

        self.assertEqual(results[0][:2], (19, {}))
        self.assertIn("格式无效", results[0][2])
        response.close.assert_called_once_with()

    def testUpdateWorkerRejectsHttpInIntermediateRedirect(self):
        response = Mock()
        response.url = "https://api.djcatpro.top/beta/"
        response.history = [Mock(url="http://mirror.example.test/beta/")]
        response.json.return_value = {"latest_version": "9999.0.0"}
        results = []
        worker = UpdateWorker(20)
        worker.finished.connect(lambda *args: results.append(args))

        with (
            patch.object(worker, "RETRY_COUNT", 0),
            patch(
                "app.view.windows.main_window.requests.get",
                return_value=response,
            ),
        ):
            worker.run()

        self.assertEqual(results[0][:2], (20, {}))
        self.assertIn("必须保持 HTTPS", results[0][2])
        response.close.assert_called_once_with()

    def testMalformedRemoteVersionIsRejectedBeforeShowingUpdate(self):
        with (
            patch.object(self.window, "_showUpdateInfoBar") as showUpdate,
            patch("app.view.windows.main_window.InfoBar.error") as showError,
        ):
            self.window._onUpdateChecked(
                {"latest_version": "9999/evil", "update_note": "bad"},
                "",
                True,
            )

        showUpdate.assert_not_called()
        showError.assert_called_once()

    def testReleaseVersionNormalizationRejectsMalformedValues(self):
        self.assertEqual(normalizeReleaseVersion("v5.0.0-pre.22"), "5.0.0-pre.22")
        for version in (None, "", "nonsense", "9999/evil"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                normalizeReleaseVersion(version)

    def testOlderRemoteVersionDoesNotShowUpdate(self):
        with (
            patch("app.view.windows.main_window.VERSION", "5.0.0"),
            patch.object(self.window, "_showUpdateInfoBar") as showUpdate,
        ):
            self.window._onUpdateChecked(
                {"latest_version": "4.9.0", "update_note": "old"},
                "",
                False,
            )

        showUpdate.assert_not_called()
        self.assertIsNone(self.window._pendingUpdateNotification)

    def testEscapedUpdateNoteDoesNotCorruptExistingChinese(self):
        with patch.object(self.window, "_showUpdateInfoBar") as showUpdate:
            self.window._onUpdateChecked(
                {
                    "latest_version": "9999.0.0",
                    "update_note": r"更新 \u4f60\u597d",
                },
                "",
                True,
            )

        self.assertEqual(showUpdate.call_args.args[1], "更新 你好")

    def testManualCheckClosesPendingBarBeforeShowingResult(self):
        order = []
        checkBar = Mock()
        checkBar.close.side_effect = lambda: order.append("close")
        worker = Mock()
        self.window._updateRequestId = 1
        self.window._updateCheckInfoBar = checkBar
        self.window._updateJobs = {1: (worker, Mock(), True)}

        with patch.object(
            self.window,
            "_onUpdateChecked",
            side_effect=lambda *_: order.append("result"),
        ):
            self.window._onUpdateCheckFinished(
                1,
                {"latest_version": "9999.0.0"},
                "",
            )

        self.assertEqual(order, ["close", "result"])
        self.assertIsNone(self.window._updateCheckInfoBar)

    def testRepeatedUpdateChecksReuseTheInFlightRequest(self):
        worker = Mock()
        worker.finished = SignalStub()
        thread = ThreadStub(worker.run, True)
        with (
            patch("app.view.windows.main_window.InfoBar", InfoBarStub),
            patch(
                "app.view.windows.main_window.UpdateWorker",
                return_value=worker,
            ) as workerFactory,
            patch(
                "app.view.windows.main_window.threading.Thread",
                return_value=thread,
            ) as threadFactory,
        ):
            self.window.checkForUpdates(False)
            self.window.checkForUpdates(True)

        self.assertEqual(workerFactory.call_count, 1)
        self.assertEqual(threadFactory.call_count, 1)
        self.assertEqual(len(self.window._updateJobs), 1)
        self.assertTrue(next(iter(self.window._updateJobs.values()))[2])
        self.assertIsNotNone(self.window._updateCheckInfoBar)
        self.window._updateJobs.clear()

    def testUpdateDialogIsScheduledForDeletionAfterClosing(self):
        dialog = Mock()
        dialog.exec.return_value = False
        with patch(
            "app.view.windows.main_window.UpdateDialog",
            return_value=dialog,
        ):
            self.window._showUpdateLog("9999.0.0", "note")

        dialog.deleteLater.assert_called_once_with()

    def testShutdownResourcesStopsRuntimeWorkOnlyOnce(self):
        downloadWorker = Mock()
        self.window._downloadWorker = downloadWorker
        self.window.scheduleTimer = Mock()
        self.window.tts = Mock()
        self.window.player = Mock()

        with (
            patch.object(self.window, "_cancelPendingEdgeTts") as cancelEdge,
            patch.object(self.window, "_cleanupEdgeTtsFile") as cleanupEdge,
            patch.object(self.window.homePage, "shutdown") as homeShutdown,
            patch.object(self.window.appStorePage, "shutdown") as appStoreShutdown,
            patch.object(
                self.window,
                "_disposeDownloadStateToolTip",
            ) as disposeToolTip,
        ):
            self.window._shutdownResources()
            self.window._shutdownResources()
            self.window.switchTo(self.window.settingPage)

        self.window.scheduleTimer.stop.assert_called_once_with()
        cancelEdge.assert_called_once_with()
        self.window.tts.stop.assert_called_once_with()
        self.window.player.stop.assert_called_once_with()
        cleanupEdge.assert_called_once_with()
        downloadWorker.cancel.assert_called_once_with()
        homeShutdown.assert_called_once_with()
        appStoreShutdown.assert_called_once_with()
        disposeToolTip.assert_called_once_with()
        self.assertIsNone(self.window._navigationTarget)
        self.assertIsNone(self.window._pendingNavigation)

    def testInstallerLaunchDialogOnlyContainsIndeterminateProgressRing(self):
        dialog = InstallerLaunchDialog(self.window)

        self.assertTrue(dialog.isModal())
        self.assertTrue(dialog.buttonGroup.isHidden())
        self.assertEqual(dialog.viewLayout.count(), 1)
        self.assertIs(dialog.viewLayout.itemAt(0).widget(), dialog.progressRing)

        delete(dialog)

    def testInstallerStartsInBackgroundBeforeApplicationQuits(self):
        infoBar = Mock()
        dialog = InstallerLaunchDialogStub()
        thread = ThreadStub(lambda: None, True)
        with tempfile.TemporaryDirectory() as tempDir:
            installer = Path(tempDir) / "DJCat-Pro.exe"
            installer.write_bytes(b"MZ")
            with (
                patch(
                    "app.view.windows.main_window.QProcess.startDetached",
                    return_value=(True, 1234),
                ) as startDetached,
                patch(
                    "app.view.windows.main_window.InstallerLaunchDialog",
                    return_value=dialog,
                ),
                patch(
                    "app.view.windows.main_window.threading.Thread",
                    return_value=thread,
                ),
                patch(
                    "app.view.windows.main_window.isValid",
                    return_value=True,
                ),
                patch(
                    "app.view.windows.main_window.QApplication.quit"
                ) as quitApp,
            ):
                self.window._launchUpdateInstaller(installer, infoBar)
                worker = self.window._installerLaunchWorker

                self.assertTrue(dialog.shown)
                self.assertTrue(thread.started)
                startDetached.assert_not_called()
                quitApp.assert_not_called()

                worker.run()

        startDetached.assert_called_once_with(str(installer), [])
        infoBar.close.assert_called_once_with()
        self.assertTrue(dialog.finished)
        self.assertIsNone(self.window._installerLaunchWorker)
        self.assertIsNone(self.window._installerLaunchThread)
        self.assertIsNone(self.window._installerLaunchDialog)
        quitApp.assert_called_once_with()

    def testInstallerLaunchFailureClosesDialogAndKeepsApplicationOpen(self):
        infoBar = Mock()
        dialog = InstallerLaunchDialogStub()
        thread = ThreadStub(lambda: None, True)
        with tempfile.TemporaryDirectory() as tempDir:
            installer = Path(tempDir) / "DJCat-Pro.exe"
            installer.write_bytes(b"MZ")
            with (
                patch(
                    "app.view.windows.main_window.QProcess.startDetached",
                    return_value=(False, 0),
                ),
                patch(
                    "app.view.windows.main_window.InstallerLaunchDialog",
                    return_value=dialog,
                ),
                patch(
                    "app.view.windows.main_window.threading.Thread",
                    return_value=thread,
                ),
                patch(
                    "app.view.windows.main_window.isValid",
                    return_value=True,
                ),
                patch(
                    "app.view.windows.main_window.InfoBar.error",
                ) as showError,
                patch(
                    "app.view.windows.main_window.QApplication.quit"
                ) as quitApp,
            ):
                self.window._launchUpdateInstaller(installer, infoBar)
                self.window._installerLaunchWorker.run()

        self.assertTrue(dialog.finished)
        showError.assert_called_once()
        quitApp.assert_not_called()
