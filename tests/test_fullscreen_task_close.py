import os
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from qfluentwidgets import Flyout, PrimaryPushButton, PushButton

from app.config.cfg import cfg
from app.view.pages.broadcast_page import BroadcastEditPage
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
