import math
from unittest import TestCase

from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.components.time_text import timeTextWidth
from app.view.pages.countdown_page import CountdownWindow
from app.view.pages.fullscreen_clock import FullscreenClockWindow
from tests.support import isolateCfg


class TimeTextTest(TestCase):
    """比例字体里 "1" 比 "0" 窄；走秒时只有变的那一格能变。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.windowTransitionEnabled, False, save=False)

    def _open(self, windowClass, width=720, height=240):
        window = windowClass()
        self.addCleanup(window.close)
        window.resize(width, height)
        window.show()
        self.app.processEvents()
        return window

    def _grabAll(self, window, setTime, values):
        label = window.timeLabel
        images, fonts = [], []
        for value in values:
            setTime(value)
            self.app.processEvents()
            images.append(label.grab().toImage())
            fonts.append(label.font().pixelSize())
        return images, fonts

    def _assertOnlyLastCellChanges(self, window, setTime, values):
        images, fonts = self._grabAll(window, setTime, values)
        self.assertEqual(len(set(fonts)), 1, fonts)

        label = window.timeLabel
        font = label.font()
        cell = max(QFontMetricsF(font).horizontalAdvance(digit) for digit in "0123456789")
        width = timeTextWidth(font, label.text())
        lastCellLeft = (label.width() + width) / 2 - cell
        # 最后一格左边的像素逐个相同；留 2 px 给抗锯齿。
        steady = math.floor(lastCellLeft) - 2
        self.assertGreater(steady, label.width() // 3)
        first = images[0].copy(0, 0, steady, images[0].height())
        for image in images[1:]:
            self.assertEqual(image.copy(0, 0, steady, image.height()), first)

    def testCountdownSecondsTickWithoutMovingTheRest(self):
        window = self._open(CountdownWindow)
        window.startCountdown("距离考试结束还剩", 3600, False)
        window.timer.stop()
        self.app.processEvents()

        def setRemaining(value):
            window.remaining = value
            window._refreshTime()

        for windowed in (False, True):
            with self.subTest(windowed=windowed):
                if window.isWindowed != windowed:
                    window.toggleWindowMode()
                    self.app.processEvents()
                self._assertOnlyLastCellChanges(window, setRemaining, (3610, 3611, 3618))

    def testCountdownPadsEveryFieldToTwoDigits(self):
        window = self._open(CountdownWindow)
        window.remaining = 45 * 60
        window._refreshTime()
        self.assertEqual(window.timeLabel.text(), "00 : 45 : 00")

    def testClockSecondsTickWithoutMovingTheRest(self):
        window = self._open(FullscreenClockWindow)
        window.startClock()
        window.timer.stop()
        self.app.processEvents()

        def setText(text):
            window.timeLabel.setText(text)
            window._applyFonts(window.contentsRect().height())

        self._assertOnlyLastCellChanges(
            window, setText, ("12 : 34 : 50", "12 : 34 : 51", "12 : 34 : 58")
        )

    def testFittedFontSizeIgnoresWhichDigitsAreShown(self):
        # 不调 startCountdown：它会铺满屏幕，大屏上字号不必缩，测不到什么。
        window = self._open(CountdownWindow, 320, 240)
        window.timeLabel.setText("00 : 00 : 00")
        window._applyFonts(window.contentsRect().height())
        self.assertLess(window.timeLabel.font().pixelSize(), 240 * 9 // 40)

        sizes = set()
        for value in (0, 11 * 3600 + 11 * 60 + 11, 20 * 3600 + 8 * 60 + 8):
            window.remaining = value
            window._refreshTime()
            window._applyFonts(window.contentsRect().height())
            sizes.add(window.timeLabel.font().pixelSize())
        self.assertEqual(len(sizes), 1, sizes)
