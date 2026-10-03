import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar

from app.common import logs
from app.view.windows.main_window import MainWindow


class LogFilesTest(TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.logDir = root / "DJCatPro" / "Log"
        self.legacyDir = root / "Log"
        self.updaterLog = root / "updater.log"
        for name, value in (
            ("LOG_DIR", self.logDir),
            ("LEGACY_LOG_DIR", self.legacyDir),
            ("UPDATER_LOG_PATH", self.updaterLog),
        ):
            patcher = patch.object(logs, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def writeLog(self, path: Path, *, daysAgo: float, size: int = 10) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        stamp = time.time() - daysAgo * 24 * 60 * 60
        os.utime(path, (stamp, stamp))
        return path

    def configure(self):
        with patch.object(logs.logger, "add") as add:
            logs.configureLogging()
        return add

    def testLogsRotateDailyInsideAppDataDirectoryAndKeepFourteenDays(self):
        add = self.configure()

        self.assertEqual(add.call_args.args[0], str(self.logDir / logs.LOG_FILE_NAME))
        self.assertEqual(add.call_args.kwargs["rotation"], "00:00")
        self.assertEqual(add.call_args.kwargs["retention"], "14 days")

    def testStartupRemovesLogsOlderThanFourteenDays(self):
        expired = self.writeLog(self.logDir / "djcatpro日志_2026-09-01.log", daysAgo=15)
        kept = self.writeLog(self.logDir / "djcatpro日志_2026-09-21.log", daysAgo=13)
        expiredUpdater = self.writeLog(self.updaterLog, daysAgo=15)
        unrelated = self.writeLog(self.logDir / "readme.txt", daysAgo=30)

        self.configure()

        self.assertFalse(expired.exists())
        self.assertFalse(expiredUpdater.exists())
        self.assertTrue(kept.exists())
        self.assertTrue(unrelated.exists())

    def testLogsLeftInProgramDirectoryMoveIntoAppDataDirectory(self):
        name = "djcatpro日志_2026-09-30.log"
        self.writeLog(self.legacyDir / name, daysAgo=3, size=7)

        self.configure()

        self.assertEqual((self.logDir / name).stat().st_size, 7)
        self.assertFalse(self.legacyDir.exists())

    def testLegacyLogNeverOverwritesOneAlreadyInAppDataDirectory(self):
        name = "djcatpro日志_2026-10-02.log"
        self.writeLog(self.legacyDir / name, daysAgo=1, size=3)
        current = self.writeLog(self.logDir / name, daysAgo=1, size=5)

        self.configure()

        self.assertEqual(current.stat().st_size, 5)
        self.assertTrue((self.legacyDir / name).exists())

    def testClearingSkipsOnlyTheLogBeingWritten(self):
        older = self.writeLog(self.logDir / "djcatpro日志_2026-10-01.log", daysAgo=2, size=100)
        writing = self.writeLog(self.logDir / "djcatpro日志_2026-10-03.log", daysAgo=0, size=40)
        updater = self.writeLog(self.updaterLog, daysAgo=1, size=7)

        self.assertEqual(logs.clearableLogSize(), 107)

        logs.clearLogs()

        self.assertFalse(older.exists())
        self.assertFalse(updater.exists())
        self.assertTrue(writing.exists())
        self.assertEqual(logs.clearableLogSize(), 0)

    def testNothingToClearWithoutLogs(self):
        self.assertEqual(logs.clearableLogSize(), 0)
        logs.clearLogs()


class ExceptionInfoBarTest(TestCase):
    def testInfoBarWithLogButtonSlidesFullyInsideWindow(self):
        window = QWidget()
        window.resize(640, 480)
        window.show()
        try:
            MainWindow._onExceptionCaught(window, "boom")
            infoBar = window.findChild(InfoBar)
            # 滑入动画 200 ms；这期间没有任何东西会让 InfoBarManager 重算位置。
            QTest.qWait(400)

            self.assertTrue(
                window.rect().contains(infoBar.geometry()),
                f"{infoBar.geometry()} 超出 {window.rect()}",
            )
        finally:
            window.close()
            window.deleteLater()
