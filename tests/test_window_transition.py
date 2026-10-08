import time
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QApplication
from qfluentwidgets import qconfig

from app.config.cfg import cfg
from app.view.components import window_transition
from app.view.components.window_transition import WindowTransition
from app.view.pages.broadcast_page import BroadcastWindow, FloatingMiniWindow
from app.view.pages.countdown_page import CountdownWindow
from app.view.pages.fullscreen_clock import FullscreenClockWindow
from tests.support import isolateCfg


def _worstDifference(expected: QImage, actual: QImage) -> int:
    worst = 0
    for y in range(expected.height()):
        for x in range(expected.width()):
            a, b = expected.pixelColor(x, y), actual.pixelColor(x, y)
            worst = max(
                worst,
                abs(a.red() - b.red()),
                abs(a.green() - b.green()),
                abs(a.blue() - b.blue()),
                abs(a.alpha() - b.alpha()),
            )
    return worst


class WindowTransitionTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.windowTransitionEnabled, True, save=False)
        cfg.set(cfg.showTaskbarInCountdown, False, save=False)
        cfg.set(cfg.showTaskbarInBroadcast, False, save=False)

    def pumpUntil(self, condition, message):
        deadline = time.monotonic() + 3
        while not condition():
            if time.monotonic() > deadline:
                self.fail(message)
            self.app.processEvents()
            time.sleep(0.002)

    def pumpUntilAnimating(self, transition):
        self.pumpUntil(
            lambda: transition._phase == window_transition._ANIMATING,
            "Window Transition never started animating",
        )

    def startCountdown(self):
        window = CountdownWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.startCountdown("期末考试", 3600, False)
        self.pumpUntil(lambda: window.geometry() == window.windowHandle().geometry(), "never fullscreen")
        return window

    def startBroadcast(self):
        window = BroadcastWindow()
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window.setContent("标题", "正文")
        window.startBroadcast()
        self.pumpUntil(lambda: window.geometry() == window.windowHandle().geometry(), "never fullscreen")
        return window

    def testANewTransitionNeverFlashesTheLastOnesFrame(self):
        window = self.startBroadcast()
        transition = window.transition
        window.toggleWindowMode()
        self.pumpUntil(lambda: not transition.isRunning(), "Window Transition never ended")
        window.move(window.pos() + QPoint(-150, -80))

        window.toggleWindowMode()

        # 透明层刚显示、还没重画时，屏幕上是它留着的那张位图（Windows 的透明窗口
        # 同样如此）：它不能还是上一次过渡的末帧，否则窗口在旧位置闪一下。
        overlay = transition._overlay
        onScreen = QGuiApplication.primaryScreen().grabWindow(overlay.winId()).toImage()
        leftovers = [
            (x, y)
            for y in range(0, onScreen.height(), 8)
            for x in range(0, onScreen.width(), 8)
            if onScreen.pixelColor(x, y).alpha()
        ]
        self.assertEqual(leftovers[:3], [])
        transition.finish()

    def testSwitchHappensUnderTheCoverAndWaitsForIt(self):
        window = self.startCountdown()
        transition = window.transition

        window.toggleWindowMode()

        # 动画层还没画到屏幕上之前，真窗口原样不动。
        self.assertTrue(transition.isRunning())
        self.assertFalse(window.isWindowed)
        self.assertEqual(window.windowOpacity(), 1.0)
        self.assertTrue(transition._overlay.isVisible())

        self.pumpUntilAnimating(transition)
        self.assertTrue(window.isWindowed)
        self.assertEqual(window.contentsRect().size().toTuple(), (600, 190))
        self.assertEqual(window.windowOpacity(), 0.0)

        window.toggleWindowMode()
        self.assertTrue(window.isWindowed)

        transition.finish()
        self.assertFalse(transition.isRunning())
        self.assertFalse(transition._overlay.isVisible())
        self.assertEqual(window.windowOpacity(), 1.0)

    def testBothEndsOfTheMorphMatchTheRealWindow(self):
        for windowType in (CountdownWindow, FullscreenClockWindow, BroadcastWindow):
            with self.subTest(window=windowType.__name__):
                if windowType is CountdownWindow:
                    window = self.startCountdown()
                elif windowType is BroadcastWindow:
                    window = self.startBroadcast()
                else:
                    window = windowType()
                    self.addCleanup(window.deleteLater)
                    self.addCleanup(window.close)
                    window.startClock()
                    self.pumpUntil(
                        lambda: window.geometry() == window.windowHandle().geometry(),
                        "never fullscreen",
                    )
                transition = window.transition
                fullscreen = window.grab().toImage()
                fullscreenRect = window.geometry()

                window.toggleWindowMode()
                self.pumpUntilAnimating(transition)
                overlay = transition._overlay
                source, target = overlay.source, overlay.target

                overlay.setFrame(source, target, 0.0)
                start = overlay.grab(fullscreenRect.translated(-overlay.pos())).toImage()
                self.assertLessEqual(_worstDifference(fullscreen, start), 2)

                overlay.setFrame(source, target, 1.0)
                end = overlay.grab(window.geometry().translated(-overlay.pos())).toImage()
                transition.finish()
                windowed = window.grab().toImage()
                self.assertLessEqual(_worstDifference(windowed, end), 4)

    def testMidwayFrameIsARoundedCardBetweenTheEnds(self):
        window = self.startCountdown()
        transition = window.transition
        window.toggleWindowMode()
        self.pumpUntilAnimating(transition)
        overlay = transition._overlay

        overlay.setFrame(overlay.source, overlay.target, 0.5)
        rect, radius, shadow, opacity = overlay.frame()

        source, target = overlay.source.rect, overlay.target.rect
        self.assertAlmostEqual(rect.width(), (source.width() + target.width()) / 2)
        self.assertAlmostEqual(rect.height(), (source.height() + target.height()) / 2)
        self.assertAlmostEqual(radius, 4)
        self.assertAlmostEqual(shadow, 0.5)
        self.assertEqual(opacity, 1.0)
        image = overlay.grab().toImage()
        self.assertEqual(image.pixelColor(rect.center().toPoint()).alpha(), 255)
        self.assertLess(image.pixelColor(rect.topLeft().toPoint()).alpha(), 255)
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        transition.finish()

    def testCollapseMorphsIntoTheFloatingButton(self):
        window = self.startBroadcast()
        transition = window.transition
        button = window.miniWindow

        window.minimizeToMini()
        self.assertTrue(window.isVisible())
        self.pumpUntilAnimating(transition)

        self.assertFalse(window.isVisible())
        self.assertTrue(button.isVisible())
        self.assertEqual(button.windowOpacity(), 0.0)
        overlay = transition._overlay
        self.assertEqual(overlay.target.rect.toRect(), button.geometry())

        overlay.setFrame(overlay.source, overlay.target, 1.0)
        rect, radius, shadow, opacity = overlay.frame()
        self.assertEqual(radius, button.width() / 2)
        self.assertEqual(shadow, 0.0)
        self.assertAlmostEqual(opacity, FloatingMiniWindow.IDLE_OPACITY, delta=0.01)
        image = overlay.grab().toImage()
        fill = image.pixelColor(rect.left() + 8, rect.center().y())
        theme = QColor(qconfig.themeColor.value)
        self.assertAlmostEqual(fill.alpha(), 128, delta=2)
        for got, want in ((fill.red(), theme.red()), (fill.green(), theme.green()), (fill.blue(), theme.blue())):
            self.assertAlmostEqual(got, want, delta=3)
        self.assertEqual(image.pixelColor(rect.topLeft().toPoint()).alpha(), 0)

        transition.finish()
        self.assertAlmostEqual(button.windowOpacity(), FloatingMiniWindow.IDLE_OPACITY, delta=0.01)
        self.assertFalse(overlay.isVisible())

    def testRestoreExpandsFromWhereverTheFloatingButtonWasDragged(self):
        window = self.startBroadcast()
        window.toggleWindowMode()
        window.transition.finish()
        windowed = window.geometry()
        window.minimizeToMini()
        window.transition.finish()
        button = window.miniWindow
        button.move(button.pos() - QPoint(200, 100))

        window.restoreFromMini()
        transition = window.transition
        self.assertEqual(
            transition._source.rect.toRect(),
            QRect(button.pos(), button.size()),
        )
        self.pumpUntilAnimating(transition)

        self.assertFalse(button.isVisible())
        self.assertTrue(window.isVisible())
        self.assertTrue(window.isWindowed)
        self.assertEqual(window.geometry(), windowed)
        self.assertEqual(window.windowOpacity(), 0.0)
        transition.finish()
        self.assertEqual(window.windowOpacity(), 1.0)

    def testTurningTheSettingOffSwitchesInstantly(self):
        cfg.set(cfg.windowTransitionEnabled, False, save=False)
        window = self.startBroadcast()

        window.toggleWindowMode()
        self.assertTrue(window.isWindowed)
        window.minimizeToMini()

        self.assertFalse(window.transition.isRunning())
        self.assertIsNone(window.transition._overlay)
        self.assertFalse(window.isVisible())
        self.assertTrue(window.miniWindow.isVisible())
        self.assertAlmostEqual(
            window.miniWindow.windowOpacity(), FloatingMiniWindow.IDLE_OPACITY, delta=0.01
        )

    def testClosingMidTransitionDropsAPendingSwitchAndRestoresOpacity(self):
        window = self.startCountdown()
        window.toggleWindowMode()
        window.close()

        self.assertFalse(window.transition.isRunning())
        self.assertFalse(window.transition._overlay.isVisible())
        self.assertFalse(window.isWindowed)
        self.assertEqual(window.windowOpacity(), 1.0)

        window = self.startBroadcast()
        window.minimizeToMini()
        self.pumpUntilAnimating(window.transition)
        window.close()

        self.assertFalse(window.transition.isRunning())
        self.assertFalse(window.miniWindow.isVisible())
        self.assertFalse(window.transition._overlay.isVisible())

    def testRedrawsFollowTheScreenRefreshRate(self):
        transition = WindowTransition()
        self.addCleanup(transition.deleteLater)
        transition._ensureOverlay()
        with patch.object(window_transition, "screenFor") as screenFor:
            for rate, interval in ((60.0, 16), (144.0, 6), (0.0, 16)):
                with self.subTest(rate=rate):
                    screenFor.return_value.refreshRate.return_value = rate
                    self.assertEqual(transition._frameInterval(), interval)
