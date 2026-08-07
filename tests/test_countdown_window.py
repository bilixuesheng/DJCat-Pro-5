import os
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.view.pages.countdown_page import CountdownWindow


class CountdownWindowTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = CountdownWindow()
        self.window.resize(720, 240)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()

    def testWindowedModeCollapsesInlineControls(self):
        self.window.is_windowed = True
        self.window._applyWindowState()
        self.app.processEvents()

        self.assertTrue(self.window.controlsWidget.isHidden())
        self.assertFalse(self.window.controlsWidget.isEnabled())
        self.assertFalse(self.window._controls_visible)

    def testWindowedBlankClickDoesNotRevealInlineControls(self):
        self.window.is_windowed = True
        self.window._applyWindowState()
        self.app.processEvents()

        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            pos=QPoint(20, 20),
        )
        self.app.processEvents()

        self.assertTrue(self.window.controlsWidget.isHidden())
        self.assertFalse(self.window._controls_visible)

    def testFullscreenBlankClickStillRevealsInlineControls(self):
        self.window.is_windowed = False
        self.window.controlsWidget.show()
        self.window._setControlsVisible(False, animated=False)

        QTest.mouseClick(
            self.window,
            Qt.MouseButton.LeftButton,
            pos=QPoint(20, 20),
        )
        self.app.processEvents()

        self.assertFalse(self.window.controlsWidget.isHidden())
        self.assertTrue(self.window._controls_visible)

