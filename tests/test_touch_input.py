from unittest import TestCase

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTime
from PySide6.QtGui import QInputDevice, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, LineEdit

from app.platform.touch_input import (
    enableTouchPressFeedback,
    setTouchPressFeedbackEnabled,
)
from app.view.components.task_picker import TouchTimePicker


def _windowsTouchScreen():
    """A touch screen as Windows reports it: Qt synthesizes no mouse events, because
    Windows sends its own once it has told a tap from a drag or a press-and-hold."""
    return QTest.createTouchDevice(
        QInputDevice.DeviceType.TouchScreen,
        QInputDevice.Capability.Position | QInputDevice.Capability.MouseEmulation,
    )


def _mousePress(pressType, widget, point):
    """Windows' own left press at point, as Qt hands it to the widget."""
    return QMouseEvent(
        pressType,
        QPointF(point),
        QPointF(widget.mapToGlobal(point)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class TouchPressFeedbackTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        enableTouchPressFeedback(cls.app)

    def setUp(self):
        self.device = _windowsTouchScreen()

    def _show(self, *widgets):
        window = QWidget()
        layout = QVBoxLayout(window)
        for widget in widgets:
            layout.addWidget(widget)
        window.resize(320, 240)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()
        return window

    def _press(self, widget, point=None):
        point = widget.rect().center() if point is None else point
        QTest.touchEvent(widget, self.device).press(0, point, widget).commit()
        self.app.processEvents()
        return point

    def _release(self, widget, point):
        QTest.touchEvent(widget, self.device).release(0, point, widget).commit()
        self.app.processEvents()

    def _clicks(self, button):
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        return clicks

    def testButtonLooksPressedWhileTheFingerIsDown(self):
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        self.assertTrue(button.isDown())
        self._release(button, point)

        self.assertFalse(button.isDown())
        self.assertEqual(clicks, [])

    def testWindowsTapAfterTheLiftClicksOnce(self):
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        self._release(button, point)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicks, [True])
        self.assertFalse(button.isDown())

    def testWindowsPressBeforeTheLiftKeepsTheButtonPressed(self):
        # 手指挪过轻点容差后 Windows 当场补发按下；抬手时不能再把按钮复位，否则
        # 随后到来的松开就点不中了。
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
        self._release(button, point)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicks, [True])

    def testBothTapsOfADoubleTapClick(self):
        # 连点的第二下 Qt 只给控件发双击、不发按下；它同样是 Windows 自己的按下，
        # 抬手时不能把按钮复位。
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        for pressType in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            point = self._press(button)
            QApplication.sendEvent(button, _mousePress(pressType, button, point))
            self._release(button, point)
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicks, [True, True])

    def testCardLooksPressedWhileTheFingerIsDown(self):
        card = CardWidget()
        card.setFixedHeight(80)
        self._show(card)

        point = self._press(card)
        self.assertTrue(card.isPressed)
        self._release(card, point)

        self.assertFalse(card.isPressed)

    def testPopupButtonLooksPressedWhileTheFingerIsDown(self):
        picker = TouchTimePicker(showSeconds=True)
        picker.setTime(QTime(6, 30, 30))
        self._show(picker)
        picker._showPanel()
        panel = QApplication.activePopupWidget()
        panel.ani.setCurrentTime(panel.ani.duration())
        self.app.processEvents()
        self.addCleanup(lambda: panel.isVisible() and panel.close())

        point = self._press(panel.yesButton)
        self.assertTrue(panel.yesButton.isDown())
        self._release(panel.yesButton, point)

        self.assertFalse(panel.yesButton.isDown())

    def testMovingTheFingerAwayDropsThePressedLook(self):
        button = QPushButton("确定")
        self._show(button)

        point = self._press(button)
        QTest.touchEvent(button, self.device).move(0, point + QPoint(0, 15), button).commit()
        self.app.processEvents()

        self.assertFalse(button.isDown())
        self._release(button, point + QPoint(0, 15))

    def testAutoRepeatButtonIsLeftAlone(self):
        button = QPushButton("+")
        button.setAutoRepeat(True)
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        QTest.qWait(button.autoRepeatDelay() + 2 * button.autoRepeatInterval())

        self.assertFalse(button.isDown())
        self.assertEqual(clicks, [])
        self._release(button, point)

    def testWidgetThatHandlesTouchKeepsItsButtonsToItself(self):
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        button = QPushButton("确定", host)
        button.resize(120, 40)
        self._show(host)

        point = self._press(button)

        self.assertFalse(button.isDown())
        self._release(button, point)

    def testHoldingInsideATextBoxKeepsTheSelection(self):
        edit = LineEdit()
        edit.setText("全屏投送标题")
        self._show(edit)
        edit.setSelection(2, 2)

        point = self._press(edit)
        QTest.qWait(300)
        self._release(edit, point)

        self.assertEqual(edit.selectedText(), "投送")


class TouchPressFeedbackSwitchTest(TestCase):
    """「新触控」默认开，可在开发人员选项里停用；停用时按住按钮与 Qt 原样相同，立即生效。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.addCleanup(enableTouchPressFeedback, self.app)
        self.button = QPushButton("确定")
        window = QWidget()
        QVBoxLayout(window).addWidget(self.button)
        window.resize(320, 240)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()

    def _pressedWhileFingerDown(self):
        device = _windowsTouchScreen()
        point = self.button.rect().center()
        QTest.touchEvent(self.button, device).press(0, point, self.button).commit()
        self.app.processEvents()
        pressed = self.button.isDown()
        QTest.touchEvent(self.button, device).release(0, point, self.button).commit()
        self.app.processEvents()
        return pressed

    def testSwitchingOffLeavesTheButtonToWindowsAndBackOnRestoresTheLook(self):
        setTouchPressFeedbackEnabled(self.app, False)
        self.assertFalse(self._pressedWhileFingerDown())

        setTouchPressFeedbackEnabled(self.app, True)
        self.assertTrue(self._pressedWhileFingerDown())
