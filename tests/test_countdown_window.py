import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScroller, QWidget
from qfluentwidgets import Flyout, PrimaryPushButton, PushButton

from app.config.cfg import cfg
from app.view.components.scroll_area import ScrollArea
from app.view.components.task_picker import TouchTimePicker
from app.view.pages.countdown_page import CountdownEditPage, CountdownWindow


class CountdownWindowTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        cfg.file = Path(self.tempDir.name) / "config.json"
        self.confirmBeforeReset = cfg.confirmBeforeResetCountdown.value
        self.window = CountdownWindow()
        self.window.resize(720, 240)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        cfg.set(cfg.confirmBeforeResetCountdown, self.confirmBeforeReset)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testWindowedModeCollapsesInlineControls(self):
        self.window.is_windowed = True
        self.window._applyWindowState()
        self.app.processEvents()

        self.assertTrue(self.window.controlsWidget.isHidden())
        self.assertFalse(self.window.controlsWidget.isEnabled())
        self.assertFalse(self.window._controls_visible)

    def testEditPageUsesTouchTimePicker(self):
        page = CountdownEditPage()

        self.assertIsInstance(page.timePicker, TouchTimePicker)
        page.close()

    def testEditPageScrollsCardsAtSmallWindowHeight(self):
        page = CountdownEditPage()
        page.resize(720, 300)
        page.show()
        self.app.processEvents()

        cards = page.scrollWidget.findChildren(
            QWidget,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        self.assertIsInstance(page.scrollArea, ScrollArea)
        self.assertEqual(len(cards), 4)
        self.assertTrue(
            all(
                first.geometry().bottom() < second.geometry().top()
                for first, second in zip(cards, cards[1:])
            )
        )
        self.assertGreater(page.scrollArea.verticalScrollBar().maximum(), 0)
        self.assertGreater(
            QScroller.grabbedGesture(page.scrollArea.viewport()).value,
            0,
        )
        page.close()

    def testEditPagePassesCustomEndTitle(self):
        page = CountdownEditPage()
        page.titleInput.setText("数学考试")
        page.endTitleInput.setText("请停止答题")
        quitOnLastWindowClosed = self.app.quitOnLastWindowClosed()

        try:
            with patch.object(page.countdownWin, "startCountdown") as startCountdown:
                page._onStart()

            startCountdown.assert_called_once_with("数学考试", 3600, True, "请停止答题")
        finally:
            self.app.setQuitOnLastWindowClosed(quitOnLastWindowClosed)
            page.close()

    def testEditPageFallsBackToDefaultEndTitle(self):
        page = CountdownEditPage()
        page.endTitleInput.setText("  ")
        quitOnLastWindowClosed = self.app.quitOnLastWindowClosed()

        try:
            with patch.object(page.countdownWin, "startCountdown") as startCountdown:
                page._onStart()

            self.assertEqual(startCountdown.call_args.args[3], "考试结束")
        finally:
            self.app.setQuitOnLastWindowClosed(quitOnLastWindowClosed)
            page.close()

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

    def testPauseButtonKeepsThemeStyleAcrossControlFade(self):
        self.window._setControlsVisible(True, animated=False)
        self.window._setControlsVisible(False, animated=True)

        self.assertTrue(self.window.controlsWidget.isEnabled())
        self.window._controlsAnim.setCurrentTime(
            self.window._controlsAnim.duration()
        )
        self.app.processEvents()
        self.assertFalse(self.window.controlsWidget.isEnabled())

        self.window._setControlsVisible(True, animated=True)
        self.assertTrue(self.window.controlsWidget.isEnabled())
        self.assertFalse(self.window.btn_pause.icon().isNull())

    def testResetConfirmationCanCancelOrConfirm(self):
        self.window.initial_seconds = 600
        self.window.remaining = 120
        cfg.set(cfg.confirmBeforeResetCountdown, True)
        self.window._setupCornerButtons()

        self.window.btn_reset.click()
        self.app.processEvents()
        flyout = next(
            child
            for child in self.window.findChildren(Flyout)
            if child.isVisible()
        )
        cancelButton = next(
            button
            for button in flyout.findChildren(PushButton)
            if button.text() == "取消"
        )
        cancelButton.click()
        self.app.processEvents()
        self.assertEqual(self.window.remaining, 120)

        self.window.btn_reset.click()
        self.app.processEvents()
        flyout = next(
            child
            for child in self.window.findChildren(Flyout)
            if child.isVisible()
        )
        resetButton = next(
            button
            for button in flyout.findChildren(PrimaryPushButton)
            if button.text() == "重置"
        )
        resetButton.click()
        self.app.processEvents()
        self.assertEqual(self.window.remaining, 600)
        self.assertIsNone(self.window._resetFlyout)

    def testResetCanRunWithoutConfirmation(self):
        self.window.initial_seconds = 600
        self.window.remaining = 120
        cfg.set(cfg.confirmBeforeResetCountdown, False)
        self.window._setupCornerButtons()

        self.window.btn_reset.click()
        self.app.processEvents()

        self.assertEqual(self.window.remaining, 600)
        self.assertFalse(
            any(
                child.isVisible()
                for child in self.window.findChildren(Flyout)
            )
        )

    def testCountdownUsesElapsedTimeAfterEventLoopStall(self):
        with patch("app.view.pages.countdown_page.time.monotonic") as monotonic:
            monotonic.return_value = 100.0
            self.window.startCountdown("测试", 60, False)
            monotonic.return_value = 105.2
            self.window._tickCountdown()

        self.assertEqual(self.window.remaining, 55)

    def testCountdownShowsCustomEndTitle(self):
        self.window.startCountdown("数学考试", 60, False, "请停止答题")

        self.window._setRemaining(0)

        self.assertEqual(self.window.titleLabel.text(), "请停止答题")

    def testCountdownKeepsDefaultEndTitle(self):
        self.window.startCountdown("数学考试", 60, False)

        self.window._setRemaining(0)

        self.assertEqual(self.window.titleLabel.text(), "考试结束")

    def testPauseAndAdjustRebuildMonotonicDeadline(self):
        with patch("app.view.pages.countdown_page.time.monotonic") as monotonic:
            monotonic.return_value = 100.0
            self.window.startCountdown("测试", 60, False)
            monotonic.return_value = 105.2
            self.window._onPause()
            self.assertEqual(self.window.remaining, 55)

            monotonic.return_value = 200.0
            self.window._onPause()
            self.window._onAdjust(-30)
            monotonic.return_value = 205.1
            self.window._tickCountdown()

        self.assertEqual(self.window.remaining, 20)
