from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.common.home_card_tasks import (
    CUSTOM_HOME_CARD_TASK,
    DEFAULT_INTERVAL_START,
    FIXED_WALLPAPER,
    INTERVAL_HOME_CARD_TRIGGER,
    ROTATION_WALLPAPER,
    SCHEDULED_HOME_CARD_TRIGGER,
    WALLPAPER_HOME_CARD_TASK,
    homeCardTaskState,
    normalizeHomeCardTasks,
    updateHomeCardTaskState,
)
from app.common.home_cards import executeAction, validateAction
from app.common.interval_tasks import dueIntervalTasks, latestDue, nextDue
from app.common.wallpaper import (
    WallpaperWorker,
    nextRotationWallpaper,
    scanWallpaperFolder,
)
from app.config.cfg import cfg
from app.view.components.home_card_dialog import ActionEditorDialog
from app.view.components.wallpaper_rotation import (
    WallpaperRotationDialog,
    rotationSuccessor,
    rotationSummary,
)
from app.view.pages.home_card_task_page import (
    AddHomeCardTaskDialog,
    HomeCardTaskCard,
    createHomeCardTaskForm,
    homeCardTaskData,
    intervalSummary,
    wallpaperSummary,
)
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg

TIMEZONE = datetime.now().astimezone().tzinfo


def at(*args):
    return datetime(*args, tzinfo=TIMEZONE)


def interval_task(**changes):
    task = {
        "id": "interval-one",
        "name": "每天换壁纸",
        "trigger": INTERVAL_HOME_CARD_TRIGGER,
        "mode": WALLPAPER_HOME_CARD_TASK,
        "interval": {"value": 1, "unit": "day"},
        "start": "2026-10-26 00:00:00",
        "wallpaper": {"mode": ROTATION_WALLPAPER, "fixed": "", "rotation": []},
        "enabled": True,
    }
    task.update(changes)
    return normalizeHomeCardTasks([task])[0]


def run_until_idle(worker):
    worker.wait(5)
    QTest.qWait(20)
    QApplication.processEvents()


class IntervalTaskSchemaTest(TestCase):
    def testMissingFieldsGetSafeDefaults(self):
        task = normalizeHomeCardTasks([{"id": "a"}])[0]

        self.assertEqual(task["interval"], {"value": 1, "unit": "day"})
        self.assertEqual(task["start"], DEFAULT_INTERVAL_START)
        self.assertEqual(
            task["wallpaper"],
            {"mode": FIXED_WALLPAPER, "fixed": "", "rotation": []},
        )

    def testMalformedIntervalAndWallpaperAreRepaired(self):
        task = normalizeHomeCardTasks(
            [
                {
                    "id": "a",
                    "trigger": "interval",
                    "mode": "wallpaper",
                    "interval": {"value": True, "unit": "week"},
                    "start": "yesterday",
                    "wallpaper": {
                        "mode": "shuffle",
                        "fixed": 3,
                        "rotation": [
                            r"C:\Pictures\a.jpg",
                            r"c:\pictures\A.JPG",
                            "",
                            None,
                            r"C:\Pictures\b.png",
                        ],
                    },
                },
                {"id": "b", "interval": {"value": 0, "unit": "hour"}},
            ]
        )

        self.assertEqual(task[0]["trigger"], INTERVAL_HOME_CARD_TRIGGER)
        self.assertEqual(task[0]["mode"], WALLPAPER_HOME_CARD_TASK)
        self.assertEqual(task[0]["interval"], {"value": 1, "unit": "day"})
        self.assertEqual(task[0]["start"], DEFAULT_INTERVAL_START)
        self.assertEqual(task[0]["wallpaper"]["mode"], FIXED_WALLPAPER)
        self.assertEqual(task[0]["wallpaper"]["fixed"], "")
        self.assertEqual(len(task[0]["wallpaper"]["rotation"]), 2)
        self.assertEqual(task[1]["interval"], {"value": 1, "unit": "hour"})


