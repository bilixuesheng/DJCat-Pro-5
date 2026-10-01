from ctypes import Structure, c_int
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QColor, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow, qconfig

from app.config.cfg import cfg
from app.platform import background_effect
from app.platform.background_effect import (
    BACKGROUND_EFFECTS,
    applyBackgroundEffect,
    defaultBackgroundEffect,
    suspendAcrylic,
    suspendsAcrylicDuringMove,
)
from app.view.windows.main_window import MainWindow
from tests.support import isolateCfg

ACCENT_ENABLE_GRADIENT = 1
ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
SIZE_MOVE = SimpleNamespace(WM_NCHITTEST=0x84, WM_ENTERSIZEMOVE=0x231, WM_EXITSIZEMOVE=0x232)


class _CompositionAttributeData(Structure):
    _fields_ = [("Attribute", c_int)]


def _fakeWindow():
    windowEffect = MagicMock()
    windowEffect.accentPolicy = SimpleNamespace(AccentState=0)
    windowEffect.winCompAttrData = _CompositionAttributeData()
    return SimpleNamespace(windowEffect=windowEffect, winId=lambda: 42)


def _windows(build):
    return SimpleNamespace(
        platform="win32", getwindowsversion=lambda: SimpleNamespace(build=build)
    )


class BackgroundEffectRulesTest(TestCase):
    def testOffersTheSameEffectsAsGhostDownloader(self):
        self.assertEqual(BACKGROUND_EFFECTS, ("Acrylic", "Mica", "MicaAlt", "Aero", "None"))

    def testDefaultIsMicaOnWin11AndNoneOnWin10(self):
        for build, expected in ((19045, "None"), (22000, "Mica"), (26100, "Mica")):
            with self.subTest(build=build), patch.object(background_effect, "sys", _windows(build)):
                self.assertEqual(defaultBackgroundEffect(), expected)

    def testEachEffectReachesItsWindowEffect(self):
        for effect, isDark, expected in (
            ("Acrylic", True, call.setAcrylicEffect(42, "00000030")),
            ("Acrylic", False, call.setAcrylicEffect(42, "FFFFFF30")),
            ("Mica", True, call.setMicaEffect(42, True)),
            ("MicaAlt", False, call.setMicaEffect(42, False, isAlt=True)),
            ("Aero", False, call.setAeroEffect(42)),
        ):
            with self.subTest(effect=effect, isDark=isDark):
                window = _fakeWindow()
                applyBackgroundEffect(window, effect, isDark)
                self.assertEqual(
                    window.windowEffect.method_calls,
                    [call.removeBackgroundEffect(42), expected],
                )

    def testReapplyingOnShowKeepsTheCurrentEffect(self):
        window = _fakeWindow()

        applyBackgroundEffect(window, "Mica", False, removeFirst=False)

        self.assertEqual(window.windowEffect.method_calls, [call.setMicaEffect(42, False)])

    def testMicaIsStillRequestedOnWin10(self):
        window = _fakeWindow()

        with patch.object(background_effect, "isWin10", return_value=True):
            applyBackgroundEffect(window, "Mica", False)

        window.windowEffect.setMicaEffect.assert_called_once_with(42, False)

    def testNoneOnlyRemovesTheEffectOnWin11(self):
        window = _fakeWindow()

        with patch.object(background_effect, "isWin10", return_value=False):
            applyBackgroundEffect(window, "None", False)

        self.assertEqual(window.windowEffect.method_calls, [call.removeBackgroundEffect(42)])

    def testNoneOnWin10SwitchesTheAccentToAGradient(self):
        window = _fakeWindow()

        with patch.object(background_effect, "isWin10", return_value=True):
            applyBackgroundEffect(window, "None", False)

        windowEffect = window.windowEffect
        self.assertEqual(windowEffect.accentPolicy.AccentState, ACCENT_ENABLE_GRADIENT)
        self.assertEqual(windowEffect.winCompAttrData.Attribute, 19)
        windowEffect.SetWindowCompositionAttribute.assert_called_once()
        self.assertEqual(windowEffect.SetWindowCompositionAttribute.call_args.args[0], 42)

    def testSuspendingAcrylicKeepsATransparentGradient(self):
        window = _fakeWindow()

        suspendAcrylic(window)

        self.assertEqual(
            window.windowEffect.accentPolicy.AccentState, ACCENT_ENABLE_TRANSPARENTGRADIENT
        )
        window.windowEffect.SetWindowCompositionAttribute.assert_called_once()

    def testOnlyWin10AcrylicIsSuspendedDuringAMove(self):
        for isWin10, effect, expected in (
            (True, "Acrylic", True),
            (True, "Aero", False),
            (True, "Mica", False),
            (False, "Acrylic", False),
        ):
            with (
                self.subTest(isWin10=isWin10, effect=effect),
                patch.object(background_effect, "isWin10", return_value=isWin10),
            ):
                self.assertEqual(suspendsAcrylicDuringMove(effect), expected)


