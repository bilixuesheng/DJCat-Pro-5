from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg


class TaskPageBackgroundTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
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

    def testOpeningATaskPageDoesNotRestyleEveryLoadedPage(self):
        # 页面栈的背景跟着当前页的 isStackedTransparent 变；任务页没设这个属性时，
        # 每进一次都对整个页面栈 setStyle()，所有已加载页面的控件全部重新排样式。
        stacked = self.window.stackedWidget
        getters = (
            self.window._getBroadcastEditPage,
            self.window._getCountdownPage,
            self.window._getSchedulePage,
            self.window._getShutdownPage,
            self.window._getHomeCardTaskPage,
        )
        for getter in getters:
            page = getter()
            with self.subTest(page=page.objectName()):
                with (
                    patch.object(stacked, "setStyle") as setStyle,
                    patch.object(stacked, "currentWidget", return_value=page),
                ):
                    self.window._updateStackedBackground()

                setStyle.assert_not_called()