class IntervalDueTest(TestCase):
    def testDuePointsAreAnchoredToTheStartNotToTheLastRun(self):
        task = interval_task(
            interval={"value": 2, "unit": "hour"},
            start="2026-10-26 08:00:00",
        )

        self.assertEqual(
            latestDue(task, at(2026, 10, 26, 9, 0), at(2026, 10, 27, 9, 30)),
            at(2026, 10, 27, 8, 0),
        )
        self.assertIsNone(
            latestDue(task, at(2026, 10, 27, 8, 0), at(2026, 10, 27, 9, 30))
        )
        self.assertEqual(nextDue(task, at(2026, 10, 27, 9, 30)), at(2026, 10, 27, 10, 0))
        self.assertEqual(nextDue(task, at(2026, 10, 27, 10, 0)), at(2026, 10, 27, 12, 0))

    def testNothingIsDueBeforeTheStart(self):
        task = interval_task(start="2026-11-01 07:30:00")

        self.assertIsNone(latestDue(task, at(2026, 10, 1), at(2026, 10, 31, 23)))
        self.assertEqual(nextDue(task, at(2026, 10, 31, 23)), at(2026, 11, 1, 7, 30))


class IntervalCatchUpTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.homeCardTaskState, {})

    def due(self, tasks, now, master=True):
        return [task["id"] for task in dueIntervalTasks(tasks, master, now)]

    def testANewRuleStartsCountingFromNow(self):
        task = interval_task()

        self.assertEqual(self.due([task], at(2026, 10, 27, 10, 0)), [])
        self.assertEqual(self.due([task], at(2026, 10, 27, 23, 59, 59)), [])
        self.assertEqual(self.due([task], at(2026, 10, 28, 0, 0, 0)), ["interval-one"])
        self.assertEqual(self.due([task], at(2026, 10, 28, 0, 0, 1)), [])

    def testManyMissedDuePointsRunOnlyOnce(self):
        task = interval_task(interval={"value": 1, "unit": "hour"})
        self.due([task], at(2026, 10, 23, 17, 30))

        # 周末两天没开机，周一开机。
        self.assertEqual(self.due([task], at(2026, 10, 26, 7, 55)), ["interval-one"])
        self.assertEqual(self.due([task], at(2026, 10, 26, 7, 56)), [])
        self.assertEqual(
            homeCardTaskState("interval-one")["lastDue"],
            at(2026, 10, 26, 7, 0).isoformat(),
        )
        self.assertEqual(self.due([task], at(2026, 10, 26, 8, 0)), ["interval-one"])

    def testMissedRunsSurviveARestartBecauseTheStateIsSaved(self):
        task = interval_task()
        self.due([task], at(2026, 10, 26, 12, 0))
        saved = cfg.homeCardTaskState.value

        cfg.set(cfg.homeCardTaskState, {})
        cfg.set(cfg.homeCardTaskState, saved)

        self.assertEqual(self.due([task], at(2026, 10, 27, 7, 55)), ["interval-one"])

    def testTimeWhileSwitchedOffIsNotCaughtUp(self):
        task = interval_task()
        self.due([task], at(2026, 10, 26, 12, 0))
        disabled = interval_task(enabled=False)

        self.assertEqual(self.due([disabled], at(2026, 10, 27, 12, 0)), [])
        self.assertEqual(self.due([task], at(2026, 10, 29, 12, 0)), [])
        self.assertEqual(self.due([task], at(2026, 10, 30, 0, 0)), ["interval-one"])

    def testMasterSwitchOffIsNotCaughtUpEither(self):
        task = interval_task()
        self.due([task], at(2026, 10, 26, 12, 0))

        self.assertEqual(self.due([task], at(2026, 10, 27, 12, 0), master=False), [])
        self.assertEqual(self.due([task], at(2026, 10, 28, 12, 0)), [])

    def testChangingTheIntervalDoesNotRunPointsBeforeTheChange(self):
        task = interval_task()
        self.due([task], at(2026, 10, 26, 12, 0))
        changed = interval_task(interval={"value": 1, "unit": "minute"})

        self.assertEqual(self.due([changed], at(2026, 10, 27, 12, 0)), [])
        self.assertEqual(self.due([changed], at(2026, 10, 27, 12, 1)), ["interval-one"])

    def testRenamingOrChangingTheWallpaperKeepsTheCount(self):
        task = interval_task()
        self.due([task], at(2026, 10, 26, 12, 0))
        edited = interval_task(
            name="换一个名字",
            wallpaper={"mode": FIXED_WALLPAPER, "fixed": r"C:\a.jpg", "rotation": []},
        )

        self.assertEqual(self.due([edited], at(2026, 10, 28, 7, 0)), ["interval-one"])

    def testTimeGoingBackDoesNotRepeatAnExecutedDuePoint(self):
        task = interval_task(interval={"value": 1, "unit": "hour"})
        self.due([task], at(2026, 10, 26, 7, 30))
        self.assertEqual(self.due([task], at(2026, 10, 26, 8, 0)), ["interval-one"])

        self.assertEqual(self.due([task], at(2026, 10, 26, 7, 40)), [])
        self.assertEqual(self.due([task], at(2026, 10, 26, 8, 0)), [])
        self.assertEqual(self.due([task], at(2026, 10, 26, 9, 0)), ["interval-one"])

    def testAClockThatWasDaysAheadStartsOverFromNow(self):
        task = interval_task()
        self.due([task], at(2030, 1, 1, 12, 0))
        self.assertEqual(self.due([task], at(2030, 1, 2, 0, 0)), ["interval-one"])

        self.assertEqual(self.due([task], at(2026, 10, 26, 12, 0)), [])
        self.assertEqual(self.due([task], at(2026, 10, 27, 0, 0)), ["interval-one"])

    def testOtherTriggersAreIgnoredAndDeletedTasksLoseTheirState(self):
        fixed = interval_task(id="fixed-time", trigger=SCHEDULED_HOME_CARD_TRIGGER)
        updateHomeCardTaskState("fixed-time", wallpaper=r"C:\a.jpg")
        updateHomeCardTaskState("deleted", wallpaper=r"C:\b.jpg")

        self.assertEqual(self.due([fixed], at(2026, 10, 30)), [])
        self.assertEqual(
            cfg.homeCardTaskState.value,
            {"fixed-time": {"wallpaper": r"C:\a.jpg"}},
        )


