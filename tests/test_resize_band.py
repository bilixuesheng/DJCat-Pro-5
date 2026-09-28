from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow

from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg


HIT_TESTS = SimpleNamespace(
    WM_NCHITTEST=0x84, HTCLIENT=1, HTMAXBUTTON=9, HTLEFT=10, HTRIGHT=11,
    HTTOP=12, HTTOPLEFT=13, HTTOPRIGHT=14, HTBOTTOM=15,
    HTBOTTOMLEFT=16, HTBOTTOMRIGHT=17,
)


class MainWindowResizeBandTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.tempDir = isolateCfg(self)
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)
        self.window.show()
        self.window.resize(1000, 700)
        self.app.processEvents()

    def tearDown(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.hide()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _hitTest(self, x, y, libraryHitTest, scale):
        """按 Windows 的方式把逻辑坐标 (x, y) 送进 WM_NCHITTEST，组件库对该点给出 libraryHitTest。"""
        message = SimpleNamespace(
            message=HIT_TESTS.WM_NCHITTEST,
            hWnd=123,
            lParam=((-234 & 0xFFFF) << 16) | (-123 & 0xFFFF),
        )
        with (
            patch("app.view.windows.main_window.sys") as windows,
            patch("app.view.windows.main_window.MSG", create=True) as nativeMessage,
            patch("app.view.windows.main_window.win32gui", create=True) as nativeGui,
            patch("app.view.windows.main_window.win32con", HIT_TESTS, create=True),
            patch.object(MSFluentWindow, "nativeEvent", return_value=(True, libraryHitTest)),
            patch.object(self.window, "devicePixelRatioF", return_value=scale),
        ):
            windows.platform = "win32"
            nativeMessage.from_address.return_value = message
            nativeGui.ScreenToClient.return_value = (x * scale, y * scale)
            self.screenToClient = nativeGui.ScreenToClient
            return self.window.nativeEvent(b"windows_generic_MSG", 1)

    def testTitleBarButtonsNeverStartAResize(self):
        width = self.window.width()
        for scale in (1, 3):
            for x, y, libraryHitTest in (
                (width - 1, 0, HIT_TESTS.HTTOPRIGHT),
                (width - 1, 20, HIT_TESTS.HTRIGHT),
                (width - 20, 2, HIT_TESTS.HTTOP),
                (width - 46 - 20, 2, HIT_TESTS.HTTOP),
                (width - 92 - 20, 2, HIT_TESTS.HTTOP),
            ):
                with self.subTest(scale=scale, x=x, y=y):
                    self.assertEqual(
                        self._hitTest(x, y, libraryHitTest, scale),
                        (True, HIT_TESTS.HTCLIENT),
                    )
                    # 触控时光标可能还停在别处，只有消息里的坐标才是这次按下的位置。
                    self.screenToClient.assert_called_with(123, (-123, -234))

    def testResizeBandRemainsBesideTheTitleBarButtons(self):
        width = self.window.width()
        for scale in (1, 3):
            for x, y, libraryHitTest in (
                (width - 138 - 5, 2, HIT_TESTS.HTTOP),
                (width - 1, 40, HIT_TESTS.HTRIGHT),
                (0, 0, HIT_TESTS.HTTOPLEFT),
            ):
                with self.subTest(scale=scale, x=x, y=y):
                    self.assertEqual(
                        self._hitTest(x, y, libraryHitTest, scale),
                        (True, libraryHitTest),
                    )

    def testMaximizeButtonKeepsSnapLayouts(self):
        width = self.window.width()
        self.assertEqual(
            self._hitTest(width - 46 - 20, 2, HIT_TESTS.HTMAXBUTTON, 1),
            (True, HIT_TESTS.HTMAXBUTTON),
        )
