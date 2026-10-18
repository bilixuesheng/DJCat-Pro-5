from unittest import TestCase

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleFactory
from qfluentwidgets import qconfig

from app.platform.touch_input import setTouchPressFeedbackEnabled
from app.view.components.window_background import closeButtonColors
from app.view.pages.broadcast_page import FloatingMiniWindow


def _iconBounds(image):
    xs, ys = [], []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if min(color.red(), color.green(), color.blue()) > 240 and color.alpha() > 200:
                xs.append(x)
                ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


class FloatingButtonTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def show(self):
        button = FloatingMiniWindow()
        self.addCleanup(button.deleteLater)
        self.addCleanup(button.hide)
        button.showAt(QPoint(100, 100))
        self.app.processEvents()
        return button

    def testIconStaysCentredWhilePressed(self):
        button = self.show()
        # Windows 上的样式把按下的工具按钮图标往右下挪一个像素，300% 下是三个物理像素。
        style = QStyleFactory.create("Windows")
        style.setParent(button)
        button.btn.setStyle(style)
        idle = button.btn.grab().toImage()

        button.btn.setDown(True)
        pressed = button.btn.grab().toImage()

        self.assertEqual(_iconBounds(pressed), _iconBounds(idle))
        theme = QColor(qconfig.themeColor.value)
        self.assertEqual(idle.pixelColor(8, 30).rgb(), theme.rgb())
        self.assertEqual(pressed.pixelColor(8, 30).rgb(), closeButtonColors().pressed.rgb())

    def testMouseLooksPressedUntilTheDragStarts(self):
        button = self.show()
        restores = []
        button.restoreSignal.connect(lambda: restores.append(True))
        centre = button.btn.rect().center()

        QTest.mousePress(button.btn, Qt.MouseButton.LeftButton, pos=centre)
        self.assertTrue(button.btn.isDown())
        self.assertEqual(button.windowOpacity(), 1.0)

        QTest.mouseMove(button.btn, centre + QPoint(20, 0))
        self.assertFalse(button.btn.isDown())
        QTest.mouseRelease(button.btn, Qt.MouseButton.LeftButton, pos=centre + QPoint(20, 0))

        self.assertFalse(button.btn.isDown())
        self.assertEqual(restores, [])

    def testFingerPressIsNeverLeftDown(self):
        previous = getattr(self.app, "_djcatTouchPressFeedback", None) is not None
        setTouchPressFeedbackEnabled(self.app, True)
        self.addCleanup(setTouchPressFeedbackEnabled, self.app, previous)
        touchScreen = QTest.createTouchDevice(
            QInputDevice.DeviceType.TouchScreen,
            QInputDevice.Capability.Position | QInputDevice.Capability.MouseEmulation,
        )
        button = self.show()
        restores = []
        button.restoreSignal.connect(lambda: restores.append(True))
        centre = button.btn.rect().center()

        QTest.touchEvent(button.btn, touchScreen).press(0, centre, button.btn).commit()
        self.app.processEvents()
        self.assertTrue(button.btn.isDown())
        self.assertEqual(button.windowOpacity(), 1.0)

        # Windows 自己的按下在手指还没抬起时就到了（手指稍微挪了一下）：按下态从此归按钮管，
        # 而按钮的按下和松开都被悬浮按钮吞掉，它得自己复位。
        QTest.mousePress(button.btn, Qt.MouseButton.LeftButton, pos=centre)
        QTest.mouseRelease(button.btn, Qt.MouseButton.LeftButton, pos=centre)
        QTest.touchEvent(button.btn, touchScreen).release(0, centre, button.btn).commit()
        self.app.processEvents()

        self.assertFalse(button.btn.isDown())
        self.assertEqual(restores, [True])
