from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from app.view.components.scroll_area import (
    OVERLAY_SCROLL_BAR_WIDTH,
    ScrollArea,
    refreshOpaqueScrolling,
)


class _Backdrop(QWidget):
    """A window painting what MainWindow and its page panel paint behind a page."""

    def __init__(self, base=QColor(240, 244, 249), gradient=False, translucent=False):
        super().__init__()
        self.base = base
        self.gradient = gradient
        # 主窗口挂了 Background Effect 时是透明窗口，底色画成全透明。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.gradient:
            fill = QLinearGradient(0, 0, 0, self.height())
            fill.setColorAt(0, QColor("white"))
            fill.setColorAt(1, QColor("black"))
            painter.fillRect(self.rect(), fill)
        else:
            painter.fillRect(self.rect(), self.base)
        painter.fillRect(self.rect(), QColor(255, 255, 255, 128))


class _PaintCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


class OpaqueScrollingTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def _window(self, opaque, **backdrop):
        window = _Backdrop(**backdrop)
        self.addCleanup(window.deleteLater)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(20, 20, 20, 20)
        area = ScrollArea(window)
        content = QWidget()
        contentLayout = QVBoxLayout(content)
        contentLayout.setContentsMargins(11, 4, 20, 36)
        labels = []
        for index in range(60):
            label = QLabel(f"第 {index} 行设置", content)
            label.setStyleSheet("background: rgba(255, 255, 255, 170); border: 1px solid #ccc;")
            contentLayout.addWidget(label)
            labels.append(label)
        area.setWidget(content)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.enableTransparentBackground()
        if opaque:
            area.enableOpaqueScrolling()
        layout.addWidget(area)
        window.resize(420, 300)
        window.show()
        self.app.processEvents()
        return window, area, labels

    def testOpaqueAreaLooksExactlyLikeATransparentOne(self):
        plain, plainArea, _ = self._window(opaque=False)
        opaque, opaqueArea, _ = self._window(opaque=True)
        self.assertEqual(opaque.grab().toImage(), plain.grab().toImage())

        for area in (plainArea, opaqueArea):
            bar = area.verticalScrollBar()
            for value in range(0, bar.maximum() // 2, 7):
                bar.setValue(value)
                self.app.processEvents()

        self.assertEqual(opaque.grab().toImage(), plain.grab().toImage())

    def testContentGivesTheScrollBarStripBackFromItsRightMargin(self):
        _, area, _ = self._window(opaque=True)

        self.assertEqual(area.viewportMargins().right(), OVERLAY_SCROLL_BAR_WIDTH)
        self.assertEqual(
            area.widget().layout().contentsMargins().right(),
            20 - OVERLAY_SCROLL_BAR_WIDTH,
        )
        bar = area.delegate.vScrollBar
        self.assertGreaterEqual(bar.x(), area.viewport().geometry().right() + 1)

    def testScrollingRepaintsOnlyTheExposedStrip(self):
        counts = {}
        for opaque in (False, True):
            _, area, labels = self._window(opaque=opaque)
            counter = _PaintCounter()
            for label in labels:
                label.installEventFilter(counter)
            bar = area.verticalScrollBar()
            for value in range(3, 63, 3):
                bar.setValue(value)
                self.app.processEvents()
            counts[opaque] = counter.count

        # 透明时每一步都要重画视口里的所有行；不透明时只补画新露出来的一两行。
        self.assertLess(counts[True] * 4, counts[False])

    def testBackdropThatIsNotOneSolidColourStaysTransparent(self):
        _, gradient, _ = self._window(opaque=True, gradient=True)
        _, translucent, _ = self._window(
            opaque=True, base=QColor(0, 0, 0, 0), translucent=True
        )

        for area in (gradient, translucent):
            self.assertIsNone(area._backdropPainter.color)
            self.assertFalse(
                area.widget().testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
            )

    def testHiddenAreaGoesBackToTransparentWhenTheBackdropChanges(self):
        window, area, _ = self._window(opaque=True)
        self.assertEqual(area._backdropPainter.color, QColor(248, 250, 252))

        area.hide()
        window.base = QColor(32, 32, 32)
        refreshOpaqueScrolling()
        self.assertIsNone(area._backdropPainter.color)

        area.show()
        self.app.processEvents()
        self.assertEqual(area._backdropPainter.color, QColor(144, 144, 144))

    def _scrollWithTheWheelBar(self, area, value, ratio):
        with patch.object(area, "devicePixelRatioF", return_value=ratio):
            area.delegate.vScrollBar.setValue(value, useAni=False)
        return area.verticalScrollBar().value()

    def testWheelScrollingMovesByWholeDevicePixels(self):
        # Qt 只在位移是整物理像素时平移像素（QBackingStore::scroll），否则整块重画。
        _, area, _ = self._window(opaque=True)

        self.assertEqual(self._scrollWithTheWheelBar(area, 7, 1.25), 4)
        self.assertEqual(self._scrollWithTheWheelBar(area, 11, 1.5), 10)
        self.assertEqual(self._scrollWithTheWheelBar(area, 15, 1.75), 12)
        self.assertEqual(self._scrollWithTheWheelBar(area, 21, 2.0), 21)
        self.assertEqual(self._scrollWithTheWheelBar(area, 23, 3.0), 23)

    def testWheelScrollingStillReachesTheEnd(self):
        _, area, _ = self._window(opaque=True)
        maximum = area.verticalScrollBar().maximum()
        self.assertNotEqual(maximum % 4, 0)

        self.assertEqual(self._scrollWithTheWheelBar(area, maximum, 1.25), maximum)

    def testTouchAndTransparentAreasKeepEveryPixel(self):
        _, opaque, _ = self._window(opaque=True)
        _, plain, _ = self._window(opaque=False)

        # 触控（QScroller）直接设原生滚动条，不对齐，手指下的内容才跟得住手指。
        with patch.object(opaque, "devicePixelRatioF", return_value=1.25):
            opaque.verticalScrollBar().setValue(7)
        self.assertEqual(opaque.verticalScrollBar().value(), 7)
        self.assertEqual(self._scrollWithTheWheelBar(plain, 7, 1.25), 7)
