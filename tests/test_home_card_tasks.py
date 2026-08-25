import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.common.home_card_tasks import (
    APPLICATION_HOME_CARD_TRIGGER,
    APPLICATION_QUIT_EVENT,
    APPLICATION_STARTUP_EVENT,
    CLOSE_HOME_CARD_ACTION,
    CUSTOM_HOME_CARD_TASK,
    EXISTING_HOME_CARD_TASK,
    HOME_CARD_TASK_KEY,
    OPEN_HOME_CARD_ACTION,
    SCHEDULED_HOME_CARD_TRIGGER,
    SILENT_STARTUP_EVENT,
    normalize_home_card_tasks,
)
from app.config.cfg import HOME_CARD_SCHEMA_VERSION, cfg, migrateConfig
from app.view.components.task_picker import TouchTimePicker
from app.view.pages.home_card_task_page import (
    HomeCardTaskPage,
    create_home_card_task_form,
    home_card_task_data,
)
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow


def home_cards():
    return [
        {
            "key": "全屏投送",
            "source": "default",
            "title": "全屏投送",
        },
        {
            "key": "custom:one",
            "source": "custom",
            "title": "课程表",
        },
        {
            "key": "app:7:0",
            "source": "application",
            "title": "课堂应用",
        },
        {
            "key": HOME_CARD_TASK_KEY,
            "source": "default",
            "title": "自动任务",
        },
    ]


def existing_task():
    return {
        "id": "existing-one",
        "name": "打开投送",
        "time": "08:00:00",
        "weeks": [0],
        "mode": EXISTING_HOME_CARD_TASK,
        "targetKey": "全屏投送",
        "targetTitle": "全屏投送",
        "actions": [],
        "enabled": True,
    }


def custom_task():
    return {
        "id": "custom-one",
        "name": "打开网页",
        "time": "08:00:00",
        "weeks": [0],
        "mode": CUSTOM_HOME_CARD_TASK,
        "targetKey": "",
        "targetTitle": "",
        "actions": [
            {
                "id": "action-one",
                "type": "url",
                "target": "https://example.test",
            }
        ],
        "enabled": True,
    }


class HomeCardTaskDataTest(TestCase):
    def testNormalizationRepairsIdsAndKeepsBothModeBranches(self):
        first = custom_task()
        second = custom_task()
        first.update(
            {
                "targetKey": "custom:one",
                "targetTitle": "课程表",
                "weeks": [6, 0, 6, 9, "2"],
                "actions": [first["actions"][0], first["actions"][0]],
            }
        )

        tasks = normalize_home_card_tasks([first, second, None])

        self.assertEqual(len(tasks), 2)
        self.assertNotEqual(tasks[0]["id"], tasks[1]["id"])
        self.assertEqual(tasks[0]["weeks"], [6, 0, 2])
        self.assertEqual(tasks[0]["targetKey"], "custom:one")
        self.assertEqual(len(tasks[0]["actions"]), 2)
        self.assertNotEqual(
            tasks[0]["actions"][0]["id"],
            tasks[0]["actions"][1]["id"],
        )

    def testMalformedValuesBecomeSafeEditableTasks(self):
        tasks = normalize_home_card_tasks(
            [
                {
                    "name": "",
                    "time": "99:99:99",
                    "weeks": "all",
                    "mode": "unknown",
                    "actions": None,
                    "enabled": "false",
                }
            ]
        )

        self.assertEqual(tasks[0]["name"], "未命名任务")
        self.assertEqual(tasks[0]["time"], "00:00:00")
        self.assertEqual(tasks[0]["weeks"], [])
        self.assertEqual(tasks[0]["mode"], EXISTING_HOME_CARD_TASK)
        self.assertEqual(tasks[0]["trigger"], SCHEDULED_HOME_CARD_TRIGGER)
        self.assertEqual(tasks[0]["event"], APPLICATION_STARTUP_EVENT)
        self.assertEqual(tasks[0]["operation"], OPEN_HOME_CARD_ACTION)
        self.assertEqual(tasks[0]["actions"], [])
        self.assertFalse(tasks[0]["enabled"])

    def testApplicationTriggersAndCloseActionsArePreserved(self):
        task = existing_task()
        task.update(
            {
                "trigger": APPLICATION_HOME_CARD_TRIGGER,
                "event": SILENT_STARTUP_EVENT,
                "operation": CLOSE_HOME_CARD_ACTION,
            }
        )

        normalized = normalize_home_card_tasks([task])[0]

        self.assertEqual(normalized["trigger"], APPLICATION_HOME_CARD_TRIGGER)
        self.assertEqual(normalized["event"], SILENT_STARTUP_EVENT)
        self.assertEqual(normalized["operation"], CLOSE_HOME_CARD_ACTION)


class HomeCardTaskUiTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.tasks = cfg.homeCardTasks.value
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(cfg.homeCardTasks, [])

    def tearDown(self):
        cfg.set(cfg.homeCardTasks, self.tasks)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testFormUsesTouchPickerAndExcludesItselfFromExistingCards(self):
        form, widgets = create_home_card_task_form(None, home_cards())
        self.addCleanup(form.deleteLater)

        self.assertIsInstance(widgets["timePicker"], TouchTimePicker)
        self.assertEqual(
            set(widgets["homeCards"]),
            {"全屏投送", "custom:one", "app:7:0"},
        )
        self.assertNotIn(HOME_CARD_TASK_KEY, widgets["homeCards"])
        self.assertEqual(widgets["homeCardCombo"].currentText(), "全屏投送")
        self.assertFalse(widgets["operationCard"].isHidden())
        self.assertEqual(home_card_task_data(widgets)["actions"], [])
        widgets["modeCombo"].setCurrentIndex(
            widgets["modeCombo"].findData(CUSTOM_HOME_CARD_TASK)
        )
        self.assertEqual(home_card_task_data(widgets)["actions"], [])

    def testApplicationTriggerReplacesTimeAndWeekControls(self):
        form, widgets = create_home_card_task_form(None, home_cards())
        self.addCleanup(form.deleteLater)

        widgets["triggerCombo"].setCurrentIndex(
            widgets["triggerCombo"].findData(APPLICATION_HOME_CARD_TRIGGER)
        )
        widgets["eventCombo"].setCurrentIndex(
            widgets["eventCombo"].findData(APPLICATION_QUIT_EVENT)
        )

        self.assertTrue(widgets["timeCard"].isHidden())
        self.assertTrue(widgets["weekCard"].isHidden())
        self.assertFalse(widgets["eventCard"].isHidden())
        self.assertEqual(widgets["eventCombo"].currentText(), "电教猫关闭时")
        data = home_card_task_data(widgets)
        self.assertEqual(data["trigger"], APPLICATION_HOME_CARD_TRIGGER)
        self.assertEqual(data["event"], APPLICATION_QUIT_EVENT)

    def testCloseActionIsOnlyAvailableForDefaultHomeCards(self):
        form, widgets = create_home_card_task_form(None, home_cards())
        self.addCleanup(form.deleteLater)
        widgets["operationCombo"].setCurrentIndex(
            widgets["operationCombo"].findData(CLOSE_HOME_CARD_ACTION)
        )

        self.assertEqual(home_card_task_data(widgets)["operation"], CLOSE_HOME_CARD_ACTION)
        widgets["homeCardCombo"].setCurrentIndex(
            widgets["homeCardCombo"].findData("custom:one")
        )
        self.assertTrue(widgets["operationCard"].isHidden())
        self.assertEqual(home_card_task_data(widgets)["operation"], OPEN_HOME_CARD_ACTION)

    def testSwitchingModesKeepsExistingTargetAndCustomActions(self):
        data = custom_task()
        data.update({"targetKey": "custom:one", "targetTitle": "课程表"})
        form, widgets = create_home_card_task_form(None, home_cards(), data)
        self.addCleanup(form.deleteLater)

        widgets["modeCombo"].setCurrentIndex(
            widgets["modeCombo"].findData(EXISTING_HOME_CARD_TASK)
        )
        existing = home_card_task_data(widgets)
        widgets["modeCombo"].setCurrentIndex(
            widgets["modeCombo"].findData(CUSTOM_HOME_CARD_TASK)
        )
        custom = home_card_task_data(widgets)

        self.assertEqual(existing["targetKey"], "custom:one")
        self.assertEqual(custom["actions"], data["actions"])

    def testMissingTargetIsShownWithoutPointingAtAnotherCard(self):
        data = existing_task()
        data.update({"targetKey": "custom:missing", "targetTitle": "旧卡片"})
        form, widgets = create_home_card_task_form(None, home_cards(), data)
        self.addCleanup(form.deleteLater)

        self.assertEqual(widgets["homeCardCombo"].currentData(), "custom:missing")
        self.assertIn("已失效", widgets["homeCardCombo"].currentText())

    def testCardRefreshOnlySavesWhenReferencedTitleChanges(self):
        cfg.set(cfg.homeCardTasks, [existing_task()])
        page = HomeCardTaskPage(home_cards())
        self.addCleanup(page.deleteLater)

        page.setHomeCards(home_cards())
        self.assertFalse(page._savePending)

        renamed = home_cards()
        renamed[0]["title"] = "投送新名称"
        page.setHomeCards(renamed)
        self.assertTrue(page._savePending)
        page.flushPendingSave()
        self.assertEqual(
            cfg.homeCardTasks.value[0]["targetTitle"],
            "投送新名称",
        )

    def testMissingTargetIsMarkedInvalidInTaskSummary(self):
        task = existing_task()
        task.update({"targetKey": "custom:missing", "targetTitle": "旧卡片"})
        cfg.set(cfg.homeCardTasks, [task])
        page = HomeCardTaskPage(home_cards())
        self.addCleanup(page.deleteLater)

        self.assertIn("旧卡片（已失效）", page._cards[0]._summary())

    def testPageDebouncesEditsAndFlushesLatestTask(self):
        cfg.set(cfg.homeCardTasks, [existing_task()])
        page = HomeCardTaskPage(home_cards())
        self.addCleanup(page.deleteLater)
        card = page._cards[0]

        card.formWidgets["nameInput"].setText("新的任务名")
        self.assertTrue(page._savePending)
        page.flushPendingSave()

        self.assertEqual(cfg.homeCardTasks.value[0]["name"], "新的任务名")
        self.assertFalse(page._savePending)


class HomeCardTaskRuntimeTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.tasks = cfg.homeCardTasks.value
        self.lastBroadcast = cfg.lastBroadcast.value
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(cfg.homeCardTasks, [])
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
        cfg.set(cfg.homeCardTasks, self.tasks)
        cfg.set(cfg.lastBroadcast, self.lastBroadcast)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testExistingCardTaskUsesStableHomeCardKey(self):
        with patch.object(self.window, "_executeHomeCard", return_value=True) as execute:
            self.window._handleHomeCardTask(existing_task())

        execute.assert_called_once_with("全屏投送", interactive=False)

    def testExistingCardTaskCannotTargetItsOwnManagementCard(self):
        task = existing_task()
        task["targetKey"] = HOME_CARD_TASK_KEY
        with (
            patch.object(self.window, "_executeHomeCard") as execute,
            patch.object(self.window, "_showHomeCardTaskError") as showError,
        ):
            self.window._handleHomeCardTask(task)

        execute.assert_not_called()
        showError.assert_called_once()

    def testScheduleRunsHomeCardTaskOnceAcrossSkippedSecond(self):
        task = existing_task()
        timezone = datetime.now().astimezone().tzinfo
        with patch.object(self.window, "_handleHomeCardTask") as execute:
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 7, 59, 59, tzinfo=timezone),
                [],
                [],
                [task],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 1, tzinfo=timezone),
                [],
                [],
                [task],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 2, tzinfo=timezone),
                [],
                [],
                [task],
            )

        execute.assert_called_once_with(task)

    def testApplicationTriggeredTaskIsIgnoredByTimeScheduler(self):
        task = existing_task()
        task.update(
            {
                "trigger": APPLICATION_HOME_CARD_TRIGGER,
                "event": APPLICATION_STARTUP_EVENT,
            }
        )
        timezone = datetime.now().astimezone().tzinfo
        with patch.object(self.window, "_handleHomeCardTask") as execute:
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 0, tzinfo=timezone),
                [],
                [],
                [task],
            )

        execute.assert_not_called()

    def testApplicationEventOnlyRunsMatchingEnabledTasks(self):
        startup = existing_task()
        startup.update(
            {
                "trigger": APPLICATION_HOME_CARD_TRIGGER,
                "event": APPLICATION_STARTUP_EVENT,
            }
        )
        silent = {**startup, "id": "silent", "event": SILENT_STARTUP_EVENT}
        disabled = {
            **startup,
            "id": "disabled",
            "enabled": False,
        }
        cfg.set(cfg.homeCardTasks, [startup, silent, disabled])

        with patch.object(self.window, "_handleHomeCardTask") as execute:
            self.window._runApplicationHomeCardTasks(APPLICATION_STARTUP_EVENT)

        self.assertEqual(execute.call_count, 1)
        self.assertEqual(execute.call_args.args[0]["id"], startup["id"])

    def testNormalAndSilentStartupDispatchExpectedApplicationEvents(self):
        for isSilent, expected in (
            (False, [APPLICATION_STARTUP_EVENT]),
            (True, [APPLICATION_STARTUP_EVENT, SILENT_STARTUP_EVENT]),
        ):
            with (
                self.subTest(isSilent=isSilent),
                patch.object(MainWindow, "_startMachineRegistration"),
                patch.object(MainWindow, "checkForUpdates"),
                patch.object(MainWindow, "_runApplicationHomeCardTasks") as runTasks,
                patch("app.view.windows.main_window.SystemTrayIcon"),
            ):
                window = MainWindow(isSilent=isSilent)
                try:
                    self.assertEqual(
                        [call.args[0] for call in runTasks.call_args_list],
                        expected,
                    )
                finally:
                    window.tray = None
                    window._shutdownResources()
                    window.deleteLater()

    def testCloseTaskSkipsUnopenedFeatureWithoutLoadingItsPage(self):
        task = existing_task()
        task["operation"] = CLOSE_HOME_CARD_ACTION
        with (
            patch.object(self.window, "_executeHomeCard") as execute,
            patch.object(self.window, "_showHomeCardTaskError") as showError,
        ):
            self.window._handleHomeCardTask(task)

        self.assertIsNone(self.window.broadcastEditPage)
        execute.assert_not_called()
        showError.assert_not_called()

    def testCloseTaskClosesActiveCountdownWithoutConfirmation(self):
        page = self.window._getCountdownPage()
        page.countdownWin.show()
        task = existing_task()
        task.update(
            {
                "targetKey": "考试倒计时",
                "targetTitle": "考试倒计时",
                "operation": CLOSE_HOME_CARD_ACTION,
            }
        )

        self.window._handleHomeCardTask(task)

        self.assertFalse(page.countdownWin.isVisible())

    def testCloseTaskAlsoClosesMinimizedProjection(self):
        page = self.window._getBroadcastEditPage()
        page.titleInput.setText("正在投送")
        page.contentInput.setPlainText("正文")
        page._onBroadcast()
        page.broadcastWin.minimizeToMini()
        task = existing_task()
        task["operation"] = CLOSE_HOME_CARD_ACTION

        self.window._handleHomeCardTask(task)

        self.assertFalse(page.broadcastWin.isVisible())
        self.assertFalse(page.broadcastWin.miniWindow.isVisible())
        self.assertFalse(cfg.lastBroadcast.value["active"])

    def testTrayQuitRunsCloseTaskBeforeShuttingDownResources(self):
        task = existing_task()
        task.update(
            {
                "trigger": APPLICATION_HOME_CARD_TRIGGER,
                "event": APPLICATION_QUIT_EVENT,
                "operation": CLOSE_HOME_CARD_ACTION,
            }
        )
        cfg.set(cfg.homeCardTasks, [task])
        with (
            patch.object(self.window, "_closeHomeCard") as closeCard,
            patch("app.view.windows.main_window.QApplication.quit"),
        ):
            self.window.requestQuit()

        closeCard.assert_called_once_with("全屏投送")
        self.assertTrue(self.window._resourcesShutdown)

    def testTrayQuitWaitsForCustomTaskWithoutBlockingTheUi(self):
        task = custom_task()
        task.update(
            {
                "trigger": APPLICATION_HOME_CARD_TRIGGER,
                "event": APPLICATION_QUIT_EVENT,
            }
        )
        cfg.set(cfg.homeCardTasks, [task])
        with (
            patch("app.common.home_cards.execute_action", return_value=None) as execute,
            patch("app.view.windows.main_window.QApplication.quit") as quitApp,
        ):
            self.window.requestQuit()
            self.assertFalse(self.window._resourcesShutdown)
            QTest.qWait(50)

        execute.assert_called_once()
        quitApp.assert_called_once_with()
        self.assertTrue(self.window._resourcesShutdown)

    def testCustomTaskReadsLatestActionsByStableId(self):
        task = custom_task()
        cfg.set(cfg.homeCardTasks, [task])

        self.assertEqual(
            self.window._getHomeCardTaskActions(task["id"]),
            task["actions"],
        )
        cfg.set(cfg.homeCardTasks, [])
        self.assertIsNone(self.window._getHomeCardTaskActions(task["id"]))

    def testRunningCustomTaskIsNotStartedTwice(self):
        task = custom_task()
        self.window._homeCardTaskWorkers[task["id"]] = object()
        with patch("app.view.windows.main_window.ActionSequenceWorker") as worker:
            self.window._handleHomeCardTask(task)

        worker.assert_not_called()
        self.window._homeCardTaskWorkers.clear()


