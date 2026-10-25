import time
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QScroller,
    QScrollerProperties,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.view.components import scroll_area
from app.view.components.scroll_area import (
    SUPPRESSED_DRAG_START_DISTANCE,
    ScrollArea,
    setTouchScrollSuppressed,
    setTunedTouchScrollEnabled,
    trackTouchScroller,
)

Metric = QScrollerProperties.ScrollMetric
_COMPARED = [
    metric
    for metric in Metric
    if metric not in (Metric.ScrollMetricCount, Metric.ScrollingCurve)
]


def _metrics(viewport):
    properties = QScroller.scroller(viewport).scrollerProperties()
    return {metric: properties.scrollMetric(metric) for metric in _COMPARED}


class _Feel(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.addCleanup(setTunedTouchScrollEnabled, scroll_area.isTunedTouchScrollEnabled())
        setTunedTouchScrollEnabled(False)

    def _scrollArea(self, target=None):
        scroll = ScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
        if target is not None:
            layout.addWidget(target)
        for index in range(20):
            layout.addWidget(QPushButton(str(index)))
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.resize(320, 240)
        scroll.show()
        self.addCleanup(scroll.deleteLater)
        self.app.processEvents()
        return scroll


class TouchScrollFeelTest(_Feel):
    def testOffIsExactlyQtsDefaultFeel(self):
        scroll = self._scrollArea()
        defaults = QScrollerProperties()

        self.assertEqual(
            _metrics(scroll.viewport()),
            {metric: defaults.scrollMetric(metric) for metric in _COMPARED},
        )

    def testOnFlingsFurtherForFasterSwipesAndBouncesBriefly(self):
        scroll = self._scrollArea()
        setTunedTouchScrollEnabled(True)
        metrics = _metrics(scroll.viewport())

        self.assertEqual(metrics[Metric.MaximumVelocity], 3.0)
        self.assertEqual(metrics[Metric.OvershootScrollTime], 0.3)
        self.assertGreater(metrics[Metric.DecelerationFactor], 0.125)
        pixelsPerMeter = QScroller.scroller(scroll.viewport()).pixelPerMeter().y()
        pixels = metrics[Metric.DragStartDistance] * pixelsPerMeter
        low, high = scroll_area.TUNED_DRAG_START_PIXELS
        self.assertGreaterEqual(pixels, low - 1e-6)
        self.assertLessEqual(pixels, high + 1e-6)

    def testSwitchingReachesViewportsThatAlreadyExist(self):
        scroll = self._scrollArea()
        edit = QTextEdit()
        self.addCleanup(edit.deleteLater)
        QScroller.grabGesture(edit.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        trackTouchScroller(edit.viewport())

        setTunedTouchScrollEnabled(True)
        for viewport in (scroll.viewport(), edit.viewport()):
            self.assertEqual(_metrics(viewport)[Metric.MaximumVelocity], 3.0)

        setTunedTouchScrollEnabled(False)
        for viewport in (scroll.viewport(), edit.viewport()):
            self.assertEqual(
                _metrics(viewport)[Metric.MaximumVelocity],
                QScrollerProperties().scrollMetric(Metric.MaximumVelocity),
            )

    def testSuppressedScrollStaysSuppressedAndComesBackWithTheCurrentFeel(self):
        scroll = self._scrollArea()
        scroll.setTouchScrollSuppressed(True)

        setTunedTouchScrollEnabled(True)
        self.assertEqual(
            _metrics(scroll.viewport())[Metric.DragStartDistance],
            SUPPRESSED_DRAG_START_DISTANCE,
        )

        scroll.setTouchScrollSuppressed(False)
        tuned = scroll_area._profileProperties(QScroller.scroller(scroll.viewport()))
        self.assertEqual(
            _metrics(scroll.viewport())[Metric.DragStartDistance],
            tuned.scrollMetric(Metric.DragStartDistance),
        )

    def testUntrackedViewportStillGetsItsOwnThresholdBack(self):
        edit = QTextEdit()
        self.addCleanup(edit.deleteLater)
        viewport = edit.viewport()
        QScroller.grabGesture(viewport, QScroller.ScrollerGestureType.TouchGesture)
        properties = QScroller.scroller(viewport).scrollerProperties()
        properties.setScrollMetric(Metric.DragStartDistance, 0.004)
        QScroller.scroller(viewport).setScrollerProperties(properties)

        restore = setTouchScrollSuppressed(viewport, True)
        setTouchScrollSuppressed(viewport, False, restore)

        self.assertAlmostEqual(_metrics(viewport)[Metric.DragStartDistance], 0.004)


class TapOrScrollTest(_Feel):
    """With the tuned feel a touch counts as a tap until the page itself moves."""

    def _press(self, scroll, button, distance):
        viewport = scroll.viewport()
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = button.mapTo(viewport, button.rect().center())
        QTest.touchEvent(viewport, device).press(0, start, viewport).commit()
        self.app.processEvents()
        for step in range(1, distance + 1):
            QTest.qWait(8)
            QTest.touchEvent(viewport, device).move(
                0, start + QPoint(0, -step), viewport
            ).commit()
            self.app.processEvents()
        QTest.touchEvent(viewport, device).release(
            0, start + QPoint(0, -distance), viewport
        ).commit()
        self.app.processEvents()
        scroller = QScroller.scroller(viewport)
        deadline = time.monotonic() + 3
        while scroller.state() != QScroller.State.Inactive and time.monotonic() < deadline:
            QTest.qWait(20)

    def _clicks(self, tuned, distance):
        button = QPushButton("打开")
        button.setFixedHeight(80)
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        scroll = self._scrollArea(button)
        setTunedTouchScrollEnabled(tuned)
        self._press(scroll, button, distance)
        return clicks, scroll, button

    @patch.object(scroll_area, "TUNED_DRAG_START_PIXELS", (14.0, 14.0))
    def testWobbleThatDoesNotMoveThePageStillClicks(self):
        wobble = QApplication.startDragDistance() + 2
        self.assertLess(wobble, 14)

        tunedClicks, tunedScroll, _ = self._clicks(tuned=True, distance=wobble)
        oldClicks, _, _ = self._clicks(tuned=False, distance=wobble)

        self.assertEqual(tunedScroll.verticalScrollBar().value(), 0)
        self.assertEqual(tunedClicks, [True])
        # 原来的规则按 startDragDistance 取消，同样的抖动点不开。
        self.assertEqual(oldClicks, [])

    @patch.object(scroll_area, "TUNED_DRAG_START_PIXELS", (14.0, 14.0))
    def testMovingThePageCancelsThePress(self):
        clicks, scroll, button = self._clicks(tuned=True, distance=60)

        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertEqual(clicks, [])
        self.assertFalse(button.isDown())


class ReleaseBeforeDestroyTest(_Feel):
    def testEveryGrabbedViewportIsReleasedOnceAndStopped(self):
        page = QWidget()
        self.addCleanup(page.deleteLater)
        layout = QVBoxLayout(page)
        grabbed = [ScrollArea(page), ScrollArea(page)]
        neverShown = ScrollArea(page, grabTouch=False)
        for area in (*grabbed, neverShown):
            layout.addWidget(area)
        text = QTextEdit(page)
        layout.addWidget(text)
        QScroller.grabGesture(text.viewport(), QScroller.ScrollerGestureType.TouchGesture)

        with (
            patch.object(QScroller, "ungrabGesture") as ungrab,
            patch.object(QScroller, "stop", autospec=True) as stop,
        ):
            scroll_area.releaseTouchGestures(page)

        released = [area.viewport() for area in grabbed] + [text.viewport()]
        self.assertCountEqual([call.args[0] for call in ungrab.call_args_list], released)
        self.assertEqual(stop.call_count, len(released))
        # 从没抓过的滚动区不碰，免得为它凭空建出一个 scroller。
        self.assertFalse(QScroller.hasScroller(neverShown.viewport()))
