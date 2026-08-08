import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget
from qfluentwidgets import Flyout, PrimaryPushButton, PushButton
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.view.pages.broadcast_page import (
    AIMarkdownDialog,
    BroadcastEditPage,
    VerticalButton,
)
from app.view.pages.countdown_page import CountdownEditPage


class FullscreenTaskCloseTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.configValues = [
            (item, item.value)
            for item in (
                cfg.broadcastActionButtonPosition,
                cfg.showMainWindowAfterBroadcast,
                cfg.confirmBeforeCloseBroadcast,
                cfg.broadcastMarkdownEnabled,
                cfg.countdownActionButtonPosition,
                cfg.showMainWindowAfterCountdown,
                cfg.confirmBeforeCloseCountdown,
                cfg.confirmBeforeResetCountdown,
            )
        ]
        cfg.file = Path(self.tempDir.name) / "config.json"

    def tearDown(self):
        for item, value in self.configValues:
            cfg.set(item, value)
        self.app.setQuitOnLastWindowClosed(True)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testTaskSettingsHaveIndependentDefaults(self):
        self.assertEqual(cfg.broadcastActionButtonPosition.defaultValue, "右下角")
        self.assertEqual(cfg.countdownActionButtonPosition.defaultValue, "右下角")
        self.assertTrue(cfg.showMainWindowAfterBroadcast.defaultValue)
        self.assertTrue(cfg.showMainWindowAfterCountdown.defaultValue)
        self.assertTrue(cfg.confirmBeforeCloseBroadcast.defaultValue)
        self.assertTrue(cfg.confirmBeforeCloseCountdown.defaultValue)
        self.assertFalse(cfg.broadcastMarkdownEnabled.defaultValue)
        self.assertTrue(cfg.confirmBeforeResetCountdown.defaultValue)

    def testFullscreenActionButtonShowsPressedStateAndCancelsOutsideRelease(self):
        for primary in (False, True):
            with self.subTest(primary=primary):
                button = VerticalButton(
                    FIF.CLOSE,
                    "关闭",
                    primary=primary,
                )
                button.show()
                self.app.processEvents()
                clicks = []
                button.clicked.connect(lambda: clicks.append(True))

                center = button.rect().center()
                QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=center)
                self.assertTrue(button.isDown())
                expectedType = PrimaryPushButton if primary else PushButton
                self.assertIsInstance(button, expectedType)
                self.assertNotIn("qlineargradient", button.styleSheet())
                self.assertEqual(button.size(), QSize(80, 65))

                QTest.mouseRelease(
                    button,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(button.width() + 10, button.height() + 10),
                )
                self.assertFalse(button.isDown())
                self.assertEqual(clicks, [])

                QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=center)
                self.assertEqual(clicks, [True])
                button.setWindowed(True)
                self.assertEqual(button.size(), QSize(50, 40))
                button.close()

    def testFullscreenActionButtonUsesReadableForegroundColor(self):
        with patch(
            "app.view.pages.broadcast_page.isDarkTheme",
            return_value=False,
        ):
            normalButton = VerticalButton(FIF.EDIT, "编辑")
            forcedDarkButton = VerticalButton(
                FIF.EDIT,
                "编辑",
                force_dark=True,
            )
            primaryButton = VerticalButton(
                FIF.CLOSE,
                "关闭",
                primary=True,
            )
            self.assertEqual(normalButton._foregroundColor().name(), "#000000")
            self.assertEqual(forcedDarkButton._foregroundColor().name(), "#ffffff")
            self.assertEqual(primaryButton._foregroundColor().name(), "#ffffff")

        with patch(
            "app.view.pages.broadcast_page.isDarkTheme",
            return_value=True,
        ):
            self.assertEqual(normalButton._foregroundColor().name(), "#ffffff")

        for button in (normalButton, forcedDarkButton, primaryButton):
            button.close()

    def testClosingTasksFollowsEachMainWindowSetting(self):
        for enabled, pageType, windowName, setting in (
            (True, BroadcastEditPage, "broadcastWin", cfg.showMainWindowAfterBroadcast),
            (True, CountdownEditPage, "countdownWin", cfg.showMainWindowAfterCountdown),
            (False, BroadcastEditPage, "broadcastWin", cfg.showMainWindowAfterBroadcast),
            (False, CountdownEditPage, "countdownWin", cfg.showMainWindowAfterCountdown),
        ):
            with self.subTest(enabled=enabled, pageType=pageType.__name__):
                cfg.set(setting, enabled)
                page = pageType()
                page.hide()
                taskWindow = getattr(page, windowName)
                taskWindow.show()
                taskWindow.close()
                self.app.processEvents()

                self.assertEqual(page.isVisible(), enabled)
                self.assertEqual(self.app.quitOnLastWindowClosed(), enabled)
                page.close()

    def testBroadcastEditRestoresActiveContentAfterEditorWasDiscarded(self):
        container = QStackedWidget()
        page = BroadcastEditPage(container)
        otherPage = QWidget(container)
        container.addWidget(page)
        container.addWidget(otherPage)
        page.editSignal.connect(lambda: container.setCurrentWidget(page))
        page.backSignal.connect(lambda: container.setCurrentWidget(otherPage))

        container.show()
        page.titleInput.setText("正在投送的标题")
        page.contentInput.setPlainText("**正在投送的正文**")
        page.markdownCheckBox.setChecked(True)
        page._onBroadcast()
        self.app.processEvents()

        container.show()
        with patch(
            "app.view.pages.broadcast_page.MessageBox.exec",
            return_value=True,
        ):
            page.backBtn.click()
        self.app.processEvents()

        self.assertIs(container.currentWidget(), otherPage)
        self.assertEqual(page.titleInput.text(), "")
        self.assertEqual(page.contentInput.toPlainText(), "")

        page.broadcastWin.btn_edit.click()
        self.app.processEvents()

        self.assertIs(container.currentWidget(), page)
        self.assertTrue(container.isVisible())
        self.assertEqual(page.titleInput.text(), "正在投送的标题")
        self.assertEqual(
            page.contentInput.toPlainText(),
            "**正在投送的正文**",
        )
        self.assertTrue(page.markdownCheckBox.isChecked())

        container.close()

    def testCloseButtonsConfirmBeforeDiscardingTask(self):
        for pageType, windowName, setting, warning in (
            (
                BroadcastEditPage,
                "broadcastWin",
                cfg.confirmBeforeCloseBroadcast,
                "关闭后不会保存投送文字。",
            ),
            (
                CountdownEditPage,
                "countdownWin",
                cfg.confirmBeforeCloseCountdown,
                "关闭后不会保存倒计时进度。",
            ),
        ):
            with self.subTest(pageType=pageType.__name__):
                cfg.set(setting, True)
                page = pageType()
                page.hide()
                taskWindow = getattr(page, windowName)
                taskWindow.show()
                taskWindow.btn_close.click()
                self.app.processEvents()

                flyout = next(
                    (
                        child
                        for child in taskWindow.findChildren(Flyout)
                        if child.isVisible()
                    ),
                    None,
                )
                self.assertIsNotNone(flyout)
                self.assertTrue(flyout.isVisible())
                self.assertEqual(flyout.view.contentLabel.text(), warning)

                taskWindow.btn_close.click()
                self.app.processEvents()
                self.assertEqual(
                    [
                        child
                        for child in taskWindow.findChildren(Flyout)
                        if child.isVisible()
                    ],
                    [flyout],
                )

                cancelButton = next(
                    button
                    for button in flyout.findChildren(PushButton)
                    if button.text() == "取消"
                )
                cancelButton.click()
                self.app.processEvents()
                self.assertTrue(taskWindow.isVisible())

                taskWindow.btn_close.click()
                self.app.processEvents()
                flyout = next(
                    child
                    for child in taskWindow.findChildren(Flyout)
                    if child.isVisible()
                )
                closeButton = next(
                    button
                    for button in flyout.findChildren(PrimaryPushButton)
                    if button.text() == "关闭"
                )
                closeButton.click()
                self.app.processEvents()

                self.assertFalse(taskWindow.isVisible())
                self.assertFalse(
                    any(
                        child.isVisible()
                        for child in taskWindow.findChildren(Flyout)
                    )
                )
                self.assertIsNone(taskWindow._closeFlyout)

                cfg.set(setting, False)
                taskWindow.show()
                taskWindow.btn_close.click()
                self.app.processEvents()
                self.assertFalse(taskWindow.isVisible())
                page.close()

    def testMarkdownChoiceIsLoadedAndPersisted(self):
        cfg.set(cfg.broadcastMarkdownEnabled, True)
        page = BroadcastEditPage()
        self.assertTrue(page.markdownCheckBox.isChecked())
        self.assertTrue(page.aiBtn.isEnabled())
        self.assertIn("Markdown", page.contentInput.placeholderText())

        page.markdownCheckBox.setChecked(False)
        self.app.processEvents()

        self.assertFalse(cfg.broadcastMarkdownEnabled.value)
        page.close()

    def testWindowedBroadcastUsesTouchFriendlyResizeBorder(self):
        page = BroadcastEditPage()
        window = page.broadcastWin

        self.assertGreaterEqual(window.BORDER_WIDTH, 12)
        window.is_windowed = True
        window._applyWindowState()

        self.assertTrue(window._isResizeEnabled)
        window.close()
        page.close()

    def testAIMarkdownDialogDoesNotOverlapQuotaRequestsAndStopsTimers(self):
        parent = QWidget()
        parent.resize(800, 600)
        with patch("app.view.pages.broadcast_page.threading.Thread") as thread:
            dialog = AIMarkdownDialog("", parent)
            self.assertEqual(thread.call_count, 1)

            dialog._refreshQuota()
            self.assertEqual(thread.call_count, 1)

            dialog._result = "转换结果"
            dialog._onConversionFinished(10, 15, 1)
            self.assertFalse(dialog._quotaTimer.isActive())

            dialog._busyTimer.start()
            dialog.close()
            self.app.processEvents()

        self.assertFalse(dialog._busyTimer.isActive())
        self.assertFalse(dialog._quotaTimer.isActive())
        dialog.deleteLater()
        parent.close()
