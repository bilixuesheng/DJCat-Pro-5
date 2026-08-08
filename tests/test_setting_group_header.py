import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from app.config.cfg import cfg
from app.view.pages.setting_page import SettingPage


class SettingGroupHeaderTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def testSettingGroupsUseWideIconHeaders(self):
        page = SettingPage()
        self.addCleanup(page.deleteLater)

        for group in page._settingGroups():
            with self.subTest(group=group.objectName()):
                self.assertIsNotNone(group.iconWidget)
                self.assertEqual(group.iconWidget.size().width(), 24)
                self.assertGreaterEqual(group.headerLayout.contentsMargins().top(), 16)

    def testNewPromptSettingsDefaultToSafeValues(self):
        self.assertFalse(cfg.broadcastMarkdownEnabled.defaultValue)
        self.assertTrue(cfg.confirmBeforeResetCountdown.defaultValue)

    @patch("app.view.pages.setting_page.fetchQuota", return_value=None)
    def testQuotaResultIsIgnoredAfterSettingPageIsDestroyed(self, _):
        page = SettingPage()
        fetch_quota = page._fetchAIQuota
        delete(page)

        fetch_quota()
