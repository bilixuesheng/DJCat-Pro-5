from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.pages.setting_page import EXPERIMENTAL_SECTION_KEY, SettingPage
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


class ExperimentalSettingsTest(_WindowTest):
    def _settingPage(self):
        window = self._window()
        window.settingPage.ensureLoaded()
        return window.settingPage.page

    def testExperimentsLiveUnderTheApplicationSectionAndSayTheyAreForDevelopers(self):
        page = self._settingPage()

        self.assertEqual(page.routeFor(EXPERIMENTAL_SECTION_KEY)[-2], "software")
        navigation = next(
            card
            for card in page.sectionStack.view("software").navigationCards()
            if card.titleLabel.text() == "实验性功能"
        )
        self.assertIn(DEVELOPER_ONLY, navigation.contentLabel.text())
        cards = page.sectionStack.view(EXPERIMENTAL_SECTION_KEY).settingCards()
        self.assertEqual(
            [card.titleLabel.text() for card in cards],
            ["新触控", "新滚动触控", "停用页面懒加载"],
        )
        self.assertEqual(
            [card.configItem for card in cards],
            [cfg.touchPressFeedback, cfg.tunedTouchScroll, cfg.eagerPageLoading],
        )
        self.assertIn("谨慎关闭", cards[2].contentLabel.text())

    def testExperimentsNeverShowUpInSettingSearch(self):
        page = self._settingPage()

        for text in ("新触控", "滚动触控", "懒加载", "触控", "加载"):
            with self.subTest(text=text):
                self.assertNotIn(
                    EXPERIMENTAL_SECTION_KEY,
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
