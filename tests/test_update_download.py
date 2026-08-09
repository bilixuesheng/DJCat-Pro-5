import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QRect, QSize
from PySide6.QtWidgets import QApplication

import djcat
from app.common.update_download import (
    INITIAL_THREAD_COUNT,
    MIN_REASSIGN_SIZE,
    SMART_THREAD_STEP,
    SmartAccelerationController,
    UpdateDownloadWorker,
    clearUpdateDirectory,
)
from app.config.cfg import cfg
from app.config.constants import DOWNLOAD_URL
from app.view.pages.setting_page import SettingPage
from app.view.shell.tray import SystemTrayIcon
from app.view.windows.main_window import MainWindow, UpdateWorker


class FakeResponse:
    def __init__(self, chunks, contentLength=None, statusCode=200, headers=None):
        self.chunks = chunks
        self.headers = dict(headers or {})
        if contentLength is not None:
            self.headers["Content-Length"] = str(contentLength)
        self.status_code = statusCode
        self.url = DOWNLOAD_URL
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

    def getSuitablePos(self):
        return (0, 0)

    def move(self, _):
        pass

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


class DownloadWorkerStub:
    def __init__(self, url, targetPath):
        self.url = url
        self.targetPath = targetPath
        self.progressChanged = SignalStub()
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

    def testDefaultRangeDownloadUsesThirtyTwoWorkers(self):
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
        self.assertEqual(INITIAL_THREAD_COUNT, 32)
        self.assertGreaterEqual(len(dataRanges), INITIAL_THREAD_COUNT)
        self.assertGreater(state["maxActive"], 1)

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

        self.assertTrue(versionBar.closed)
        self.assertIsNone(self.window._updateInfoBar)
        self.assertTrue(thread.started)
        self.assertTrue(self.window._downloadStateToolTip.shown)
        self.assertIn("50%", self.window._downloadStateToolTip.content)
        self.assertIn("32 线程", self.window._downloadStateToolTip.content)
        workerFactory.assert_called_once()
        self.assertEqual(workerFactory.call_args.args[0], DOWNLOAD_URL)

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
        disposeToolTip.assert_called_once_with()
        self.assertIsNone(self.window._navigationTarget)
        self.assertIsNone(self.window._pendingNavigation)

    def testInstallerStartsBeforeApplicationQuits(self):
        infoBar = Mock()
        with tempfile.TemporaryDirectory() as tempDir:
            installer = Path(tempDir) / "DJCat-Pro.exe"
            installer.write_bytes(b"MZ")
            with (
                patch(
                    "app.view.windows.main_window.QProcess.startDetached",
                    return_value=(True, 1234),
                ) as startDetached,
                patch(
                    "app.view.windows.main_window.QApplication.quit"
                ) as quitApp,
            ):
                self.window._launchUpdateInstaller(installer, infoBar)

        startDetached.assert_called_once_with(str(installer), [])
        infoBar.close.assert_called_once_with()
        quitApp.assert_called_once_with()
