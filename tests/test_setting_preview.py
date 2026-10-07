from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication, QWidget

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.components.setting_preview import (
    MAIN_WINDOW_PREVIEW_HEIGHT,
    MainWindowPreview,
    MainWindowReplica,
)
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg


def _rectIn(widget, ancestor) -> QRect:
    return QRect(widget.mapTo(ancestor, QPoint()), widget.size())


class MainWindowReplicaTest(TestCase):
    """The replica must stay pinned to the real main window's geometry."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        quotaPatcher.start()
        self.addCleanup(quotaPatcher.stop)
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)
        self.addCleanup(self._closeWindow)
        self.window.show()
        self.window.resize(1000, 640)
        self.app.processEvents()

    def _closeWindow(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _replica(self):
        replica = MainWindowReplica()
        self.addCleanup(replica.deleteLater)
        replica.setHomeCards(self.window.homePage.homeCardEntries())
        replica.layoutFor(self.window.size())
        return replica

    def testNavigationTitleBarAndHomePageSitWhereTheRealOnesDo(self):
        replica = self._replica()
        window = self.window
        home = window.homePage

        for key, item in window.navigationInterface.items.items():
            with self.subTest(item=key):
                self.assertEqual(
                    _rectIn(replica.navigationButtons[key], replica),
                    _rectIn(item, window),
                )
        for name in ("minBtn", "maxBtn", "closeBtn"):
            with self.subTest(button=name):
                self.assertEqual(
                    _rectIn(getattr(replica, name), replica),
                    _rectIn(getattr(window.titleBar, name), window),
                )
        self.assertEqual(
            _rectIn(replica.banner, replica), _rectIn(home.banner, window)
        )
        self.assertEqual(
            _rectIn(replica.subTitle, replica), _rectIn(home.subTitle, window)
        )
        self.assertEqual(
            _rectIn(replica.sortButton, replica), _rectIn(home.sortBtn, window)
        )
        for key in ("全屏投送", "考试倒计时", "全屏时钟", "定时播报"):
            with self.subTest(card=key):
                self.assertEqual(
                    _rectIn(replica.cards[key], replica),
                    _rectIn(home.allCards[key], window),
                )

    def testHiddenBannerLeavesThePageTitleWhereTheRealOneIs(self):
        cfg.set(cfg.showBanner, False)
        self.app.processEvents()
        replica = self._replica()
        home = self.window.homePage

        self.assertTrue(replica.banner.isHidden())
        self.assertEqual(
            _rectIn(replica.pageTitle, replica), _rectIn(home.normalTitle, self.window)
        )
        self.assertEqual(
            _rectIn(replica.cards["全屏投送"], replica),
            _rectIn(home.allCards["全屏投送"], self.window),
        )

    def testContentFollowsTheSettings(self):
        replica = self._replica()
        self.assertEqual(replica.windowTitle(), APP_NAME)
        self.assertFalse(replica.navigationButtons["CreditsPage"].isHidden())

        cfg.set(cfg.windowTitle, "三年二班")
        cfg.set(cfg.showCreditsPage, False)
        replica.layoutFor(self.window.size())

        self.assertEqual(replica.windowTitle(), "三年二班")
        self.assertTrue(replica.navigationButtons["CreditsPage"].isHidden())
        self.assertEqual(
            [card.titleLabel.text() for card in replica.cards.values()][:2],
            ["全屏投送", "考试倒计时"],
        )


class MainWindowPreviewTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        self.host = QWidget()
        self.addCleanup(self.host.deleteLater)
        self.host.resize(1200, 600)
        self.preview = MainWindowPreview(self.host)
        self.preview.resize(700, MAIN_WINDOW_PREVIEW_HEIGHT)
        self.host.show()
        self.app.processEvents()

    def _aspect(self):
        rect = self.preview.windowRect()
        return rect.width() / rect.height()

    def testTheMiniatureKeepsTheMainWindowsAspectWithinTheHeightCap(self):
        self.assertAlmostEqual(self._aspect(), 2.0, delta=0.02)
        self.assertLessEqual(
            self.preview.windowRect().height(), MAIN_WINDOW_PREVIEW_HEIGHT
        )
        self.assertTrue(
            self.preview.rect().toRectF().contains(self.preview.windowRect())
        )

    def testResizingTheMainWindowReshapesTheMiniature(self):
        self.host.resize(800, 800)
        self.app.processEvents()

        self.assertAlmostEqual(self._aspect(), 1.0, delta=0.02)

    def testTheMiniatureIsRenderedAtDevicePixels(self):
        pixmap = self.preview.renderedPixmap()
        rect = self.preview.windowRect()
        ratio = self.preview.devicePixelRatioF()

        self.assertEqual(pixmap.devicePixelRatio(), ratio)
        self.assertEqual(
            pixmap.size(),
            QSize(round(rect.width() * ratio), round(rect.height() * ratio)),
        )

    def testTheMainWindowsMinimumSizeIsRespected(self):
        self.host.resize(300, 300)
        self.app.processEvents()

        self.assertAlmostEqual(self._aspect(), 700 / 400, delta=0.02)
