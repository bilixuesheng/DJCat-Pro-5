from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import FluentIcon as FIF, RoundMenu

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.components.setting_preview import (
    MAIN_WINDOW_PREVIEW_HEIGHT,
    MainWindowPreview,
    MainWindowReplica,
    TrayPreview,
)
from app.view.pages.setting_page import SettingPage
from app.view.shell.tray import SystemTrayIcon
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


class TrayPreviewTest(TestCase):
    ENTRIES = [
        {"key": "custom:one", "source": "custom", "title": "自定义入口", "icon": FIF.APPLICATION},
        {"key": "custom:two", "source": "custom", "title": "第二项", "icon": FIF.LINK},
    ]

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.trayHomeCardKeys, ["custom:one", "custom:two"])
        cfg.set(cfg.trayHomeCardsInSubmenu, False)
        self.preview = TrayPreview()
        self.addCleanup(self.preview.deleteLater)
        self.preview.setHomeCards(self.ENTRIES)
        self.preview.resize(700, self.preview.height())
        self.preview.show()
        self.app.processEvents()

    def _texts(self, menu):
        return [action.text() for action in menu.actions()]

    def testTheMenuHasTheTraysOwnRows(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        tray = SystemTrayIcon(parent)
        tray.setHomeCards(self.ENTRIES)

        self.assertEqual(self._texts(self.preview.menuParts.menu), self._texts(tray.menu))

        cfg.set(cfg.showBroadcastTrayAction, False)
        cfg.set(cfg.homeCardTasksEnabled, False)
        self.app.processEvents()

        self.assertEqual(self._texts(self.preview.menuParts.menu), self._texts(tray.menu))
        self.assertIn("开启自动任务", self._texts(self.preview.menuParts.menu))

    def testTheMenuStandsOnTheTaskbarAgainstTheRightEdge(self):
        menu = self.preview.menuRect()
        taskbar = self.preview.taskbarRect()

        self.assertEqual(menu.size(), self.preview.menuParts.menu.view.size())
        self.assertEqual(menu.bottom() + 1, taskbar.top())
        # AcrylicMenu.adjustPosition 按 rect.right() - (宽 + 5) 放左边，
        # QRect.right() 两头各少 1 px，菜单右缘离屏幕边 6 px。
        self.assertEqual(self.preview.width() - 1 - menu.right(), 6)
        self.assertEqual(
            self.preview.height(),
            TrayPreview.TOP_MARGIN + menu.height() + taskbar.height(),
        )

    def testTheSubmenuOpensWhereTheRealOneWould(self):
        cfg.set(cfg.trayHomeCardsInSubmenu, True)
        self.app.processEvents()
        menu, submenu = self.preview.menuRect(), self.preview.submenuRect()

        submenus = self.preview.menuParts.menu.findChildren(RoundMenu)
        self.assertEqual([menu.title() for menu in submenus], ["主页卡片"])
        self.assertEqual(self._texts(submenus[0]), ["自定义入口", "第二项"])
        # 菜单贴着屏幕右边，右侧放不下，二级菜单开在左边，与条目相隔 5 px。
        self.assertEqual(menu.left() - 5 - submenu.width(), submenu.left())
        self.assertLessEqual(submenu.bottom() + 1, self.preview.taskbarRect().top())

    def testTheTooltipShowsTheConfiguredTextOrTheApplicationName(self):
        self.assertEqual(self.preview.tooltipText(), APP_NAME)

        cfg.set(cfg.trayTooltip, "  值班托盘 ")

        self.assertEqual(self.preview.tooltipText(), "值班托盘")
        tooltip = self.preview.tooltipRect()
        self.assertLess(tooltip.right(), self.preview.menuRect().left())
        self.assertLess(tooltip.bottom(), self.preview.taskbarRect().top())

    def testMoreShortcutsMakeTheMenuAndThePreviewTaller(self):
        height = self.preview.height()

        cfg.set(cfg.trayHomeCardKeys, ["custom:one"])
        self.app.processEvents()

        self.assertEqual(self.preview.height(), height - 28)
