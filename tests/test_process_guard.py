import tempfile
import threading
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import call, patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from app.common import install_location, process_guard
from app.common.home_card_tasks import PROCESS_GUARD_TRIGGER
from app.common.process_guard import (
    MISSING_PROGRAM,
    NEEDS_ELEVATION,
    REPEATED_EXIT,
    ProcessGuard,
    launchProgram,
)
from app.config.cfg import cfg
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg

CLASSROOM_APP = "C:\\Class\\ClassApp.exe"


def guardTask(taskId="guard-one", target=CLASSROOM_APP, enabled=True):
    return {
        "id": taskId,
        "name": "守护课堂程序",
        "trigger": PROCESS_GUARD_TRIGGER,
        "program": {"target": target, "arguments": "", "working_dir": ""},
        "enabled": enabled,
    }


class FakeComputer:
    """被守护程序所在的电脑：哪些程序在运行、拉起了什么、现在几点。"""

    def __init__(self):
        self.now = 0.0
        self.running = set()
        self.launched = []
        self.keepsRunning = True
        self.launchErrors = {}
        self.listingFails = False

    def runningPrograms(self):
        if self.listingFails:
            return None
        return [Path(target).resolve() for target in self.running]

    def launch(self, program):
        target = program["target"]
        self.launched.append(target)
        error = self.launchErrors.get(target)
        if error is None and self.keepsRunning:
            self.running.add(target)
        return error

    def clock(self):
        return self.now


