import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedWidget, QWidget
from qfluentwidgets import Flyout, PrimaryPushButton, PushButton
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.view.pages.broadcast_page import BroadcastEditPage, VerticalButton
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
                cfg.countdownActionButtonPosition,
                cfg.showMainWindowAfterCountdown,
                cfg.confirmBeforeCloseCountdown,
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

    def testFullscreenActionButtonShowsPressedStateAndCancelsOutsideRelease(self):
        for primary in (False, True):
            with self.subTest(primary=primary):
                button = VerticalButton(
                    FIF.CLOSE,
                    "关闭",
                    primary=primary,
                    force_dark=True,
                )
                button.show()
                self.app.processEvents()
                clicks = []
                button.clicked.connect(lambda: clicks.append(True))

                center = button.rect().center()
                QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=center)
                self.assertTrue(button.isDown())
                self.assertIn("QToolButton:pressed", button.styleSheet())

                QTest.mouseRelease(
                    button,
                    Qt.MouseButton.LeftButton,
                    pos=QPoint(button.width() + 10, button.height() + 10),
                )
                self.assertFalse(button.isDown())
                self.assertEqual(clicks, [])

                QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=center)
                self.assertEqual(clicks, [True])
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

                cfg.set(setting, False)
                taskWindow.show()
                taskWindow.btn_close.click()
                self.app.processEvents()
                self.assertFalse(taskWindow.isVisible())
                page.close()
