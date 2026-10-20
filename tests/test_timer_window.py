from unittest import TestCase

from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.pages.countdown_page import CountdownWindow
from app.view.pages.fullscreen_clock import FullscreenClockWindow
from tests.support import isolateCfg


class TimerWindowLayoutTest(TestCase):
    """Exam Countdown 的标题和时间与 Fullscreen Clock 在同一处、同样大。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.windowTransitionEnabled, False, save=False)
        cfg.set(cfg.fullscreenClockStartWindowed, False, save=False)
        self.countdown = CountdownWindow()
        self.clock = FullscreenClockWindow()
        self.addCleanup(self.clock.close)
        self.addCleanup(self.countdown.close)
        self.countdown.startCountdown("考试倒计时", 2 * 3600, False)
        self.clock.startClock()
        self._settle()

    def _settle(self):
        for _ in range(5):
            self.app.processEvents()

    def _layout(self, window):
        return {
            "contents": window.contentsRect().getRect(),
            "title": window.titleLabel.geometry().getRect()
            if window.titleLabel.isVisible()
            else None,
            "time": window.timeLabel.geometry().getRect(),
            "font": window.timeLabel.font().pixelSize(),
        }

    def _toggleBoth(self):
        self.countdown.toggleWindowMode()
        self.clock.toggleWindowMode()
        self._settle()

    def testFullscreenTitleAndTimeMatchTheClock(self):
        self.assertFalse(self.countdown.isWindowed)
        self.assertEqual(self._layout(self.countdown), self._layout(self.clock))

    def testWindowedTimeMatchesTheClock(self):
        self._toggleBoth()

        self.assertTrue(self.countdown.isWindowed)
        self.assertTrue(self.clock.isWindowed)
        self.assertEqual(self._layout(self.countdown), self._layout(self.clock))

    def testCountdownControlsFloatUnderTheTime(self):
        # 来回切一次，时间换了位置和字号，控制也要跟过去。
        self._toggleBoth()
        self._toggleBoth()
        self.countdown._setControlsVisible(True, animated=False)
        self._settle()

        timeRect = self.countdown.timeLabel.geometry()
        controls = self.countdown.controlsWidget.geometry()
        self.assertEqual(controls.top(), timeRect.bottom() + 1)
        self.assertEqual(controls.center().x(), timeRect.center().x())
        self.assertEqual(self._layout(self.countdown), self._layout(self.clock))
