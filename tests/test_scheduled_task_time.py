"""Scheduled Task 按 Bell Time 匹配，设为不偏移的种类按 Calibrated Time。"""

from datetime import datetime
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg

LOCAL = datetime.now().astimezone().tzinfo


def at(hour, minute, second, microsecond=0, day=23):
    return datetime(2026, 10, day, hour, minute, second, microsecond, tzinfo=LOCAL)


def task(time="08:00:00", taskId="task"):
    return {"id": taskId, "enabled": True, "weeks": list(range(7)), "time": time}


class ScheduledTaskTimeTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        for item in (
            cfg.broadcastTasksEnabled,
            cfg.homeCardTasksEnabled,
            cfg.shutdownTasksEnabled,
        ):
            cfg.set(item, True, save=False)
        cfg.set(cfg.homeCardTasks, [], save=False)
        cfg.set(cfg.timeOffsetEnabled, True, save=False)
        cfg.set(cfg.dailyDriftEnabled, False, save=False)
        cfg.set(cfg.timeOffsetExemptions, [], save=False)
        self.setOffset(-3.0)
        quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        quotaPatcher.start()
        self.addCleanup(quotaPatcher.stop)
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)
        self.addCleanup(self.closeWindow)
        self.played = []
        self.shutdowns = []
        for name, calls in (
            ("_playAudioTask", self.played),
            ("_handleShutdownTask", self.shutdowns),
        ):
            patcher = patch.object(self.window, name, side_effect=calls.append)
            patcher.start()
            self.addCleanup(patcher.stop)

    def closeWindow(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def setOffset(self, seconds):
        cfg.set(cfg.timeOffset, seconds, save=False)
        cfg.set(cfg.timeOffsetDate, "2026-10-23", save=False)

    def check(self, calibrated, broadcast=(), shutdown=()):
        cfg.set(cfg.broadcastTasks, list(broadcast), save=False)
        cfg.set(cfg.shutdownTasks, list(shutdown), save=False)
        self.window._checkScheduleAt(calibrated)

    def testTasksRunWhenBellTimeReachesThem(self):
        broadcast = [task()]

        self.check(at(8, 0, 2), broadcast)
        self.check(at(8, 0, 2, 900_000), broadcast)
        self.assertEqual(self.played, [])

        self.check(at(8, 0, 3, 100_000), broadcast)
        self.assertEqual(self.played, broadcast)

    def testExemptKindRunsAtCalibratedTime(self):
        cfg.set(cfg.timeOffsetExemptions, ["shutdown"], save=False)
        broadcast, shutdown = [task(taskId="bell")], [task(taskId="off")]

        self.check(at(7, 59, 59, 500_000), broadcast, shutdown)
        self.check(at(8, 0, 0, 500_000), broadcast, shutdown)
        self.assertEqual((self.played, self.shutdowns), ([], shutdown))

        self.check(at(8, 0, 3, 500_000), broadcast, shutdown)
        self.assertEqual((self.played, self.shutdowns), (broadcast, shutdown))

    def testOffsetChangeCatchesUpForwardAndNeverRepeats(self):
        broadcast = [task()]
        self.setOffset(0.0)
        self.check(at(7, 59, 50), broadcast)

        self.setOffset(30.0)
        self.check(at(7, 59, 51), broadcast)
        self.assertEqual(self.played, broadcast)

        self.setOffset(0.0)
        for second in range(52, 60):
            self.check(at(7, 59, second), broadcast)
        self.check(at(8, 0, 0), broadcast)
        self.check(at(8, 0, 1), broadcast)
        self.assertEqual(self.played, broadcast)

    def testKindsOnEitherSideOfMidnightRunOnce(self):
        cfg.set(cfg.timeOffsetExemptions, ["shutdown"], save=False)
        broadcast, shutdown = [task("00:00:00", "bell")], [task("00:00:00", "off")]

        self.check(at(23, 59, 59, day=22), broadcast, shutdown)
        for second in range(0, 6):
            self.check(at(0, 0, second, 500_000), broadcast, shutdown)

        self.assertEqual((self.played, self.shutdowns), (broadcast, shutdown))

    def testNextCheckLandsJustAfterTheNearestWholeSecond(self):
        self.setOffset(-3.2)

        # Bell Time 07:59:56.900，0.1 秒后到整秒；Calibrated Time 还要 0.9 秒。
        delay = self.window._nextScheduleDelay(at(8, 0, 0, 100_000))

        self.assertGreaterEqual(delay, 100)
        self.assertLessEqual(delay, 105)

    def testWithoutOffsetTheNextCheckFollowsCalibratedSeconds(self):
        cfg.set(cfg.timeOffsetEnabled, False, save=False)

        delay = self.window._nextScheduleDelay(at(8, 0, 0, 250_000))

        self.assertGreaterEqual(delay, 750)
        self.assertLessEqual(delay, 755)
