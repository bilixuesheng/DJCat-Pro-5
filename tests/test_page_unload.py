from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from app.common.install_location import installLocation
from app.view.pages.setting_page import SettingPage
from app.view.windows import main_window
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg


class _Store:
    """Enough of ApplicationStore for a page that is built but never shown."""

    architecture = "x86_64"

    def __init__(self):
        self.programDir = Path(installLocation()).resolve()
        self.launched = {}
        self.stopped = False

    def mergeInstalled(self, apps):
        return list(apps)

    def cachedImagePath(self, _url):
        return ""

    def locationAvailable(self):
        return True

    def shutdown(self):
        self.stopped = True


class PageUnloadTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        for patcher in (
            patch.object(SettingPage, "_refreshAIQuota"),
            patch("app.view.pages.app_store_page.ApplicationStore", side_effect=_Store),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)
        self.addCleanup(self._close)

    def _close(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def testBothPagesGoAndComeBackWhenNeeded(self):
        settings = self.window.settingPage.ensureLoaded()
        store = self.window.appStorePage.ensureLoaded()

        self.assertTrue(self.window._unloadIdlePages())

        self.assertFalse(self.window.settingPage.isLoaded())
        self.assertFalse(self.window.appStorePage.isLoaded())
        self.assertFalse(isValid(settings))
        self.assertFalse(isValid(store))
        rebuilt = self.window.settingPage.ensureLoaded()
        self.assertIsNot(rebuilt, settings)
        # 托盘设置里的主页卡片开关要的 Home Card 列表由外壳暂存，重建后照样有。
        self.assertEqual(
            [entry["key"] for entry in rebuilt.trayCardShortcutList._homeCards],
            [entry["key"] for entry in self.window.homePage.homeCardEntries()],
        )

    def testNothingLoadedMeansNothingToWaitFor(self):
        self.assertTrue(self.window._unloadIdlePages())

    def testLeavingTheCurrentPageGoesHome(self):
        self.window.stackedWidget.view.setAnimationEnabled(False)
        self.window.switchTo(self.window.settingPage)
        self.window.stackedWidget.view.setAnimationEnabled(True)
        self.assertIs(self.window.stackedWidget.currentWidget(), self.window.settingPage)

        self.window._unloadIdlePages()

        self.assertIs(self.window.stackedWidget.currentWidget(), self.window.homePage)
        self.assertFalse(self.window.settingPage.isLoaded())

    def testABusyApplicationStoreWaitsWhileSettingsGo(self):
        self.window.settingPage.ensureLoaded()
        page = self.window.appStorePage.ensureLoaded()
        page._installing.add(7)

        self.assertFalse(self.window._unloadIdlePages())

        self.assertFalse(self.window.settingPage.isLoaded())
        self.assertIs(self.window.appStorePage.page, page)
        page._installing.clear()
        self.assertTrue(self.window._unloadIdlePages())

    def testTheApplicationStoreWaitsForItsCatalogToLoad(self):
        page = self.window.appStorePage.ensureLoaded()
        page._catalogLoading = True

        self.assertFalse(self.window._unloadIdlePages())

        self.assertIs(self.window.appStorePage.page, page)
        page._catalogLoading = False
        self.assertTrue(self.window._unloadIdlePages())

    def testNothingGoesInsideANestedEventLoop(self):
        settings = self.window.settingPage.ensureLoaded()

        with patch.object(main_window, "_insideNestedEventLoop", return_value=True):
            self.assertFalse(self.window._unloadIdlePages())

        self.assertIs(self.window.settingPage.page, settings)

    def testTheApplicationStoreKeepsItsStoreAcrossRebuilds(self):
        store = self.window.appStorePage.ensureLoaded().store
        store.launched["教室软件"] = "进程"

        self.window._unloadIdlePages()
        rebuilt = self.window.appStorePage.ensureLoaded()

        self.assertIs(rebuilt.store, store)
        self.assertFalse(store.stopped)

    def testQuittingStopsTheStoreEvenWithThePageUnloaded(self):
        store = self.window.appStorePage.ensureLoaded().store
        self.window._unloadIdlePages()

        self.window._shutdownResources()

        self.assertTrue(store.stopped)

    def testABuiltPageTellsMemoryRelease(self):
        with patch.object(self.window.memoryRelease, "_restart") as restart:
            self.window.appStorePage.ensureLoaded()

        # 主窗口藏着（静默启动）时建起来的页面，也要等十分钟后卸下。
        restart.assert_called_once_with()

    def testCreatingWindowsAfterUnloadingTouchScrolledSectionsIsSafe(self):
        # 抓过触控手势的视口照弹窗的做法先放开再删；做错了，之后创建任意窗口时会崩溃。
        from PySide6.QtWidgets import QScroller, QWidget

        self.window.show()
        self.window.stackedWidget.view.setAnimationEnabled(False)
        self.window.switchTo(self.window.settingPage)
        self.window.stackedWidget.view.setAnimationEnabled(True)
        self.app.processEvents()
        page = self.window.settingPage.page
        self.assertTrue(
            any(QScroller.hasScroller(child) for child in page.findChildren(QWidget))
        )
        self.window.hide()

        self.assertTrue(self.window._unloadIdlePages())
        for _ in range(3):
            other = QWidget()
            other.show()
            self.app.processEvents()
            other.close()
            other.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.window.show()
        self.window.switchTo(self.window.settingPage)
        self.app.processEvents()
        self.assertTrue(self.window.settingPage.isLoaded())
