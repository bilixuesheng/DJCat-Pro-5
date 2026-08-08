import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from app.config.cfg import cfg
from app.view.pages.setting_page import SettingPage


class SettingGroupHeaderTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingGroupsUseWideIconHeaders(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()

        for group in page._settingGroups():
            with self.subTest(group=group.objectName()):
                self.assertIsNotNone(group.iconWidget)
                self.assertEqual(group.iconWidget.size().width(), 24)
                self.assertTrue(group.contentLabel.text())
                self.assertTrue(group.contentLabel.isVisible())
                self.assertGreaterEqual(group.headerLayout.contentsMargins().top(), 12)

    @patch("app.view.components.setting_card_group.cfg.set")
    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingGroupTogglesOnlyAfterValidRelease(self, _, __):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.personalGroup
        start = QPoint(120, group.cardContainer.geometry().top() // 2)
        initialState = group.isCollapsed

        QTest.mousePress(group, Qt.MouseButton.LeftButton, pos=start)
        QTest.qWait(250)
        self.assertEqual(group.isCollapsed, initialState)
        self.assertTrue(group.isPressed)

        outside = QPoint(group.width() + 20, start.y())
        QTest.mouseMove(group, outside)
        QTest.mouseRelease(group, Qt.MouseButton.LeftButton, pos=outside)
        self.assertEqual(group.isCollapsed, initialState)
        self.assertFalse(group.isPressed)

        QTest.mouseClick(group, Qt.MouseButton.LeftButton, pos=start)
        self.assertNotEqual(group.isCollapsed, initialState)

    def testNewPromptSettingsDefaultToSafeValues(self):
        self.assertFalse(cfg.broadcastMarkdownEnabled.defaultValue)
        self.assertTrue(cfg.confirmBeforeResetCountdown.defaultValue)

    @patch("app.view.pages.setting_page.fetchQuota", return_value=None)
    def testQuotaResultIsIgnoredAfterSettingPageIsDestroyed(self, _):
        page = SettingPage()
        fetch_quota = page._fetchAIQuota
        delete(page)

        fetch_quota()