class ProcessGuardTest(TestCase):
    def setUp(self):
        self.computer = FakeComputer()
        self.guard = ProcessGuard(
            runningPrograms=self.computer.runningPrograms,
            launch=self.computer.launch,
            clock=self.computer.clock,
        )
        self.addCleanup(self.guard.deleteLater)
        self.stops = []
        self.guard.stopped.connect(lambda taskId, reason: self.stops.append((taskId, reason)))

    def check(self, times=1):
        for _ in range(times):
            self.guard.tick()
            self.computer.now += 3

    def testLaunchesOnlyAfterTwoChecksInARowWithoutTheProgram(self):
        self.guard.setRules([guardTask()], True)

        self.check()
        self.assertEqual(self.computer.launched, [])
        self.check()
        self.assertEqual(self.computer.launched, [CLASSROOM_APP])

    def testOneMissedCheckDuringASelfRestartIsNotALaunch(self):
        self.computer.running.add(CLASSROOM_APP)
        self.guard.setRules([guardTask()], True)

        self.check()
        self.computer.running.clear()
        self.check()
        self.computer.running.add(CLASSROOM_APP)
        self.check()
        self.computer.running.clear()
        self.check()

        self.assertEqual(self.computer.launched, [])

    def testSameNameProgramInAnotherFolderDoesNotCountAsRunning(self):
        self.computer.running.add("D:\\Copy\\ClassApp.exe")
        self.guard.setRules([guardTask()], True)

        self.check(2)

        self.assertEqual(self.computer.launched, [CLASSROOM_APP])

    def testStartupHoldOnlyWatchesUntilItEnds(self):
        self.guard.setRules([guardTask()], True)
        self.guard.holdLaunches(60)

        self.check(20)
        self.assertEqual(self.computer.launched, [])
        self.check()
        self.assertEqual(self.computer.launched, [CLASSROOM_APP])

    def testProgramThatStartsByItselfDuringTheHoldIsNeverLaunched(self):
        self.guard.setRules([guardTask()], True)
        self.guard.holdLaunches(60)

        self.check(10)
        self.computer.running.add(CLASSROOM_APP)
        self.check(20)

        self.assertEqual(self.computer.launched, [])

    def testGivesUpAfterSixLaunchesInARowThatDieWithinThirtySeconds(self):
        self.computer.keepsRunning = False
        self.guard.setRules([guardTask()], True)

        self.check(14)
        self.assertEqual(self.stops, [("guard-one", REPEATED_EXIT)])
        self.assertEqual(len(self.computer.launched), 6)
        self.assertEqual(self.guard.stoppedReasons(), {"guard-one": REPEATED_EXIT})

        self.check(10)
        self.assertEqual(len(self.computer.launched), 6)
        self.assertEqual(len(self.stops), 1)

    def testLaunchThatLastsThirtySecondsStartsTheCountAgain(self):
        self.guard.setRules([guardTask()], True)

        for _ in range(8):
            self.check(2)
            self.check(11)
            self.computer.running.clear()

        self.assertEqual(len(self.computer.launched), 8)
        self.assertEqual(self.stops, [])

    def testFailedLaunchStopsGuardingInsteadOfRetrying(self):
        for reason in (MISSING_PROGRAM, NEEDS_ELEVATION, "拒绝访问。"):
            with self.subTest(reason=reason):
                self.computer.launched.clear()
                self.stops.clear()
                self.computer.launchErrors = {CLASSROOM_APP: reason}
                self.guard.setRules([guardTask(taskId=reason)], True)

                self.check(10)

                self.assertEqual(self.computer.launched, [CLASSROOM_APP])
                self.assertEqual(self.stops, [(reason, reason)])
                self.assertEqual(self.guard.stoppedReasons(), {reason: reason})

    def testOnlyEnabledGuardRulesUnderAnEnabledMasterSwitchAreGuarded(self):
        scheduled = {**guardTask(taskId="scheduled"), "trigger": "time"}
        for tasks, enabled in (
            ([guardTask(enabled=False)], True),
            ([guardTask()], False),
            ([scheduled], True),
            ([guardTask(target="")], True),
        ):
            with self.subTest(tasks=tasks, enabled=enabled):
                self.guard.setRules(tasks, enabled)
                self.check(4)
                self.assertEqual(self.computer.launched, [])

    def testUnchangedRuleStaysStoppedButTurningItOffAndOnGuardsAgain(self):
        self.computer.launchErrors = {CLASSROOM_APP: MISSING_PROGRAM}
        self.guard.setRules([guardTask()], True)
        self.check(2)
        renamed = {**guardTask(), "name": "改了名字"}

        self.guard.setRules([renamed], True)
        self.assertEqual(self.guard.stoppedReasons(), {"guard-one": MISSING_PROGRAM})

        self.guard.setRules([guardTask(enabled=False)], True)
        self.assertEqual(self.guard.stoppedReasons(), {"guard-one": MISSING_PROGRAM})
        self.guard.setRules([guardTask()], True)
        self.assertEqual(self.guard.stoppedReasons(), {})
        self.computer.launchErrors = {}
        self.check(2)
        self.assertEqual(self.computer.launched, [CLASSROOM_APP, CLASSROOM_APP])

    def testMasterSwitchOffAndOnAlsoGuardsAgain(self):
        self.computer.launchErrors = {CLASSROOM_APP: MISSING_PROGRAM}
        self.guard.setRules([guardTask()], True)
        self.check(2)

        self.guard.setRules([guardTask()], False)
        self.assertEqual(self.guard.stoppedReasons(), {"guard-one": MISSING_PROGRAM})
        self.guard.setRules([guardTask()], True)

        self.assertEqual(self.guard.stoppedReasons(), {})

    def testDeletedRuleLeavesNoStopBehind(self):
        self.computer.launchErrors = {CLASSROOM_APP: MISSING_PROGRAM}
        self.guard.setRules([guardTask()], True)
        self.check(2)

        self.guard.setRules([], True)

        self.assertEqual(self.guard.stoppedReasons(), {})

    def testChoosingAnotherProgramIsANewRule(self):
        self.computer.launchErrors = {CLASSROOM_APP: MISSING_PROGRAM}
        self.guard.setRules([guardTask()], True)
        self.check(2)

        self.guard.setRules([guardTask(target="C:\\Class\\Other.exe")], True)
        self.check(2)

        self.assertEqual(self.guard.stoppedReasons(), {})
        self.assertEqual(
            self.computer.launched, [CLASSROOM_APP, "C:\\Class\\Other.exe"]
        )

    def testSecondRuleForTheSameProgramIsIgnored(self):
        self.guard.setRules(
            [guardTask(), guardTask(taskId="guard-two")], True
        )

        self.check(2)

        self.assertEqual(self.computer.launched, [CLASSROOM_APP])

    def testProgramsInsideTheInstallLocationWaitForAnApplicationRelocation(self):
        isolateCfg(self)
        cfg.set(cfg.appInstallLocation, "/apps", save=False)
        installed = "/apps/Tool/tool.exe"
        outside = "/school/other.exe"
        self.guard.setRules(
            [guardTask(target=installed), guardTask(taskId="outside", target=outside)],
            True,
        )
        install_location.setRelocationState(install_location.RELOCATING)
        self.addCleanup(install_location.setRelocationState, install_location.IDLE)

        self.check(4)
        self.assertEqual(self.computer.launched, [outside])

        install_location.setRelocationState(install_location.CLEANING)
        self.check()
        self.assertEqual(self.computer.launched, [outside, installed])

    def testRoundWhoseProcessListFailsIsSkipped(self):
        self.computer.running.add(CLASSROOM_APP)
        self.guard.setRules([guardTask()], True)
        self.computer.listingFails = True

        self.check(4)
        self.computer.listingFails = False
        self.check()

        self.assertEqual(self.computer.launched, [])

    def testShutdownWaitsForALaunchAlreadyUnderWay(self):
        launching = threading.Event()
        release = threading.Event()

        def slowLaunch(program):
            launching.set()
            release.wait(5)
            return self.computer.launch(program)

        guard = ProcessGuard(
            runningPrograms=self.computer.runningPrograms,
            launch=slowLaunch,
            clock=self.computer.clock,
        )
        self.addCleanup(guard.deleteLater)
        guard.setRules([guardTask()], True)
        guard.tick()
        checking = threading.Thread(target=guard.tick)
        checking.start()
        self.assertTrue(launching.wait(5))
        stopping = threading.Thread(target=guard.shutdown)
        stopping.start()

        stopping.join(0.2)
        self.assertTrue(stopping.is_alive())
        release.set()
        stopping.join(5)
        checking.join(5)
        self.assertFalse(stopping.is_alive())

    def testShutdownEndsGuardingForGood(self):
        self.guard.setRules([guardTask()], True)
        self.check()

        self.guard.shutdown()
        self.check(4)
        self.guard.setRules([guardTask(taskId="later")], True)
        self.check(4)

        self.assertEqual(self.computer.launched, [])

    def testStartChecksInTheBackgroundUntilShutdown(self):
        self.guard.setRules([guardTask()], True)
        with patch.object(process_guard, "CHECK_INTERVAL", 0.01):
            self.guard.start()
            deadline = time.monotonic() + 5
            while not self.computer.launched and time.monotonic() < deadline:
                time.sleep(0.01)
            self.guard.shutdown()
            self.computer.running.clear()
            time.sleep(0.1)

        self.assertEqual(self.computer.launched, [CLASSROOM_APP])


