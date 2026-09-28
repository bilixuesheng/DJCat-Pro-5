import time
from unittest import TestCase

from PySide6.QtCore import QPoint
from PySide6.QtGui import QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QScroller,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CardWidget

from app.platform.application import TOUCH_PRESS_PLATFORM, withQtTouchPress
from app.view.components.scroll_area import ScrollArea


def testWindowsGetsQtTouchPressPlatform():
    argv = ["DJCat Pro.exe", "--silence"]

    arguments = withQtTouchPress(argv, platform="win32", environ={})

    assert arguments == [
        "DJCat Pro.exe",
        "--silence",
        "-platform",
        TOUCH_PRESS_PLATFORM,
    ]
    assert argv == ["DJCat Pro.exe", "--silence"]


def testExplicitPlatformIsLeftAlone():
    cases = [
        (["djcat.py"], {"QT_QPA_PLATFORM": "offscreen"}),
        (["djcat.py", "-platform", "offscreen"], {}),
        (["djcat.py", "--platform", "offscreen"], {}),
    ]
    for argv, environ in cases:
        assert withQtTouchPress(argv, platform="win32", environ=environ) == argv


def testOtherSystemsKeepTheirArguments():
    assert withQtTouchPress(["djcat.py"], platform="linux", environ={}) == [
        "djcat.py"
    ]


class TouchPressInScrollAreaTest(TestCase):
    """Offscreen Qt synthesizes mouse events from unaccepted touch, as Windows does
    once ``nomousefromtouch`` is set, so these cover the press path DJCat ships."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def _scrollArea(self, target):
        scroll = ScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
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

    def _dragUp(self, scroll, target, device, onStep):
        """Drag in viewport coordinates: the content scrolls with the finger, so
        the finger stays on ``target`` the whole way, as it does on a real screen."""
        viewport = scroll.viewport()
        start = target.mapTo(viewport, target.rect().center())
        QTest.touchEvent(viewport, device).press(0, start, viewport).commit()
        self.app.processEvents()
        onStep(0)
        for step in range(1, 7):
            QTest.qWait(16)
            QTest.touchEvent(viewport, device).move(
                0, start + QPoint(0, -12 * step), viewport
            ).commit()
            self.app.processEvents()
            onStep(step)
        QTest.touchEvent(viewport, device).release(
            0, start + QPoint(0, -72), viewport
        ).commit()
        scroller = QScroller.scroller(viewport)
        deadline = time.monotonic() + 3
        while (
            scroller.state() != QScroller.State.Inactive
            and time.monotonic() < deadline
        ):
            QTest.qWait(20)

    def testButtonIsPressedAsSoonAsTheFingerLands(self):
        button = QPushButton("打开")
        self._scrollArea(button)
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

        QTest.touchEvent(button, device).press(0, button.rect().center(), button).commit()
        self.app.processEvents()

        self.assertTrue(button.isDown())
        QTest.touchEvent(button, device).release(
            0, button.rect().center(), button
        ).commit()
        self.app.processEvents()

    def testScrollKeepsButtonReleasedWhileFingerStaysOnIt(self):
        button = QPushButton("打开")
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        scroll = self._scrollArea(button)
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

        def assertPressedUntilScrolling(step):
            with self.subTest(step=step):
                scrolling = 12 * step >= QApplication.startDragDistance()
                self.assertEqual(button.isDown(), not scrolling)

        self._dragUp(scroll, button, device, assertPressedUntilScrolling)

        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertEqual(clicks, [])
        self.assertFalse(button.isDown())

    def testScrollCancelsPressedCardWithoutClickingIt(self):
        card = CardWidget()
        card.setFixedHeight(80)
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))
        scroll = self._scrollArea(card)
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

        def assertPressedUntilScrolling(step):
            with self.subTest(step=step):
                scrolling = 12 * step >= QApplication.startDragDistance()
                self.assertEqual(card.isPressed, not scrolling)

        self._dragUp(scroll, card, device, assertPressedUntilScrolling)

        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertEqual(clicks, [])
        self.assertFalse(card.isPressed)