class MainWindowBackgroundEffectTest(TestCase):
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
        self.window.resize(1000, 700)
        self.window.move(100, 100)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.hide()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def _onWindows(self):
        """Run the main window's Windows branch with the window effects recorded."""
        windows = patch("app.view.windows.main_window.sys", SimpleNamespace(platform="win32"))
        apply = patch("app.view.windows.main_window.applyBackgroundEffect")
        windows.start()
        self.addCleanup(windows.stop)
        recorded = apply.start()
        self.addCleanup(apply.stop)
        return recorded

    def _onWin10(self):
        win10 = patch.object(background_effect, "isWin10", return_value=True)
        win10.start()
        self.addCleanup(win10.stop)
        suspend = patch("app.view.windows.main_window.suspendAcrylic")
        recorded = suspend.start()
        self.addCleanup(suspend.stop)
        return recorded

    def testChoosingAnEffectAppliesItAtOnceAndClearsTheWindowBackground(self):
        apply = self._onWindows()

        cfg.set(cfg.backgroundEffect, "Acrylic")

        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[:2], (self.window, "Acrylic"))
        self.assertEqual(self.window.backgroundColor, QColor(0, 0, 0, 0))

        cfg.set(cfg.backgroundEffect, "None")

        self.assertEqual(apply.call_args.args[:2], (self.window, "None"))
        self.assertEqual(self.window.backgroundColor.alpha(), 255)

    def testWin10MicaStillLeavesTheWindowBackgroundTransparent(self):
        cfg.set(cfg.backgroundEffect, "None")
        self._onWindows()
        self._onWin10()

        cfg.set(cfg.backgroundEffect, "Mica")

        self.assertEqual(self.window.backgroundColor, QColor(0, 0, 0, 0))

    def testThemeChangeReappliesTheEffectInTheNewTheme(self):
        cfg.set(cfg.backgroundEffect, "Acrylic")
        apply = self._onWindows()

        with patch("app.view.windows.main_window.isDarkTheme", return_value=True):
            qconfig.themeChangedFinished.emit()

        apply.assert_called_once_with(self.window, "Acrylic", True, True)

    def testShowingTheWindowAgainReappliesTheEffect(self):
        self.window.hide()
        cfg.set(cfg.backgroundEffect, "MicaAlt")
        apply = self._onWindows()

        with patch.object(self.window, "windowEffect", create=True):
            self.window.show()
            self.app.processEvents()

        self.assertEqual(apply.call_args.args[:2], (self.window, "MicaAlt"))
        # 显示时与 Ghost 一样不先移除，直接在现有效果上重新设置。
        self.assertFalse(apply.call_args.args[3])

    def _sizeMove(self, message):
        with (
            patch("app.view.windows.main_window.sys", SimpleNamespace(platform="win32")),
            patch("app.view.windows.main_window.MSG", create=True) as nativeMessage,
            patch("app.view.windows.main_window.win32con", SIZE_MOVE, create=True),
            patch.object(MSFluentWindow, "nativeEvent", return_value=(False, 0)),
        ):
            nativeMessage.from_address.return_value = SimpleNamespace(message=message)
            return self.window.nativeEvent(b"windows_generic_MSG", 1)

    def testWin10AcrylicDropsTheBlurWhileTheSystemMovesTheWindow(self):
        cfg.set(cfg.backgroundEffect, "Acrylic")
        apply = self._onWindows()
        suspend = self._onWin10()

        self.assertEqual(self._sizeMove(SIZE_MOVE.WM_ENTERSIZEMOVE), (False, 0))
        suspend.assert_called_once_with(self.window)
        apply.assert_not_called()

        self.assertEqual(self._sizeMove(SIZE_MOVE.WM_EXITSIZEMOVE), (False, 0))
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[:2], (self.window, "Acrylic"))
        self.assertEqual(apply.call_args.kwargs, {"removeFirst": False})

    def testOtherEffectsKeepTheirMaterialWhileTheWindowMoves(self):
        cfg.set(cfg.backgroundEffect, "Aero")
        apply = self._onWindows()
        suspend = self._onWin10()

        self._sizeMove(SIZE_MOVE.WM_ENTERSIZEMOVE)
        self._sizeMove(SIZE_MOVE.WM_EXITSIZEMOVE)

        suspend.assert_not_called()
        apply.assert_not_called()

    def testWin10AcrylicDropsTheBlurWhileAFingerDragsTheTitleBar(self):
        cfg.set(cfg.backgroundEffect, "Acrylic")
        apply = self._onWindows()
        suspend = self._onWin10()
        titleBar = self.window.titleBar
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = titleBar.mapToGlobal(QPoint(titleBar.width() // 2, titleBar.height() // 2))

        def touch(action, globalPoint):
            local = titleBar.mapFromGlobal(globalPoint)
            getattr(QTest.touchEvent(titleBar, device), action)(0, local, titleBar).commit()
            self.app.processEvents()

        touch("press", start)
        for step in range(1, 4):
            touch("move", start + QPoint(40, 30) * step)
        suspend.assert_called_once_with(self.window)
        apply.assert_not_called()

        touch("release", start + QPoint(120, 90))
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[:2], (self.window, "Acrylic"))
        self.assertEqual(apply.call_args.kwargs, {"removeFirst": False})
