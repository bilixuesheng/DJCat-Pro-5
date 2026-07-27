import os
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

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
        self.showMainWindow = cfg.showMainWindowAfterFullscreenTask.value
        cfg.file = Path(self.tempDir.name) / "config.json"

    def tearDown(self):
        cfg.set(cfg.showMainWindowAfterFullscreenTask, self.showMainWindow)
        self.app.setQuitOnLastWindowClosed(True)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testClosingFullscreenTasksFollowsMainWindowSetting(self):
        self.assertTrue(cfg.showMainWindowAfterFullscreenTask.defaultValue)

        for enabled, pageType, windowName in (
            (True, BroadcastEditPage, "broadcastWin"),
            (True, CountdownEditPage, "countdownWin"),
            (False, BroadcastEditPage, "broadcastWin"),
            (False, CountdownEditPage, "countdownWin"),
        ):
            with self.subTest(enabled=enabled, pageType=pageType.__name__):
                cfg.set(cfg.showMainWindowAfterFullscreenTask, enabled)
                page = pageType()
                page.hide()
                taskWindow = getattr(page, windowName)
                taskWindow.show()
                taskWindow.close()
                self.app.processEvents()

                self.assertEqual(page.isVisible(), enabled)
                self.assertEqual(self.app.quitOnLastWindowClosed(), enabled)
                page.close()