class LaunchProgramTest(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.program = self.directory / "ClassApp.exe"
        self.program.write_bytes(b"MZ")

    def launch(self, **program):
        return launchProgram(
            {
                "target": str(self.program),
                "arguments": "",
                "working_dir": "",
                **program,
            }
        )

    def testStartsTheProgramWithItsArgumentsAndWorkingDirectory(self):
        with patch.object(process_guard.subprocess, "Popen") as popen:
            error = self.launch(
                arguments='--tray "two words"', working_dir=str(self.directory)
            )

        self.assertIsNone(error)
        self.assertEqual(
            popen.call_args.args[0], [str(self.program), "--tray", "two words"]
        )
        self.assertEqual(popen.call_args.kwargs["cwd"], str(self.directory))

    def testMissingFileIsReportedWithoutTryingToStartIt(self):
        with patch.object(process_guard.subprocess, "Popen") as popen:
            error = self.launch(target=str(self.directory / "gone.exe"))

        self.assertEqual(error, MISSING_PROGRAM)
        popen.assert_not_called()

    def testProgramThatRequiresElevationIsReportedAsSuch(self):
        refused = OSError("请求的操作需要提升。")
        refused.winerror = 740
        with patch.object(process_guard.subprocess, "Popen", side_effect=refused):
            self.assertEqual(self.launch(), NEEDS_ELEVATION)

    def testOtherFailuresKeepWindowsMessage(self):
        with patch.object(
            process_guard.subprocess,
            "Popen",
            side_effect=OSError("不是有效的 Win32 应用程序。"),
        ):
            self.assertEqual(self.launch(), "不是有效的 Win32 应用程序。")


class ProcessGuardMainWindowTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.homeCardTasks, [guardTask()])
        cfg.set(cfg.homeCardTasksEnabled, True)
        quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        quotaPatcher.start()
        self.addCleanup(quotaPatcher.stop)

    def createWindow(self, isSilent=False):
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
            patch("app.view.windows.main_window.ProcessGuard") as guardClass,
        ):
            guardClass.return_value.stoppedReasons.return_value = {}
            window = MainWindow(isSilent=isSilent)
        self.addCleanup(self.closeWindow, window)
        return window, guardClass.return_value

    def closeWindow(self, window):
        window.tray = None
        window._shutdownResources()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def testGuardingStartsWithTheWindowAndHoldsLaunchesOnlyAfterSilentStartup(self):
        for isSilent in (False, True):
            with self.subTest(isSilent=isSilent):
                _window, guard = self.createWindow(isSilent)

                guard.setRules.assert_called_with(cfg.homeCardTasks.value, True)
                guard.start.assert_called_once_with()
                if isSilent:
                    self.assertEqual(
                        guard.mock_calls.index(call.holdLaunches(60)),
                        guard.mock_calls.index(call.start()) - 1,
                    )
                else:
                    guard.holdLaunches.assert_not_called()

    def testRulesFollowTheTaskListAndMasterSwitch(self):
        window, guard = self.createWindow()
        guard.stoppedReasons.return_value = {"guard-two": MISSING_PROGRAM}
        page = window._getHomeCardTaskPage()

        cfg.set(cfg.homeCardTasksEnabled, False)
        guard.setRules.assert_called_with(cfg.homeCardTasks.value, False)
        other = guardTask(taskId="guard-two", target="C:\\Class\\Other.exe")
        cfg.set(cfg.homeCardTasks, [other])
        guard.setRules.assert_called_with(cfg.homeCardTasks.value, False)
        self.assertEqual(cfg.homeCardTasks.value[0]["id"], "guard-two")

        self.assertIn(f"已停止：{MISSING_PROGRAM}", page._cards[0]._summary())

    def testTrayQuitStopsGuardingBeforeQuitTasksRun(self):
        window, guard = self.createWindow()
        stoppedFirst = []
        with (
            patch.object(
                window,
                "_runApplicationHomeCardTasks",
                side_effect=lambda event: stoppedFirst.append(guard.shutdown.called),
            ),
            patch("app.view.windows.main_window.QApplication.quit"),
        ):
            window.requestQuit()

        self.assertEqual(stoppedFirst, [True])

    def testWindowsSessionEndStopsGuarding(self):
        window, guard = self.createWindow()

        window._onSessionEnding(None)

        guard.shutdown.assert_called_once_with()

    def testShutdownTaskStopsGuardingBeforeShuttingDown(self):
        window, guard = self.createWindow()
        stoppedFirst = []
        with patch(
            "app.view.windows.main_window.QProcess.startDetached",
            side_effect=lambda *args: stoppedFirst.append(guard.shutdown.called),
        ):
            window._handleShutdownTask({"notify": False})

        self.assertEqual(stoppedFirst, [True])

    def testStoppedRuleIsReportedOnceWithTheReason(self):
        window, guard = self.createWindow()
        page = window._getHomeCardTaskPage()
        guard.stoppedReasons.return_value = {"guard-one": REPEATED_EXIT}
        reportStop = guard.stopped.connect.call_args.args[0]

        with patch.object(window, "_showHomeCardTaskError") as showError:
            reportStop("guard-one", REPEATED_EXIT)

        task, message = showError.call_args.args
        self.assertEqual(task["id"], "guard-one")
        self.assertIn("反复退出", message)
        self.assertIn("启动器", message)
        self.assertIn(f"已停止：{REPEATED_EXIT}", page._cards[0]._summary())

    def testEachStopReasonGetsItsOwnExplanation(self):
        window, _guard = self.createWindow()
        messages = {}
        with patch.object(window, "_showHomeCardTaskError") as showError:
            for reason in (MISSING_PROGRAM, NEEDS_ELEVATION, "[WinError 193] 不是有效的 Win32 应用程序。"):
                window._onProcessGuardStopped("guard-one", reason)
                messages[reason] = showError.call_args.args[1]

        self.assertIn("文件不存在", messages[MISSING_PROGRAM])
        self.assertIn("管理员权限", messages[NEEDS_ELEVATION])
        self.assertIn("WinError 193", messages["[WinError 193] 不是有效的 Win32 应用程序。"])