class WallpaperRotationTest(TestCase):
    def testRotationGoesToTheNextImageAndWrapsAround(self):
        rotation = ["a.jpg", "b.jpg", "c.jpg"]
        exists = lambda path: True

        self.assertEqual(nextRotationWallpaper(rotation, "", "", exists), "a.jpg")
        self.assertEqual(nextRotationWallpaper(rotation, "a.jpg", "", exists), "b.jpg")
        self.assertEqual(nextRotationWallpaper(rotation, "c.jpg", "", exists), "a.jpg")

    def testCurrentFollowsTheImageNotItsPosition(self):
        exists = lambda path: True

        self.assertEqual(
            nextRotationWallpaper(["c.jpg", "a.jpg", "b.jpg"], "a.jpg", "", exists),
            "b.jpg",
        )
        # 删掉了当前那张：从原来排在它后面的那张开始。
        self.assertEqual(
            nextRotationWallpaper(["a.jpg", "c.jpg"], "b.jpg", "c.jpg", exists),
            "c.jpg",
        )
        self.assertEqual(
            nextRotationWallpaper(["a.jpg", "c.jpg"], "b.jpg", "", exists),
            "a.jpg",
        )

    def testMissingImagesAreSkippedButNotRemoved(self):
        exists = lambda path: path != "b.jpg"

        self.assertEqual(
            nextRotationWallpaper(["a.jpg", "b.jpg", "c.jpg"], "a.jpg", "", exists),
            "c.jpg",
        )
        self.assertIsNone(
            nextRotationWallpaper(["a.jpg", "b.jpg"], "", "", lambda path: False)
        )

    def testSuccessorIsTheNextRemainingImageAfterTheDeletedCurrentOne(self):
        previous = ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]

        self.assertEqual(rotationSuccessor(previous, "b.jpg", ["a.jpg", "d.jpg", "c.jpg"]), "c.jpg")
        self.assertEqual(rotationSuccessor(previous, "b.jpg", ["a.jpg", "d.jpg"]), "d.jpg")
        self.assertIsNone(rotationSuccessor(previous, "d.jpg", ["a.jpg"]))
        self.assertIsNone(rotationSuccessor(previous, "b.jpg", previous))

    def testFolderImportIsRecursiveNaturallySortedAndSkipsHiddenFolders(self):
        root = isolateCfg(self) / "pictures"
        for name in (
            "10.jpg",
            "2.JPG",
            "notes.txt",
            "sub/1.png",
            "sub/deeper/3.bmp",
            ".hidden/4.jpg",
            ".5.jpg",
        ):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

        found = scanWallpaperFolder(str(root))

        self.assertEqual(
            [Path(path).relative_to(root).as_posix() for path in found],
            ["2.JPG", "10.jpg", "sub/1.png", "sub/deeper/3.bmp"],
        )


class WallpaperWorkerTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.directory = isolateCfg(self)
        self.images = []
        for name in ("a.jpg", "b.jpg"):
            path = self.directory / name
            path.write_bytes(b"x")
            self.images.append(str(path))

    def run_worker(self, task, state, setter_result=None):
        applied = []
        finished = []
        worker = WallpaperWorker(task, state)
        worker.applied.connect(lambda taskId, path: applied.append(path))
        worker.finished.connect(lambda taskId, errors: finished.append(errors))
        with patch(
            "app.common.wallpaper.setDesktopWallpaper",
            return_value=setter_result,
        ) as setter:
            worker.start()
            run_until_idle(worker)
        return setter, applied, finished

    def testRotationSetsTheNextImageAndReportsIt(self):
        task = interval_task(
            wallpaper={"mode": ROTATION_WALLPAPER, "fixed": "", "rotation": self.images}
        )

        setter, applied, finished = self.run_worker(task, {"wallpaper": self.images[0]})

        setter.assert_called_once_with(self.images[1])
        self.assertEqual(applied, [self.images[1]])
        self.assertEqual(finished, [[]])

    def testFailedSetDoesNotMoveTheCurrentWallpaper(self):
        task = interval_task(
            wallpaper={"mode": ROTATION_WALLPAPER, "fixed": "", "rotation": self.images}
        )

        _setter, applied, finished = self.run_worker(task, {}, "Windows 没能换上壁纸")

        self.assertEqual(applied, [])
        self.assertEqual(finished, [["Windows 没能换上壁纸"]])

    def testFixedWallpaperThatIsGoneIsAnError(self):
        task = interval_task(
            wallpaper={
                "mode": FIXED_WALLPAPER,
                "fixed": str(self.directory / "gone.jpg"),
                "rotation": self.images,
            }
        )

        setter, applied, finished = self.run_worker(task, {})

        setter.assert_not_called()
        self.assertEqual(applied, [])
        self.assertIn("找不到壁纸图片", finished[0][0])

    def testRotationWithNoImageLeftIsAnError(self):
        task = interval_task(
            wallpaper={
                "mode": ROTATION_WALLPAPER,
                "fixed": "",
                "rotation": [str(self.directory / "gone.jpg")],
            }
        )

        setter, _applied, finished = self.run_worker(task, {})

        setter.assert_not_called()
        self.assertEqual(finished, [["轮换列表里的图片都找不到了"]])


class WallpaperHomeActionTest(TestCase):
    def testWallpaperActionNeedsASupportedImage(self):
        self.assertEqual(
            validateAction({"type": "wallpaper", "target": ""}),
            "请选择壁纸图片",
        )
        self.assertEqual(
            validateAction({"type": "wallpaper", "target": r"C:\a.gif"}),
            "壁纸只支持 JPG、PNG 或 BMP 图片",
        )
        self.assertEqual(validateAction({"type": "wallpaper", "target": r"C:\a.png"}), "")

    def testWallpaperActionSetsTheImage(self):
        image = isolateCfg(self) / "a.png"
        image.write_bytes(b"x")
        with patch(
            "app.common.home_cards.setDesktopWallpaper", return_value=None
        ) as setter:
            error = executeAction({"type": "wallpaper", "target": str(image)}, None)

        self.assertIsNone(error)
        setter.assert_called_once_with(str(image))

    def testActionEditorKeepsTheWallpaperImage(self):
        host = QWidget()
        dialog = ActionEditorDialog(
            {"id": "w", "type": "wallpaper", "target": r"C:\壁纸\海边.jpg"},
            host,
        )

        self.assertEqual(
            dialog.getData(),
            {"id": "w", "type": "wallpaper", "target": r"C:\壁纸\海边.jpg"},
        )
        dialog.deleteLater()
        host.deleteLater()

    def testMissingWallpaperImageFailsTheStep(self):
        with patch("app.common.home_cards.setDesktopWallpaper") as setter:
            error = executeAction({"type": "wallpaper", "target": r"Z:\none.png"}, None)

        setter.assert_not_called()
        self.assertIn("找不到壁纸图片", error)


class IntervalWallpaperFormTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.homeCardTasks, [])
        cfg.set(cfg.homeCardTaskState, {})
        self.host = QWidget()

    def tearDown(self):
        self.host.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def testIntervalTriggerShowsIntervalAndStartInsteadOfTimeAndWeeks(self):
        _form, widgets = createHomeCardTaskForm(self.host, [])
        combo = widgets["triggerCombo"]
        combo.setCurrentIndex(combo.findData(INTERVAL_HOME_CARD_TRIGGER))

        for name in ("intervalCard", "startDateCard", "startTimeCard"):
            self.assertTrue(widgets[name].isVisibleTo(self.host), name)
        for name in ("timeCard", "weekCard"):
            self.assertFalse(widgets[name].isVisibleTo(self.host), name)
        data = homeCardTaskData(widgets)
        self.assertEqual(data["interval"], {"value": 1, "unit": "day"})
        self.assertTrue(data["start"].endswith(" 00:00:00"))

    def testWallpaperModeSwitchesBetweenFixedImageAndRotationList(self):
        _form, widgets = createHomeCardTaskForm(self.host, [])
        mode = widgets["modeCombo"]
        mode.setCurrentIndex(mode.findData(WALLPAPER_HOME_CARD_TASK))

        self.assertTrue(widgets["fixedWallpaperCard"].isVisibleTo(self.host))
        self.assertFalse(widgets["rotationCard"].isVisibleTo(self.host))
        self.assertFalse(widgets["actionCard"].isVisibleTo(self.host))
        self.assertFalse(widgets["homeCardCard"].isVisibleTo(self.host))

        wallpaperMode = widgets["wallpaperModeCombo"]
        wallpaperMode.setCurrentIndex(wallpaperMode.findData(ROTATION_WALLPAPER))

        self.assertFalse(widgets["fixedWallpaperCard"].isVisibleTo(self.host))
        self.assertTrue(widgets["rotationCard"].isVisibleTo(self.host))

    def testFixedAndRotationAreKeptSeparately(self):
        task = interval_task(
            wallpaper={
                "mode": ROTATION_WALLPAPER,
                "fixed": r"C:\fixed.jpg",
                "rotation": [r"C:\a.jpg", r"C:\b.jpg"],
            }
        )
        _form, widgets = createHomeCardTaskForm(self.host, [], task)
        wallpaperMode = widgets["wallpaperModeCombo"]
        wallpaperMode.setCurrentIndex(wallpaperMode.findData(FIXED_WALLPAPER))

        self.assertEqual(
            homeCardTaskData(widgets)["wallpaper"],
            {
                "mode": FIXED_WALLPAPER,
                "fixed": r"C:\fixed.jpg",
                "rotation": [r"C:\a.jpg", r"C:\b.jpg"],
            },
        )

    def testNewWallpaperTaskNeedsAnImage(self):
        dialog = AddHomeCardTaskDialog([], self.host)
        widgets = dialog.formWidgets
        widgets["modeCombo"].setCurrentIndex(
            widgets["modeCombo"].findData(WALLPAPER_HOME_CARD_TASK)
        )
        widgets["wallpaperModeCombo"].setCurrentIndex(
            widgets["wallpaperModeCombo"].findData(ROTATION_WALLPAPER)
        )

        with patch("app.view.pages.home_card_task_page.InfoBar.error") as error:
            self.assertFalse(dialog.validate())

        self.assertIn("轮换列表", error.call_args.args[1])
        dialog.deleteLater()

    def testSummariesNameTheNextRunAndTheCurrentWallpaper(self):
        task = interval_task(
            interval={"value": 2, "unit": "hour"},
            start="2026-10-26 08:00:00",
            wallpaper={
                "mode": ROTATION_WALLPAPER,
                "fixed": "",
                "rotation": [r"C:\壁纸\山.jpg", r"C:\壁纸\海边.jpg"],
            },
        )

        self.assertEqual(
            intervalSummary(task, at(2026, 10, 27, 9, 30)),
            "每 2 小时 · 下次 今天 10:00",
        )
        self.assertEqual(
            intervalSummary(task, at(2026, 10, 27, 23, 0)),
            "每 2 小时 · 下次 明天 00:00",
        )
        self.assertEqual(wallpaperSummary(task, {}), "轮换 · 尚未执行")
        self.assertEqual(
            wallpaperSummary(task, {"wallpaper": r"C:\壁纸\海边.jpg"}),
            "轮换 2/2 · 海边.jpg",
        )
        self.assertEqual(
            rotationSummary(task["wallpaper"]["rotation"], r"C:\壁纸\海边.jpg"),
            "2 张 · 当前 海边.jpg",
        )

    def testCardSummaryFollowsTheCurrentWallpaper(self):
        task = interval_task(
            wallpaper={
                "mode": ROTATION_WALLPAPER,
                "fixed": "",
                "rotation": [r"C:\a.jpg", r"C:\b.jpg"],
            }
        )
        card = HomeCardTaskCard(task, [], None, parent=self.host)

        updateHomeCardTaskState(task["id"], wallpaper=r"C:\b.jpg")

        self.assertIn("轮换 2/2 · b.jpg", card.expandCard.card.contentLabel.text())
        self.assertEqual(
            card.formWidgets["rotationField"].summaryLabel.text(),
            "2 张 · 当前 b.jpg",
        )

    def testRotationDialogSkipsDuplicatesAndMovesRows(self):
        dialog = WallpaperRotationDialog([r"C:\a.jpg"], r"C:\a.jpg", self.host)

        self.assertEqual(
            dialog.addPaths([r"C:\b.jpg", r"c:\A.JPG", r"C:\c.jpg"]),
            (2, 1),
        )
        rows = dialog.list.rows
        self.assertTrue(rows[0].currentBadge.isVisibleTo(rows[0]))
        dialog.list.moveRow(rows[2], 0)
        self.assertEqual(dialog.paths(), [r"C:\c.jpg", r"C:\a.jpg", r"C:\b.jpg"])
        rows[1].moveLastRequested.emit()
        self.assertEqual(dialog.paths(), [r"C:\c.jpg", r"C:\b.jpg", r"C:\a.jpg"])
        dialog._removeRow(dialog.list.rows[0])
        self.assertEqual(dialog.paths(), [r"C:\b.jpg", r"C:\a.jpg"])
        self.assertEqual(dialog.countLabel.text(), "共 2 张")
        dialog.done(0)
        dialog.deleteLater()


class IntervalTaskRuntimeTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.directory = isolateCfg(self)
        cfg.set(cfg.homeCardTasks, [])
        cfg.set(cfg.homeCardTaskState, {})
        cfg.set(cfg.homeCardTasksEnabled, True)
        self.quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        self.quotaPatcher.start()
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)
        self.window.scheduleTimer.stop()

    def tearDown(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.quotaPatcher.stop()

    def check(self, now, tasks):
        with patch.object(cfg.homeCardTasks, "_ConfigItem__value", list(tasks)):
            self.window._checkScheduleAt(now)

    def testScheduleLoopRunsIntervalTasksAndCatchesUpOnce(self):
        task = interval_task(mode=CUSTOM_HOME_CARD_TASK)
        with (
            patch.object(self.window, "_handleHomeCardTask") as handle,
            patch("app.common.clock.timeOffset", return_value=0.0),
        ):
            self.check(at(2026, 10, 26, 12, 0), [task])
            self.check(at(2026, 10, 29, 7, 55), [task])
            self.check(at(2026, 10, 29, 7, 55, 1), [task])

        handle.assert_called_once()
        self.assertEqual(handle.call_args.args[0]["id"], task["id"])

    def testWallpaperTaskAdvancesTheCurrentWallpaper(self):
        images = []
        for name in ("a.jpg", "b.jpg"):
            path = self.directory / name
            path.write_bytes(b"x")
            images.append(str(path))
        task = interval_task(
            wallpaper={"mode": ROTATION_WALLPAPER, "fixed": "", "rotation": images}
        )
        cfg.set(cfg.homeCardTasks, [task])

        with patch("app.common.wallpaper.setDesktopWallpaper", return_value=None):
            self.window._handleHomeCardTask(task)
            run_until_idle(self.window._homeCardTaskWorkers[task["id"]])
            self.assertEqual(homeCardTaskState(task["id"])["wallpaper"], images[0])

            self.window._handleHomeCardTask(task)
            run_until_idle(self.window._homeCardTaskWorkers[task["id"]])

        self.assertEqual(homeCardTaskState(task["id"])["wallpaper"], images[1])
        self.assertEqual(self.window._homeCardTaskWorkers, {})

    def testWallpaperFailureIsShownAsTaskError(self):
        task = interval_task(
            wallpaper={"mode": ROTATION_WALLPAPER, "fixed": "", "rotation": []}
        )
        cfg.set(cfg.homeCardTasks, [task])

        with patch.object(self.window, "_showHomeCardTaskError") as showError:
            self.window._handleHomeCardTask(task)
            run_until_idle(self.window._homeCardTaskWorkers[task["id"]])

        showError.assert_called_once()
        self.assertIn("轮换列表里没有图片", showError.call_args.args[1])
