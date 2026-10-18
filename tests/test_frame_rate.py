from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QVariantAnimation, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from app.config.cfg import cfg
from app.view.components import frame_rate
from app.view.components.frame_rate import (
    FrameRateLabel,
    setFrameRateShown,
    trackFrameRate,
)
from tests.support import isolateCfg

# 测试里每 200 ms 数一次，换算成每秒。
SAMPLE_MS = 200


def _label(window):
    return window.findChild(
        FrameRateLabel, options=Qt.FindChildOption.FindDirectChildrenOnly
    )


class _FrameRateTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.addCleanup(setFrameRateShown, frame_rate.isFrameRateShown())
        interval = patch.object(frame_rate, "SAMPLE_INTERVAL_MS", SAMPLE_MS)
        interval.start()
        self.addCleanup(interval.stop)

    def _window(self):
        window = QWidget()
        window.resize(400, 300)
        trackFrameRate(window)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()
        return window

    def _samples(self, window, count):
        texts = []
        for _ in range(count):
            QTest.qWait(SAMPLE_MS)
            texts.append(_label(window).text())
        return texts


class FrameRateSwitchTest(_FrameRateTest):
    def testOffUntilSwitchedOnThenEveryTrackedWindowGetsOneLabel(self):
        setFrameRateShown(False)
        window = self._window()
        self.assertIsNone(_label(window))

        setFrameRateShown(True)
        later = self._window()
        for each in (window, later):
            label = _label(each)
            self.assertIsNotNone(label)
            self.assertTrue(label.isVisible())
            self.assertEqual(label.pos(), QPoint(8, 8))

        setFrameRateShown(True)
        self.assertEqual(len(window.findChildren(FrameRateLabel)), 1)

        setFrameRateShown(False)
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertIsNone(_label(window))
        self.assertIsNone(_label(later))

        # 关了又立刻开，旧标签还没删掉也要换上新的。
        setFrameRateShown(True)
        setFrameRateShown(False)
        setFrameRateShown(True)
        self.assertIsNotNone(_label(window))
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(len(window.findChildren(FrameRateLabel)), 1)

    def testLabelSitsInTheVisibleCardAndLetsTouchesThrough(self):
        setFrameRateShown(True)
        window = self._window()
        button = QLabel("下面的控件", window)
        button.setGeometry(0, 0, 200, 60)
        button.show()
        window.setContentsMargins(12, 12, 12, 12)
        self.app.processEvents()

        label = _label(window)
        self.assertEqual(label.pos(), QPoint(20, 20))
        self.assertTrue(
            label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        )
        self.assertIs(window.childAt(label.geometry().center()), button)

    def testStaysAboveWidgetsAddedLaterSuchAsMaskDialogs(self):
        setFrameRateShown(True)
        window = self._window()
        mask = QWidget(window)
        mask.setGeometry(window.rect())
        mask.show()
        self.app.processEvents()

        widgets = [child for child in window.children() if child.isWidgetType()]
        self.assertIs(widgets[-1], _label(window))

    def testWidthHoldsStillWhileTheNumberChanges(self):
        setFrameRateShown(True)
        label = _label(self._window())
        width = label.width()

        for frames in (0, 7, 60, 144, 999):
            with self.subTest(frames=frames):
                label._setFramesPerSecond(frames)
                self.assertEqual(label.text(), f"{frames} FPS")
                self.assertEqual(label.width(), width)
                self.assertGreaterEqual(
                    width, label.fontMetrics().horizontalAdvance("999 FPS")
                )


class FrameRateCountTest(_FrameRateTest):
    def testIdleWindowReadsZeroAndItsOwnLabelDoesNotCount(self):
        setFrameRateShown(True)
        window = self._window()
        # 窗口显示时那一下是真的重画，等它数过去。
        QTest.qWait(2 * SAMPLE_MS)
        _label(window)._setFramesPerSecond(37)

        # 标签换数字自己也要重画一次；那一次不算，静止的窗口才稳在 0。
        self.assertEqual(self._samples(window, 5)[1:], ["0 FPS"] * 4)

    def testAnimatingWindowCountsItsRepaintsPerSecond(self):
        setFrameRateShown(True)
        window = self._window()
        moving = QLabel(window)
        moving.setGeometry(100, 100, 120, 30)
        moving.show()
        animation = QVariantAnimation(window)
        animation.setStartValue(0)
        animation.setEndValue(10_000)
        animation.setDuration(3 * SAMPLE_MS)
        animation.valueChanged.connect(lambda value: moving.setText(str(value)))
        animation.start()

        frames = int(self._samples(window, 2)[-1].split()[0])

        # 16 ms 一次的动画约 60 次每秒；开着超级帧率优化时更多。
        self.assertGreater(frames, 30)


class FrameRateWindowsTest(TestCase):
    """Main window, Projection, Exam Countdown and Fullscreen Clock carry the label."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.windowTransitionEnabled, False, save=False)
        self.addCleanup(setFrameRateShown, frame_rate.isFrameRateShown())
        setFrameRateShown(True)

    def _assertLabelled(self, window):
        window.show()
        self.addCleanup(window.close)
        self.app.processEvents()
        label = _label(window)
        self.assertIsNotNone(label)
        for _ in range(2):
            # 窗口化时阴影留白不算，标签落在可见卡片的角上；切回全屏跟着回去。
            self.assertEqual(
                label.pos(), window.contentsRect().topLeft() + QPoint(8, 8)
            )
            window.toggleWindowMode()
            self.app.processEvents()
        window.toggleWindowMode()
        self.app.processEvents()
        self.assertTrue(window.isWindowed)
        self.assertGreater(window.contentsRect().left(), 0)
        self.assertEqual(label.pos(), window.contentsRect().topLeft() + QPoint(8, 8))

    def testDisplayWindows(self):
        from app.view.pages.broadcast_page import BroadcastWindow
        from app.view.pages.countdown_page import CountdownWindow
        from app.view.pages.fullscreen_clock import FullscreenClockWindow

        for windowClass in (BroadcastWindow, CountdownWindow, FullscreenClockWindow):
            with self.subTest(window=windowClass.__name__):
                self._assertLabelled(windowClass())
