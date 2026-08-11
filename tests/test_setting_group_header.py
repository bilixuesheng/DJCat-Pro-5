import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPropertyAnimation, QUrl, Qt
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import TransparentToolButton
from shiboken6 import delete

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.config.paths import LOG_DIR
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
                self.assertEqual(group.headerWidget.height(), 70)
                self.assertGreaterEqual(group.headerLayout.contentsMargins().top(), 12)
                for card in group.settingCards():
                    header = getattr(card, "card", card)
                    self.assertEqual(header.height(), group.headerWidget.height())

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingGroupsDoNotExposeReorderControls(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()

        self.assertEqual(
            [group.objectName() for group in page._settingGroups()],
            [
                "personalization",
                "banner",
                "broadcast",
                "countdown",
                "aiMarkdown",
                "software",
                "about",
            ],
        )
        for group in page._settingGroups():
            with self.subTest(group=group.objectName()):
                self.assertFalse(
                    group.headerWidget.findChildren(TransparentToolButton)
                )

    @patch("app.view.pages.setting_page.threading.Thread")
    def testAppStoreCacheCardBelongsToSoftwareGroup(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)

        self.assertIn(
            page.clearAppStoreCacheCard,
            page.softwareGroup.settingCards(),
        )
        self.assertNotIn(
            page.clearAppStoreCacheCard,
            page.aboutGroup.settingCards(),
        )

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
        group.collapseAnimation.pause()
        for frame in (0, 1, 8, 16, 32, 40):
            group.collapseAnimation.setCurrentTime(frame)
            self.app.processEvents()
            with self.subTest(frame=frame):
                self.assertEqual(
                    (
                        group.headerWidget.geometry(),
                        group.iconWidget.geometry(),
                        group.titleLabel.geometry(),
                        group.contentLabel.geometry(),
                    ),
                    initialGeometry,
                )
                self.assertEqual(
                    group.height(),
                    group.headerWidget.height()
                    + int(group.collapseAnimation.currentValue()),
                )
                self.assertEqual(
                    group.cardContainer.geometry().top(),
                    group.headerWidget.height(),
                )
                self.assertGreaterEqual(
                    group.settingCards()[0].mapTo(group, QPoint()).y(),
                    group.headerWidget.height(),
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
        self.assertIsNotNone(group.cardView.graphicsEffect())

        group._setCollapsed(False)
        self.assertEqual(group.cardContainer.height(), 0)
        self.assertIsNotNone(group.cardView.graphicsEffect())
        self.app.processEvents()
        QTest.qWait(40)
        self.app.processEvents()

        self.assertIsNone(group.cardView.graphicsEffect())
        self.assertEqual(group.cardView.y(), 0)
        self.assertEqual(card.geometry(), initialGeometry)
        self.assertEqual(card.mapTo(group, QPoint()).y(), 73)

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
        self.assertIsNotNone(card.viewContent.graphicsEffect())

        for expanded in (True, False):
            card.setExpand(expanded)
            if expanded:
                self.assertEqual(card.view.height(), 0)
                self.assertIsNotNone(card.viewContent.graphicsEffect())
            self.app.processEvents()
            QTest.qWait(80)
            self.app.processEvents()
            with self.subTest(expanded=expanded):
                self.assertEqual(card.card.y(), 0)
                self.assertEqual(card.card.height(), 70)
                self.assertEqual(card.view.y(), 70)
                self.assertEqual(card.viewContent.y(), 0)
                self.assertEqual(card.editorWidget.geometry(), editorGeometry)
            QTest.qWait(card.expandAnimation.duration())
            self.assertEqual(card.viewContent.graphicsEffect() is None, expanded)

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
        visibleCards = [card for card in group.settingCards() if not card.isHidden()]
        visibleSeparators = [
            separator
            for separator in group._itemSeparators[1:]
            if not separator.isHidden()
        ]
        self.assertEqual(len(visibleSeparators), max(len(visibleCards) - 1, 0))
        for separator in visibleSeparators:
            with self.subTest(separator=separator):
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
    def testNestedCardsToggleOnlyAfterValidRelease(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()

        for card in (page.themeColorCard, page.aiStyleCard):
            card.setExpandedImmediately(False)
            header = card.card
            start = QPoint(120, header.height() // 2)
            outside = QPoint(header.width() + 20, start.y())

            QTest.mousePress(header, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(header, outside)
            QTest.mouseRelease(header, Qt.MouseButton.LeftButton, pos=outside)
            with self.subTest(card=header.titleLabel.text()):
                self.assertFalse(card.isExpand)

            QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=start)
            with self.subTest(card=header.titleLabel.text(), action="click"):
                self.assertTrue(card.isExpand)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testWindowTitleSettingDefaultsToApplicationName(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)

        self.assertEqual(cfg.windowTitle.defaultValue, "")
        self.assertEqual(page.windowTitleCard.lineEdit.placeholderText(), APP_NAME)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSearchExpansionKeepsArrowAndContentInSync(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(800, 600)
        page.show()
        self.app.processEvents()
        group = page.aiMarkdownGroup
        group._setCollapsed(True)
        group.collapseAnimation.setCurrentTime(group.collapseAnimation.duration())
        group.expandButton.rotateAnimation.setCurrentTime(
            group.expandButton.rotateAnimation.duration()
        )

        def toggleAndWait():
            finished = QSignalSpy(group.expandButton.rotateAnimation.finished)
            group._onExpandClicked()
            self.assertTrue(finished.wait(1000))
            self.app.processEvents()

        page.setSearchText("AI")

        self.assertTrue(group.isCollapsed)
        self.assertEqual(group.cardContainer.maximumHeight(), QWIDGETSIZE_MAX)
        self.assertAlmostEqual(group.expandButton.angle, 90, delta=0.01)

        toggleAndWait()
        self.assertTrue(group.isCollapsed)
        self.assertEqual(group.cardContainer.maximumHeight(), 0)
        self.assertAlmostEqual(group.expandButton.angle, 0, delta=0.01)

        toggleAndWait()
        self.assertTrue(group.isCollapsed)
        self.assertGreater(group.cardContainer.height(), 0)
        self.assertAlmostEqual(group.expandButton.angle, 90, delta=0.01)

        page.setSearchText("")

        self.assertEqual(group.cardContainer.maximumHeight(), 0)
        self.assertEqual(group.expandButton.angle, 0)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testSettingGroupArrowRotatesDuringExpansion(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        group = page.personalGroup
        group._setCollapsed(True)
        group.collapseAnimation.setCurrentTime(group.collapseAnimation.duration())

        group._setCollapsed(False)
        self.assertEqual(
            group.expandButton.rotateAnimation.state(),
            QPropertyAnimation.State.Running,
        )
        group.expandButton.rotateAnimation.setCurrentTime(100)

        self.assertGreater(group.expandButton.angle, 0)
        self.assertLess(group.expandButton.angle, 90)

    def testNewPromptSettingsDefaultToSafeValues(self):
        self.assertFalse(cfg.broadcastMarkdownEnabled.defaultValue)
        self.assertTrue(cfg.confirmBeforeResetCountdown.defaultValue)

    @patch("app.view.pages.setting_page.threading.Thread")
    def testErrorLogCardOpensLogDirectory(self, _):
        page = SettingPage()
        self.addCleanup(page.deleteLater)

        with patch.object(QDesktopServices, "openUrl") as openUrl:
            page.errorLogCard.clicked.emit()

        openUrl.assert_called_once_with(QUrl.fromLocalFile(str(LOG_DIR)))

    @patch("app.view.pages.setting_page.fetchQuota", return_value=None)
    def testQuotaResultIsIgnoredAfterSettingPageIsDestroyed(self, _):
        page = SettingPage()
        fetch_quota = page._fetchAIQuota
        delete(page)

        fetch_quota()
