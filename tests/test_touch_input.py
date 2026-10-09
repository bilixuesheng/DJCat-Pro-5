from unittest import TestCase

from PySide6.QtCore import QPoint, Qt, QTime
from PySide6.QtGui import QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, LineEdit

from app.platform.touch_input import enableTouchPressFeedback
from app.view.components.task_picker import TouchTimePicker


def _windowsTouchScreen():
    """A touch screen as Windows reports it: Qt synthesizes no mouse events, because
    Windows sends its own once it has told a tap from a drag or a press-and-hold."""
    return QTest.createTouchDevice(
        QInputDevice.DeviceType.TouchScreen,
        QInputDevice.Capability.Position | QInputDevice.Capability.MouseEmulation,
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
