from unittest import TestCase

from PySide6.QtCore import QEvent, QObject, QPoint, QTime
from PySide6.QtGui import QGuiApplication, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import LineEdit, MSFluentWindow, RoundMenu

from app.view.components.task_picker import TouchTimePicker

from app.platform.touch_input import enableTouchInput, enableTouchTitleBarDrag


def _holdInterval():
    return QGuiApplication.styleHints().mousePressAndHoldInterval()


class TouchLongPressTest(TestCase):
    """Offscreen Qt synthesizes left-button mouse events from touch, as Windows does
    under ``nomousefromtouch``; nothing there turns a held finger into a right click."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        enableTouchInput(cls.app)

    def setUp(self):
        self.device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        # offscreen 的空剪贴板 mimeData() 是 None，LineEdit 的右键菜单读它会出错。
        QApplication.clipboard().setText("粘贴")

    def _window(self, *widgets):
        window = QWidget()
        layout = QVBoxLayout(window)
        for widget in widgets:
            layout.addWidget(widget)
        window.resize(320, 200)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()
        return window

    def _closePopups(self):
        while (popup := QApplication.activePopupWidget()) is not None:
            popup.close()
            self.app.processEvents()

    def testHoldingStillOnTextBoxOpensItsMenu(self):
        edit = LineEdit()
        self._window(edit)
        self.addCleanup(self._closePopups)
        point = edit.rect().center()

        QTest.touchEvent(edit, self.device).press(0, point, edit).commit()
        QTest.qWait(_holdInterval() + 150)

        menu = QApplication.activePopupWidget()
        self.assertIsInstance(menu, RoundMenu)
        QTest.touchEvent(edit, self.device).release(0, point, edit).commit()
        QTest.qWait(50)
        self.assertIs(QApplication.activePopupWidget(), menu)

    def testMovingBeforeTheHoldEndsOpensNothing(self):
        edit = LineEdit()
        self._window(edit)
        self.addCleanup(self._closePopups)
        point = edit.rect().center()

        QTest.touchEvent(edit, self.device).press(0, point, edit).commit()
        QTest.qWait(50)
        QTest.touchEvent(edit, self.device).move(
            0, point + QPoint(QApplication.startDragDistance() + 5, 0), edit
        ).commit()
        QTest.qWait(_holdInterval() + 150)

        self.assertIsNone(QApplication.activePopupWidget())
        QTest.touchEvent(edit, self.device).release(0, point, edit).commit()
        self.app.processEvents()

    def testHoldingAButtonWithoutMenuStillClicksOnRelease(self):
        button = QPushButton("确定")
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        self._window(button)
        point = button.rect().center()

        QTest.touchEvent(button, self.device).press(0, point, button).commit()
        QTest.qWait(_holdInterval() + 150)
        QTest.touchEvent(button, self.device).release(0, point, button).commit()
        self.app.processEvents()

        self.assertIsNone(QApplication.activePopupWidget())
        self.assertEqual(clicks, [True])


class TouchTitleBarDragTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

    def _window(self):
        window = MSFluentWindow()
        enableTouchTitleBarDrag(window.titleBar)
        window.resize(500, 400)
        window.move(100, 100)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()
        return window

    def _touch(self, titleBar, action, globalPoint):
        """Keep the finger fixed on the screen while the window moves under it."""
        local = titleBar.mapFromGlobal(globalPoint)
        getattr(QTest.touchEvent(titleBar, self.device), action)(
            0, local, titleBar
        ).commit()
        self.app.processEvents()

    def _drag(self, window, delta):
        titleBar = window.titleBar
        start = titleBar.mapToGlobal(QPoint(titleBar.width() // 2, titleBar.height() // 2))
        self._touch(titleBar, "press", start)
        for step in range(1, 6):
            QTest.qWait(16)
            self._touch(titleBar, "move", start + delta * step / 5)
        self._touch(titleBar, "release", start + delta)
        return start + delta

    def testFingerDragOnTitleBarMovesTheWindow(self):
        window = self._window()
        before = window.pos()

        self._drag(window, QPoint(120, 80))

        self.assertEqual(window.pos(), before + QPoint(120, 80))

    def testTapOnTitleBarLeavesTheWindowInPlace(self):
        window = self._window()
        before = window.pos()

        self._drag(window, QPoint(1, 1))

        self.assertEqual(window.pos(), before)

    def testFingerDragRestoresMaximizedWindowUnderTheFinger(self):
        window = self._window()
        window.showMaximized()
        self.app.processEvents()
        self.assertTrue(window.isMaximized())

        finger = self._drag(window, QPoint(60, 120))

        self.assertFalse(window.isMaximized())
        self.assertEqual(window.width(), 500)
        # 按下时手指在最大化窗口正中，还原后仍应落在窗口宽度的正中。
        local = window.mapFromGlobal(finger)
        self.assertAlmostEqual(local.x(), window.width() / 2, delta=2)
        self.assertTrue(window.titleBar.geometry().contains(local))


class _SwallowRelease(QObject):
    """Stands in for the Windows path that loses the lift before the button sees it."""

    def __init__(self, button):
        super().__init__()
        self.button = button

    def eventFilter(self, obj, event):
        return obj is self.button and event.type() == QEvent.Type.MouseButtonRelease


class TouchPopupTapTest(TestCase):
    """On the touch screens a finger tap on the time picker's check mark lights it up
    and then does nothing; offscreen never reproduced why, so these simulate the ways
    the lift can go missing and require the tap to click exactly once regardless."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        enableTouchInput(cls.app)

    def setUp(self):
        self.device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

    def _openPanel(self):
        picker = TouchTimePicker(showSeconds=True)
        picker.setTime(QTime(6, 30, 30))
        picker.show()
        self.addCleanup(picker.deleteLater)
        self.app.processEvents()
        picker._showPanel()
        panel = QApplication.activePopupWidget()
        panel.ani.setCurrentTime(panel.ani.duration())
        self.app.processEvents()
        self.addCleanup(lambda: panel.isVisible() and panel.close())
        return panel

    def _tap(self, button, liftAt=None, afterPress=None):
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        press = button.rect().center()
        QTest.touchEvent(button, self.device).press(0, press, button).commit()
        self.app.processEvents()
        if afterPress is not None:
            afterPress()
        lift = press if liftAt is None else liftAt
        if lift != press:
            QTest.touchEvent(button, self.device).move(0, lift, button).commit()
            self.app.processEvents()
        QTest.touchEvent(button, self.device).release(0, lift, button).commit()
        QTest.qWait(50)
        return clicks

    def testNormalTapClicksOnce(self):
        panel = self._openPanel()

        self.assertEqual(self._tap(panel.yesButton), [True])

    def testTapClicksWhenTheLiftNeverReachesTheButton(self):
        panel = self._openPanel()
        swallow = _SwallowRelease(panel.yesButton)
        self.app.installEventFilter(swallow)
        self.addCleanup(self.app.removeEventFilter, swallow)

        self.assertEqual(self._tap(panel.yesButton), [True])

    def testTapClicksWhenTheButtonLostItsPressBeforeTheLift(self):
        panel = self._openPanel()

        clicks = self._tap(
            panel.cancelButton,
            afterPress=lambda: panel.cancelButton.setDown(False),
        )

        self.assertEqual(clicks, [True])

    def testSlidingOffTheButtonBeforeLiftingDoesNotClick(self):
        panel = self._openPanel()
        outside = QPoint(panel.yesButton.width() + 40, panel.yesButton.height() // 2)

        self.assertEqual(self._tap(panel.yesButton, liftAt=outside), [])
