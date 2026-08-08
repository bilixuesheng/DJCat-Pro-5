import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon
from shiboken6 import delete

from app.config.cfg import cfg
from app.view.components.setting_card_group import QWIDGETSIZE_MAX
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
                self.assertEqual(group.headerWidget.height(), 64)
                self.assertGreaterEqual(group.headerLayout.contentsMargins().top(), 12)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testHeaderGeometryStaysFixedDuringExpandAnimation(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.personalGroup
        group._setCollapsed(True)
        QTest.qWait(group.collapseAnimation.duration())
        self.app.processEvents()
        initialGeometry = (
            group.headerWidget.geometry(),
            group.iconWidget.geometry(),
            group.titleLabel.geometry(),
            group.contentLabel.geometry(),
        )

        group._setCollapsed(False)
        QTest.qWait(40)
        self.app.processEvents()

        self.assertEqual(
            (
                group.headerWidget.geometry(),
                group.iconWidget.geometry(),
                group.titleLabel.geometry(),
                group.contentLabel.geometry(),
            ),
            initialGeometry,
        )

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingCardsRevealBelowHeaderWithoutBeingCompressed(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.bannerGroup
        group._setCollapsed(True)
        QTest.qWait(group.collapseAnimation.duration())
        card = group.settingCards()[0]
        initialGeometry = card.geometry()

        group._setCollapsed(False)
        QTest.qWait(40)
        self.app.processEvents()

        self.assertEqual(group.cardView.y(), 0)
        self.assertEqual(card.geometry(), initialGeometry)
        self.assertEqual(card.mapTo(group, QPoint()).y(), 67)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testAIMarkdownEditorRevealsBelowStationaryHeader(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        card = page.aiStyleCard
        card.setExpandedImmediately(False)
        editorGeometry = card.editorWidget.geometry()

        for expanded in (True, False):
            card.setExpand(expanded)
            QTest.qWait(80)
            self.app.processEvents()
            with self.subTest(expanded=expanded):
                self.assertEqual(card.card.y(), 0)
                self.assertEqual(card.card.height(), 70)
                self.assertEqual(card.view.y(), 70)
                self.assertEqual(card.viewContent.y(), 0)
                self.assertEqual(card.editorWidget.geometry(), editorGeometry)
            QTest.qWait(card.expandAnimation.duration())

    @patch("app.view.pages.setting_page.threading.Thread")
    def testExpandedGroupDrawsHeaderSeparator(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.personalGroup
        group._setCollapsed(False)
        QTest.qWait(group.collapseAnimation.duration())
        self.app.processEvents()

        self.assertIs(group.cardLayout.itemAt(0).widget(), group.separator)
        self.assertEqual(group.separator.height(), 3)
        image = QImage(group.separator.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        group.separator.render(image)
        self.assertTrue(
            any(image.pixelColor(x, 1).alpha() for x in range(image.width()))
        )

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingCardsHaveVisibleSeparatorsWithoutOrphans(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.countdownGroup

        self.assertEqual(len(group._itemSeparators), len(group.settingCards()))
        self.assertIsNone(group._itemSeparators[0])
        for separator in group._itemSeparators[1:]:
            with self.subTest(separator=separator):
                self.assertFalse(separator.isHidden())
                image = QImage(separator.size(), QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                separator.render(image)
                self.assertTrue(
                    any(
                        image.pixelColor(x, 1).alpha()
                        for x in range(image.width())
                    )
                )

        page.setSearchText("重置时间")

        self.assertTrue(group.isVisible())
        self.assertTrue(all(s.isHidden() for s in group._itemSeparators[1:]))

    @patch("app.view.components.setting_card_group.cfg.set")
    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingGroupTogglesOnlyAfterValidRelease(self, _, __):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.personalGroup
        header = group.headerWidget
        start = QPoint(120, header.height() // 2)
        initialState = group.isCollapsed

        QTest.mousePress(header, Qt.MouseButton.LeftButton, pos=start)
        QTest.qWait(250)
        self.assertEqual(group.isCollapsed, initialState)
        self.assertTrue(group.isPressed)

        outside = QPoint(header.width() + 20, start.y())
        QTest.mouseMove(header, outside)
        QTest.mouseRelease(header, Qt.MouseButton.LeftButton, pos=outside)
        self.assertEqual(group.isCollapsed, initialState)
        self.assertFalse(group.isPressed)

        QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=start)
        self.assertNotEqual(group.isCollapsed, initialState)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSearchExpansionKeepsArrowAndContentInSync(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.aiMarkdownGroup
        group._setCollapsed(True)
        QTest.qWait(group.collapseAnimation.duration())

        page.setSearchText("AI")

        self.assertTrue(group.isCollapsed)
        self.assertEqual(group.cardContainer.maximumHeight(), QWIDGETSIZE_MAX)
        self.assertIs(group.expandButton._icon, FluentIcon.CHEVRON_DOWN_MED)

        group._onExpandClicked()
        self.assertTrue(group.isCollapsed)
        QTest.qWait(group.collapseAnimation.duration())
        self.assertEqual(group.cardContainer.maximumHeight(), 0)
        self.assertIs(group.expandButton._icon, FluentIcon.CHEVRON_RIGHT_MED)

        group._onExpandClicked()
        QTest.qWait(group.collapseAnimation.duration())
        self.assertTrue(group.isCollapsed)
        self.assertGreater(group.cardContainer.height(), 0)
        self.assertIs(group.expandButton._icon, FluentIcon.CHEVRON_DOWN_MED)

        page.setSearchText("")

        self.assertEqual(group.cardContainer.maximumHeight(), 0)
        self.assertIs(group.expandButton._icon, FluentIcon.CHEVRON_RIGHT_MED)

    def testNewPromptSettingsDefaultToSafeValues(self):
        self.assertFalse(cfg.broadcastMarkdownEnabled.defaultValue)
        self.assertTrue(cfg.confirmBeforeResetCountdown.defaultValue)

    @patch("app.view.pages.setting_page.fetchQuota", return_value=None)
    def testQuotaResultIsIgnoredAfterSettingPageIsDestroyed(self, _):
        page = SettingPage()
        fetch_quota = page._fetchAIQuota
        delete(page)

        fetch_quota()