class HomeCardTaskMigrationTest(TestCase):
    def testRenameKeepsOrderVisibilityAndTraySelection(self):
        items = (
            cfg.homeCardOrder,
            cfg.visibleDefaultHomeCards,
            cfg.trayHomeCardKeys,
            cfg.homeCardSchemaVersion,
        )
        values = [(item, item.value) for item in items]
        configFile = cfg.file
        with tempfile.TemporaryDirectory() as directory:
            try:
                cfg.file = Path(directory) / "config.json"
                cfg.set(
                    cfg.homeCardOrder,
                    ["全屏投送", "定时任务", "定时播报"],
                    save=False,
                )
                cfg.set(
                    cfg.visibleDefaultHomeCards,
                    ["全屏投送", "定时播报"],
                    save=False,
                )
                cfg.set(cfg.trayHomeCardKeys, ["定时任务"], save=False)
                cfg.set(cfg.homeCardSchemaVersion, 2, save=False)

                migrateConfig()

                self.assertEqual(
                    cfg.homeCardOrder.value,
                    ["全屏投送", "自动任务", "定时播报"],
                )
                self.assertEqual(
                    cfg.visibleDefaultHomeCards.value,
                    ["全屏投送", "定时播报"],
                )
                self.assertEqual(cfg.trayHomeCardKeys.value, ["自动任务"])
                self.assertEqual(
                    cfg.homeCardSchemaVersion.value,
                    HOME_CARD_SCHEMA_VERSION,
                )
            finally:
                for item, value in values:
                    cfg.set(item, value, save=False)
                cfg.file = configFile
