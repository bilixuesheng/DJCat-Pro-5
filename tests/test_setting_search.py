import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import TestCase
from unittest.mock import call, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QImage
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow

from app.config.cfg import (
    BANNER_IMAGE_PRESETS,
    BANNER_PRESET_SCALE_MODES,
    cfg,
)
from app.config.constants import APP_NAME
from app.config.paths import ASSET_DIR
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow


class SettingSearchTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.windowTitle = cfg.windowTitle.value
        self.applicationIcon = self.app.windowIcon()
        self.iconValues = [
            (item, item.value)
            for item in (cfg.applicationIconSource, cfg.applicationIconPath)
        ]
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(cfg.applicationIconSource, "默认")
        cfg.set(cfg.applicationIconPath, "")
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
        cfg.set(cfg.windowTitle, self.windowTitle)
        for item, value in self.iconValues:
            cfg.set(item, value)
        self.app.setWindowIcon(self.applicationIcon)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testSearchVisibilityUpdatesWhenNavigationStarts(self):
        self.assertTrue(self.window.searchEdit.isHidden())

        self.window.switchTo(self.window.settingPage)

        self.assertFalse(self.window.searchEdit.isHidden())
        self.assertIsNot(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
            "The transition should still be running when the search appears",
        )

        QTest.qWait(500)
        self.assertIs(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
        )

        self.window.searchEdit.setText("主题")
        self.window.switchTo(self.window.homePage)

        self.assertTrue(self.window.searchEdit.isHidden())
        self.assertEqual(self.window.searchEdit.text(), "")
        self.assertIs(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
            "The transition should still be running when the search disappears",
        )

    def testDuplicateNavigationDuringTransitionIsIgnored(self):
        with patch.object(MSFluentWindow, "switchTo", autospec=True) as switchTo:
            self.window.switchTo(self.window.settingPage)
            self.window.switchTo(self.window.settingPage)

        switchTo.assert_called_once_with(self.window, self.window.settingPage)

    def testCustomWindowTitleUpdatesAndBlankRestoresDefault(self):
        titleEdit = self.window.settingPage.windowTitleCard.lineEdit
        titleEdit.setText("值班控制台")
        titleEdit.editingFinished.emit()
        self.assertEqual(cfg.windowTitle.value, "值班控制台")
        self.assertEqual(self.window.windowTitle(), "值班控制台")

        titleEdit.setText("   ")
        titleEdit.editingFinished.emit()
        self.assertEqual(self.window.windowTitle(), APP_NAME)

    def testCustomApplicationIconCardOnlyAppearsForCustomSource(self):
        page = self.window.settingPage.ensureLoaded()

        self.assertTrue(page.applicationIconCard.isHidden())

        cfg.set(cfg.applicationIconSource, "自定义")
        self.assertFalse(page.applicationIconCard.isHidden())

        cfg.set(cfg.applicationIconSource, "默认")
        self.assertTrue(page.applicationIconCard.isHidden())

    def testCustomApplicationIconUpdatesWindowsAndRestoresDefault(self):
        path = Path(self.tempDir.name) / "custom-icon.png"
        image = QImage(24, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ce352c"))
        self.assertTrue(image.save(str(path)))
        defaultIcon = self.window.windowIcon().pixmap(24, 24).toImage()

        cfg.set(cfg.applicationIconSource, "自定义")
        cfg.set(cfg.applicationIconPath, str(path))

        for icon in (self.window.windowIcon(), self.app.windowIcon()):
            self.assertEqual(
                icon.pixmap(24, 24).toImage().pixelColor(12, 12).name(),
                "#ce352c",
            )

        cfg.set(cfg.applicationIconSource, "默认")
        self.assertEqual(
            self.window.windowIcon().pixmap(24, 24).toImage(),
            defaultIcon,
        )

    def testSplashScreenUsesCustomApplicationIcon(self):
        path = Path(self.tempDir.name) / "custom-icon.png"
        image = QImage(24, 24, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ce352c"))
        self.assertTrue(image.save(str(path)))
        cfg.set(cfg.applicationIconPath, str(path))
        cfg.set(cfg.applicationIconSource, "自定义")

        with patch("app.view.windows.main_window.CustomSplashScreen") as splash:
            self.window.initSplashScreen()

        icon = splash.call_args.args[0]
        self.assertEqual(
            icon.pixmap(24, 24).toImage().pixelColor(12, 12).name(),
            "#ce352c",
        )
        self.window.splashScreen = None

    def testMissingCustomApplicationIconFallsBackToDefault(self):
        defaultIcon = self.window.windowIcon().pixmap(24, 24).toImage()

        cfg.set(cfg.applicationIconPath, str(Path(self.tempDir.name) / "missing.ico"))
        cfg.set(cfg.applicationIconSource, "自定义")

        self.assertEqual(
            self.window.windowIcon().pixmap(24, 24).toImage(),
            defaultIcon,
        )

    def testApplicationIconPickerAcceptsIcoAndStoresSelectedPath(self):
        page = self.window.settingPage.ensureLoaded()
        path = str(Path(self.tempDir.name) / "custom.ico")

        with patch(
            "app.view.pages.setting_page.QFileDialog.getOpenFileName",
            return_value=(path, ""),
        ) as picker:
            page._onChooseApplicationIconClicked()

        self.assertEqual(cfg.applicationIconPath.value, path)
        self.assertEqual(cfg.applicationIconSource.value, "自定义")
        self.assertIn("*.ico", picker.call_args.args[3])

    def testClearingStoreCacheDropsPinnedIconPathsAndKeepsFallback(self):
        item = cfg.pinnedHomeCards
        oldValue = item.value
        cachedIcon = Path(self.tempDir.name) / "cached-icon.png"
        cachedIcon.write_bytes(b"stale")
        cards = [
            {
                "app_id": 7,
                "preset_id": 0,
                "title": "Ghost Downloader",
                "description": "下载工具",
                "action": {"type": "program", "target": "ghost.exe"},
                "install_dir": "ghost-downloader",
                "icon_url": "https://example.test/icon.png",
                "icon_path": str(cachedIcon),
            }
        ]
        try:
            cfg.set(item, cards)
            self.window._setPinnedHomeCards(cards)

            self.window.settingPage.appStoreCacheCleared.emit()

            self.assertEqual(cfg.pinnedHomeCards.value[0]["icon_path"], "")
            stored = next(iter(self.window.homePage._applicationCardData.values()))
            self.assertEqual(stored["icon_path"], "")
        finally:
            cfg.set(item, oldValue)

    def testBannerPresetsUseExpectedAssetsAndDefault(self):
        self.assertEqual(
            BANNER_IMAGE_PRESETS,
            {
                "预设: 树人门": "home.png",
                "预设: 罗小黑": "luoxiaoheimiao.jpg",
                "预设: 罗小黑（2）": "luoxiaoheimiao2.jpg",
                "预设: 罗小黑（3）": "luoxiaoheimiao3.jpg",
            },
        )
        self.assertEqual(
            cfg.bannerImageSource.defaultValue,
            "预设: 罗小黑",
        )
        for filename in BANNER_IMAGE_PRESETS.values():
            self.assertTrue((ASSET_DIR / filename).is_file())

    def testBannerPresetsUseExpectedScaleModes(self):
        self.window.settingPage.ensureLoaded()
        source = cfg.bannerImageSource.value
        scaleMode = cfg.bannerScaleMode.value
        try:
            for preset, expectedScaleMode in BANNER_PRESET_SCALE_MODES.items():
                with self.subTest(preset=preset):
                    cfg.set(cfg.bannerImageSource, "自定义")
                    cfg.set(
                        cfg.bannerScaleMode,
                        "缩放(中)"
                        if expectedScaleMode == "缩放(下)"
                        else "缩放(下)",
                    )
                    cfg.set(cfg.bannerImageSource, preset)

                    self.assertEqual(
                        cfg.bannerScaleMode.value,
                        expectedScaleMode,
                    )
                    self.assertEqual(
                        self.window.homePage.banner.get_image_path(),
                        str(ASSET_DIR / BANNER_IMAGE_PRESETS[preset]),
                    )
        finally:
            cfg.set(cfg.bannerImageSource, source)
            cfg.set(cfg.bannerScaleMode, scaleMode)

    def testRepeatedQueuedDestinationRunsOnlyOnce(self):
        changes = []
        self.window.stackedWidget.currentChanged.connect(
            lambda _: changes.append(self.window.stackedWidget.currentWidget())
        )

        self.window.switchTo(self.window.settingPage)
        self.window.switchTo(self.window.creditsPage)
        self.window.switchTo(self.window.creditsPage)
        QTest.qWait(800)

        self.assertEqual(
            changes,
            [self.window.settingPage, self.window.creditsPage],
        )
        self.assertIsNone(self.window._navigationTarget)
        self.assertIsNone(self.window._pendingNavigation)

    def testLatestQueuedDestinationReplacesIntermediateDestination(self):
        changes = []
        schedulePage = self.window._getSchedulePage()
        self.window.stackedWidget.currentChanged.connect(
            lambda _: changes.append(self.window.stackedWidget.currentWidget())
        )

        self.window.switchTo(self.window.settingPage)
        self.window.switchTo(self.window.creditsPage)
        self.window.switchTo(schedulePage)
        QTest.qWait(800)

        self.assertEqual(
            changes,
            [self.window.settingPage, schedulePage],
        )
        self.assertIs(
            self.window.stackedWidget.currentWidget(),
            schedulePage,
        )

    def testTaskPagesAreCreatedOnlyWhenFirstOpened(self):
        pageSpecs = (
            ("全屏投送", "broadcastEditPage"),
            ("考试倒计时", "countdownPage"),
            ("定时播报", "schedulePage"),
            ("自动任务", "homeCardTaskPage"),
            ("定时关机", "shutdownPage"),
        )
        self.assertTrue(
            all(getattr(self.window, name) is None for _, name in pageSpecs)
        )

        for title, name in pageSpecs:
            with self.subTest(page=name):
                previousCount = self.window.stackedWidget.count()
                self.window.homePage.all_cards[title].clicked.emit()
                QTest.qWait(500)
                page = getattr(self.window, name)

                self.assertIsNotNone(page)
                self.assertIs(self.window.stackedWidget.currentWidget(), page)
                self.assertEqual(
                    self.window.stackedWidget.count(),
                    previousCount + 1,
                )

                self.window._navToHome()
                QTest.qWait(500)

                self.window.homePage.all_cards[title].clicked.emit()
                QTest.qWait(500)

                self.assertIs(getattr(self.window, name), page)
                self.assertEqual(
                    self.window.stackedWidget.count(),
                    previousCount + 1,
                )

                self.window._navToHome()
                QTest.qWait(500)

    def testFullscreenClockOpensDirectlyWithoutAddingEditorPage(self):
        pageCount = self.window.stackedWidget.count()
        currentPage = self.window.stackedWidget.currentWidget()
        showMainWindow = cfg.showMainWindowAfterFullscreenClock.value
        try:
            cfg.set(cfg.showMainWindowAfterFullscreenClock, True)
            self.window.homePage.all_cards["全屏时钟"].clicked.emit()
            self.app.processEvents()

            clock = self.window.fullscreenClockWindow
            self.assertIsNotNone(clock)
            self.assertTrue(clock.isVisible())
            self.assertTrue(self.window.isHidden())
            self.assertEqual(self.window.stackedWidget.count(), pageCount)
            self.assertIs(self.window.stackedWidget.currentWidget(), currentPage)

            clock.close()
            QTest.qWait(500)
            self.assertTrue(self.window.isVisible())
            self.assertIs(
                self.window.stackedWidget.currentWidget(),
                self.window.homePage,
            )
        finally:
            cfg.set(cfg.showMainWindowAfterFullscreenClock, showMainWindow)
            if self.window.fullscreenClockWindow is not None:
                self.window.fullscreenClockWindow.close()

    def testFullscreenClockSettingsFollowRequestedGroupOrder(self):
        page = self.window.settingPage.ensureLoaded()
        groups = [
            page.broadcastGroup,
            page.aiMarkdownGroup,
            page.countdownGroup,
            page.fullscreenClockGroup,
            page.personalGroup,
            page.softwareGroup,
        ]

        self.assertEqual(
            [page.vBoxLayout.indexOf(group) for group in groups],
            sorted(page.vBoxLayout.indexOf(group) for group in groups),
        )
        self.assertEqual(
            [
                card.titleLabel.text()
                for card in page.fullscreenClockGroup.settingCards()
            ],
            [
                "背景类型",
                "背景颜色",
                "自定义时钟背景",
                "图片缩放模式",
                "显示任务栏",
                "全屏时置顶",
                "窗口化时置顶",
                "操作按钮位置",
                "关闭后显示主页面",
                "退出前询问",
            ],
        )

    def testBackgroundSchedulesDoNotLoadManagementPages(self):
        broadcastTask = {
            "enabled": True,
            "weeks": [0],
            "time": "08:00:00",
            "type": "系统TTS",
            "content": "测试",
        }
        shutdownTask = {
            "enabled": True,
            "weeks": [0],
            "time": "08:00:00",
            "notify": False,
        }

        with (
            patch.object(self.window, "_playAudioTask") as playAudio,
            patch.object(self.window, "_handleShutdownTask") as handleShutdown,
        ):
            self.window._runScheduledTasks(
                "broadcast",
                [broadcastTask],
                "2026-08-17",
                "08:00:00",
                0,
                playAudio,
            )
            self.window._runScheduledTasks(
                "shutdown",
                [shutdownTask],
                "2026-08-17",
                "08:00:00",
                0,
                handleShutdown,
            )

        playAudio.assert_called_once_with(broadcastTask)
        handleShutdown.assert_called_once_with(shutdownTask)
        self.assertIsNone(self.window.schedulePage)
        self.assertIsNone(self.window.shutdownPage)

    def testSchedulesRunEveryDayWithoutRestarting(self):
        task = {
            "enabled": True,
            "weeks": [0],
            "time": "08:00:00",
            "type": "系统TTS",
            "content": "测试",
        }
        with patch.object(self.window, "_playAudioTask") as playAudio:
            self.window._runScheduledTasks(
                "broadcast", [task], "2026-08-17", "08:00:00", 0, playAudio
            )
            self.window._runScheduledTasks(
                "broadcast", [task], "2026-08-17", "08:00:00", 0, playAudio
            )
            self.window._runScheduledTasks(
                "broadcast", [task], "2026-08-18", "08:00:00", 0, playAudio
            )

        self.assertEqual(playAudio.call_count, 2)

    def testAllSchedulesAtTheSameSecondRunOnce(self):
        tasks = [
            {
                "enabled": True,
                "weeks": [0],
                "time": "08:00:00",
                "type": "系统TTS",
                "content": content,
            }
            for content in ("第一条", "第二条")
        ]
        with patch.object(self.window, "_playAudioTask") as playAudio:
            self.window._runScheduledTasks(
                "broadcast", tasks, "2026-08-17", "08:00:00", 0, playAudio
            )
            self.window._runScheduledTasks(
                "broadcast", tasks, "2026-08-17", "08:00:00", 0, playAudio
            )

        self.assertEqual(
            [call.args[0]["content"] for call in playAudio.call_args_list],
            ["第一条", "第二条"],
        )

    def testAudioTasksAtTheSameSecondArePlayedInOrder(self):
        first = {"type": "系统TTS", "content": "第一条"}
        second = {"type": "系统TTS", "content": "第二条"}
        with patch.object(
            self.window, "_startAudioTask", return_value=True, create=True
        ) as start:
            self.window._playAudioTask(first)
            self.window._playAudioTask(second)
            self.assertEqual(start.call_args_list, [call(first)])

            self.window._finishAudioTask()
            self.app.processEvents()

        self.assertEqual(start.call_args_list, [call(first), call(second)])

    def testMediaErrorAdvancesTheScheduledAudioQueue(self):
        nextTask = {"type": "系统TTS", "content": "下一条"}
        self.window._audioTaskActive = True
        self.window._activeAudioKind = "media"
        self.window._audioTaskQueue.append(nextTask)

        with patch.object(
            self.window, "_startAudioTask", return_value=True
        ) as start:
            self.window.player.errorOccurred.emit(
                QMediaPlayer.Error.ResourceError,
                "decoder failed",
            )
            self.app.processEvents()

        start.assert_called_once_with(nextTask)
        self.assertTrue(self.window._audioTaskActive)

    def testScheduleCatchesUpWhenGuiSkipsTheTargetSecond(self):
        task = {
            "enabled": True,
            "weeks": [0],
            "time": "08:00:00",
            "type": "系统TTS",
            "content": "测试",
        }
        timezone = datetime.now().astimezone().tzinfo
        with patch.object(self.window, "_playAudioTask") as playAudio:
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 7, 59, 59, tzinfo=timezone),
                [task],
                [],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 1, tzinfo=timezone),
                [task],
                [],
            )

        playAudio.assert_called_once_with(task)

    def testScheduleCatchesUpAfterLongGuiBlock(self):
        task = {
            "enabled": True,
            "weeks": [0],
            "time": "08:00:00",
            "type": "系统TTS",
            "content": "长阻塞后补播",
        }
        timezone = datetime.now().astimezone().tzinfo
        with patch.object(self.window, "_playAudioTask") as playAudio:
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 7, 59, 30, tzinfo=timezone),
                [task],
                [],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 30, tzinfo=timezone),
                [task],
                [],
            )

        playAudio.assert_called_once_with(task)

    def testShutdownDoesNotReplayAStaleTriggerAfterGuiBlock(self):
        task = {
            "enabled": True,
            "weeks": [0],
            "time": "08:00:00",
            "action": "关机",
        }
        timezone = datetime.now().astimezone().tzinfo
        with patch.object(self.window, "_handleShutdownTask") as handleShutdown:
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 7, 59, 30, tzinfo=timezone),
                [],
                [task],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 30, tzinfo=timezone),
                [],
                [task],
            )

        handleShutdown.assert_not_called()

    def testScheduleCatchUpHandlesMidnight(self):
        task = {
            "enabled": True,
            "weeks": [1],
            "time": "00:00:00",
            "type": "系统TTS",
            "content": "跨日",
        }
        timezone = datetime.now().astimezone().tzinfo
        with patch.object(self.window, "_playAudioTask") as playAudio:
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 23, 59, 59, tzinfo=timezone),
                [task],
                [],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 18, 0, 0, 1, tzinfo=timezone),
                [task],
                [],
            )

        playAudio.assert_called_once_with(task)

    def testScheduleDoesNotReplayHoursOldTaskAfterResume(self):
        broadcast = {
            "enabled": True,
            "weeks": [0],
            "time": "12:30:00",
            "type": "系统TTS",
            "content": "已过期",
        }
        shutdown = {
            "enabled": True,
            "weeks": [0],
            "time": "18:00:00",
            "action": "关机",
        }
        timezone = datetime.now().astimezone().tzinfo
        with (
            patch.object(self.window, "_playAudioTask") as playAudio,
            patch.object(self.window, "_handleShutdownTask") as handleShutdown,
        ):
            self.window._checkScheduleAt(
                datetime(2026, 8, 17, 8, 0, 0, tzinfo=timezone),
                [broadcast],
                [shutdown],
            )
            self.window._checkScheduleAt(
                datetime(2026, 8, 18, 8, 0, 0, tzinfo=timezone),
                [broadcast],
                [shutdown],
            )

        playAudio.assert_not_called()
        handleShutdown.assert_not_called()
