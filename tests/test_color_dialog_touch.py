import time
from unittest import TestCase

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QColor, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QScroller,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import Slider

from app.view.components.color_dialog import ColorDialog
from app.view.components.scroll_area import (
    ScrollArea,
    _isTouchDragTarget,
    registerTouchDragTarget,
)


class _ReleaseRecorder(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.releases = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonRelease:
            self.releases += 1
        return False


class _TouchDragMixin:
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        cls.device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

    def _drag(self, scroll, start, delta, steps=7):
        """Drag in viewport coordinates, as a finger does on a real screen."""
        viewport = scroll.viewport()
        QTest.touchEvent(viewport, self.device).press(0, start, viewport).commit()
        self.app.processEvents()
        for step in range(1, steps + 1):
            QTest.qWait(16)
            QTest.touchEvent(viewport, self.device).move(
                0, start + delta * step, viewport
            ).commit()
            self.app.processEvents()
        QTest.touchEvent(viewport, self.device).release(
            0, start + delta * steps, viewport
        ).commit()
        scroller = QScroller.scroller(viewport)
        deadline = time.monotonic() + 3
        while (
            scroller.state() != QScroller.State.Inactive
            and time.monotonic() < deadline
        ):
            QTest.qWait(20)
        self.app.processEvents()


class ColorDialogTouchTest(_TouchDragMixin, TestCase):
    """A window short enough that the dialog content has to scroll."""

    def setUp(self):
        self.host = QWidget()
        self.host.resize(700, 520)
        self.host.show()
        self.addCleanup(self.host.deleteLater)

    def _openDialog(self, color=QColor(0, 120, 215)):
        dialog = ColorDialog(color, "选择颜色", self.host)
        dialog.show()
        QTest.qWait(50)
        self.addCleanup(dialog.deleteLater)
        scroll = dialog.scrollArea
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        return dialog, scroll

    def _at(self, dialog, widget, point):
        return widget.mapTo(dialog.scrollArea.viewport(), point)

    def testDragFromBlankSpaceScrollsTheContent(self):
        dialog, scroll = self._openDialog()
        start = self._at(dialog, dialog.scrollWidget, QPoint(400, 250))

        self._drag(scroll, start, QPoint(0, -12))

        self.assertGreater(scroll.verticalScrollBar().value(), 0)

    def testDragOnHuePanelPicksColorWithoutScrolling(self):
        dialog, scroll = self._openDialog()
        panel = dialog.huePanel
        hue = panel.hue
        start = self._at(dialog, panel, QPoint(40, 200))

        self._drag(scroll, start, QPoint(20, -12))

        self.assertEqual(scroll.verticalScrollBar().value(), 0)
        self.assertNotEqual(panel.hue, hue)
        self.assertFalse(scroll.isTouchScrollSuppressed)

    def testDragOnBrightnessSliderMovesItWithoutScrolling(self):
        dialog, scroll = self._openDialog()
        slider = dialog.brightSlider
        value = slider.value()
        start = self._at(dialog, slider, slider.rect().center())

        self._drag(scroll, start, QPoint(-8, -12))

        self.assertEqual(scroll.verticalScrollBar().value(), 0)
        self.assertNotEqual(slider.value(), value)
        self.assertFalse(slider.isSliderDown())

    def testDragFromLineEditScrollsWithoutReleasingIntoIt(self):
        dialog, scroll = self._openDialog()
        lineEdit = dialog.redLineEdit
        recorder = _ReleaseRecorder(lineEdit)
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        start = self._at(dialog, lineEdit, lineEdit.rect().center())

        self._drag(scroll, start, QPoint(0, 12))

        self.assertLess(
            scroll.verticalScrollBar().value(),
            scroll.verticalScrollBar().maximum(),
        )
        self.assertEqual(recorder.releases, 0)

    def testReopeningAfterCloseDoesNotCrash(self):
        for _ in range(3):
            dialog = ColorDialog(QColor(0, 120, 215), "选择颜色", self.host)
            dialog.show()
            QTest.qWait(20)
            dialog.done(0)
            dialog.done(0)
            QTest.qWait(150)
            dialog.deleteLater()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QWidget().deleteLater()


class SliderDragTargetTest(_TouchDragMixin, TestCase):
    def testRegisteredSliderOwnsTheDragInsideAScrollArea(self):
        scroll = ScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
        slider = Slider(Qt.Orientation.Horizontal, content)
        slider.setRange(0, 100)
        slider.setValue(50)
        registerTouchDragTarget(slider)
        layout.addWidget(slider)
        for index in range(20):
            layout.addWidget(QPushButton(str(index)))
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.resize(320, 240)
        scroll.show()
        self.addCleanup(scroll.deleteLater)
        self.app.processEvents()
        start = slider.mapTo(scroll.viewport(), slider.rect().center())

        self._drag(scroll, start, QPoint(-10, -12))

        self.assertEqual(scroll.verticalScrollBar().value(), 0)
        self.assertLess(slider.value(), 50)
        self.assertFalse(slider.isSliderDown())
        self.assertFalse(scroll.isTouchScrollSuppressed)

    def testPageSlidersAreRegistered(self):
        from app.view.pages.schedule_page import createTaskForm
        from app.view.pages.setting_page import SettingPage

        page = SettingPage()
        self.addCleanup(page.deleteLater)
        self.assertTrue(_isTouchDragTarget(page.bannerBrightnessCard.slider))

        host = QWidget()
        self.addCleanup(host.deleteLater)
        form, widgets = createTaskForm(host)
        self.assertTrue(_isTouchDragTarget(widgets["volumeSlider"]))
