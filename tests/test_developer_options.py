from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.components.frame_rate import (
    FrameRateLabel,
    isFrameRateShown,
    setFrameRateShown,
)
from app.view.pages.setting_page import DEVELOPER_SECTION_KEY, SettingPage
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg

DEVELOPER_ONLY = "本选项仅供开发人员调试使用"


class _WindowTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        quota = patch.object(SettingPage, "_refreshAIQuota")
        quota.start()
        self.addCleanup(quota.stop)

    def _window(self):
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            window = MainWindow(isSilent=True)
        self.addCleanup(self._close, window)
        return window

    def _close(self, window):
        window.tray = None
        window._shutdownResources()
        window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()


class DeveloperOptionsTest(_WindowTest):
    def _settingPage(self):
        window = self._window()
        window.settingPage.ensureLoaded()
        return window.settingPage.page

    def testOptionsLiveUnderTheApplicationSectionAndSayTheyAreForDevelopers(self):
        page = self._settingPage()

        self.assertEqual(page.routeFor(DEVELOPER_SECTION_KEY)[-2], "software")
        navigation = next(
            card
            for card in page.sectionStack.view("software").navigationCards()
            if card.titleLabel.text() == "开发人员选项"
        )
        self.assertEqual(
            navigation.contentLabel.text(), f"触控、帧率和页面懒加载。{DEVELOPER_ONLY}"
        )
        cards = page.sectionStack.view(DEVELOPER_SECTION_KEY).settingCards()
        self.assertEqual(
            [card.titleLabel.text() for card in cards],
            [
                "停用新触控",
                "停用新滑动触控",
                "停用超级帧率优化",
                "停用页面懒加载",
                "显示帧率",
            ],
        )
        self.assertEqual(
            [card.configItem for card in cards],
            [
                cfg.disableTouchPressFeedback,
                cfg.disableTunedTouchScroll,
                cfg.disableSuperFrameRate,
                cfg.eagerPageLoading,
                cfg.showFrameRate,
            ],
        )
        self.assertIn("谨慎关闭", cards[3].contentLabel.text())

    def testEveryOptionIsOffUntilADeveloperSwitchesItOn(self):
        # 新触控、新滑动触控和超级帧率优化因此默认都在用。
        for item in (
            cfg.disableTouchPressFeedback,
            cfg.disableTunedTouchScroll,
            cfg.disableSuperFrameRate,
            cfg.eagerPageLoading,
            cfg.showFrameRate,
        ):
            with self.subTest(item=item.key):
                self.assertFalse(item.defaultValue)
                self.assertEqual(item.group, "Experimental")

    def testOptionsNeverShowUpInSettingSearch(self):
        page = self._settingPage()

        for text in ("新触控", "滑动触控", "超级帧率", "帧率", "懒加载", "触控", "停用"):
            with self.subTest(text=text):
                self.assertNotIn(
                    DEVELOPER_SECTION_KEY,
                    [suggestion.routeKey for suggestion in page.searchSuggestions(text)],
                )


class EagerPageLoadingTest(_WindowTest):
    def _loaded(self, window):
        return {
            "lazy": [
                page.page is not None
                for page in (window.appStorePage, window.creditsPage, window.settingPage)
            ],
            "task": [
                page is not None
                for page in (
                    window.broadcastEditPage,
                    window.countdownPage,
                    window.schedulePage,
                    window.shutdownPage,
                    window.homeCardTaskPage,
                )
            ],
        }

    def testPagesStayLazyByDefault(self):
        window = self._window()

        self.assertEqual(
            self._loaded(window), {"lazy": [False] * 3, "task": [False] * 5}
        )

    def testSwitchingOnBuildsEveryPageAtOnceAndStartupDoesTooFromThenOn(self):
        window = self._window()
        cfg.set(cfg.eagerPageLoading, True)
        self.assertEqual(self._loaded(window), {"lazy": [True] * 3, "task": [True] * 5})

        restarted = self._window()
        self.assertEqual(
            self._loaded(restarted), {"lazy": [True] * 3, "task": [True] * 5}
        )


class FrameRateOnMainWindowTest(_WindowTest):
    def testLabelSitsInTheTopLeftCornerAboveEverythingElse(self):
        self.addCleanup(setFrameRateShown, isFrameRateShown())
        setFrameRateShown(True)
        window = self._window()
        window.resize(1000, 700)
        window.show()
        self.app.processEvents()

        label = window.findChild(
            FrameRateLabel, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
        self.assertEqual(label.pos(), QPoint(8, 8))
        widgets = [child for child in window.children() if child.isWidgetType()]
        self.assertIs(widgets[-1], label)
        # 不盖到页面上：盖住滚动区视口时 Qt 会退回整块重画。
        stack = window.stackedWidget
        self.assertFalse(
            label.geometry().intersects(
                stack.geometry().translated(stack.parentWidget().mapTo(window, QPoint()))
            )
        )

