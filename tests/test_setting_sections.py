import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    Qt,
    QUrl,
)
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.config.paths import LOG_DIR
from app.view.components.setting_section import (
    ROOT_SECTION_KEY,
    SLIDE_DURATION_MS,
    SettingNavigationCard,
)
from app.view.pages.setting_page import SettingPage

TOP_LEVEL_SECTIONS = [
    "横幅设置",
    "全屏投送设置",
    "AI整理Markdown设置",
    "考试倒计时设置",
    "全屏时钟设置",
    "个性化",
    "应用",
    "关于",
]


class SettingSectionTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def buildPage(self):
        patcher = patch("app.view.pages.setting_page.threading.Thread")
        patcher.start()
        self.addCleanup(patcher.stop)
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        page.resize(900, 640)
        page.show()
        self.app.processEvents()
        return page

    def navigate(self, page, key):
        page.navigateToRoute(key)
        QTest.qWait(SLIDE_DURATION_MS + 80)
        self.app.processEvents()

    def crumbs(self, page):
        return [item.text for item in page.breadcrumbBar.items]

    def testRootListsEveryTopLevelSectionAsANavigationRow(self):
        page = self.buildPage()
        root = page.sectionStack.view(ROOT_SECTION_KEY)

        self.assertEqual(
            [card.titleLabel.text() for card in root.navigationCards()],
            TOP_LEVEL_SECTIONS,
        )
        self.assertEqual(root.settingCards(), ())
        for card in root.navigationCards():
            with self.subTest(section=card.titleLabel.text()):
                self.assertEqual(card.height(), 70)
                self.assertEqual(card.iconWidget.size().width(), 24)
                self.assertTrue(card.contentLabel.text())

    def testOnlyTheCurrentSectionStaysVisible(self):
        page = self.buildPage()

        def visibleKeys():
            return [
                view.key for view in page.sectionStack.views() if not view.isHidden()
            ]

        self.assertEqual(visibleKeys(), [ROOT_SECTION_KEY])

        self.navigate(page, "broadcast.background")
        self.assertEqual(visibleKeys(), ["broadcast.background"])
        self.assertEqual(
            self.crumbs(page), ["设置", "全屏投送设置", "背景"]
        )

        self.navigate(page, ROOT_SECTION_KEY)
        self.assertEqual(visibleKeys(), [ROOT_SECTION_KEY])
        self.assertEqual(self.crumbs(page), ["设置"])

    def testBreadcrumbClickReturnsToAnAncestorSection(self):
        page = self.buildPage()
        self.navigate(page, "countdown.background")

        page.breadcrumbBar.setCurrentItem("countdown")
        QTest.qWait(SLIDE_DURATION_MS + 80)
        self.app.processEvents()

        self.assertEqual(page.currentRouteKey(), "countdown")
        self.assertEqual(self.crumbs(page), ["设置", "考试倒计时设置"])

    def testNavigationRowIgnoresAPressDraggedOffTheCard(self):
        page = self.buildPage()
        card = page.sectionStack.view(ROOT_SECTION_KEY).navigationCards()[0]
        start = QPoint(120, card.height() // 2)
        outside = QPoint(card.width() + 40, start.y())

        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(card, outside)
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=outside)
        self.app.processEvents()

        self.assertEqual(page.currentRouteKey(), ROOT_SECTION_KEY)

        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=start)
        QTest.qWait(SLIDE_DURATION_MS + 80)
        self.app.processEvents()

        self.assertEqual(page.currentRouteKey(), "banner")

    def testOnlyVisitedSectionsGrabTheTouchGesture(self):
        page = self.buildPage()

        def grabbed():
            return {
                view.key
                for view in page.sectionStack.views()
                if view.isTouchGestureGrabbed
            }

        self.assertEqual(grabbed(), {ROOT_SECTION_KEY})

        self.navigate(page, "broadcast")
        self.assertEqual(grabbed(), {ROOT_SECTION_KEY, "broadcast"})

        # 回到已访问过的 Section 不该再抓一次，抓了又放会在 Qt 的手势管理器里留下残留。
        self.navigate(page, ROOT_SECTION_KEY)
        self.assertEqual(grabbed(), {ROOT_SECTION_KEY, "broadcast"})

    def testRepeatedNavigationDoesNotAccumulateAnimationGroups(self):
        page = self.buildPage()
        stack = page.sectionStack

        def liveGroups():
            # deleteLater() 只在事件循环处理 DeferredDelete 时生效。
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            return len(stack.findChildren(QParallelAnimationGroup))

        self.navigate(page, "broadcast")
        self.navigate(page, ROOT_SECTION_KEY)
        settled = liveGroups()

        for _ in range(12):
            self.navigate(page, "broadcast")
            self.navigate(page, ROOT_SECTION_KEY)

        # 每次推移都会新建一个动画组；不释放就会随会话一直涨。
        self.assertEqual(liveGroups(), settled)

    def testInterruptedNavigationDoesNotAccumulateAnimationGroups(self):
        page = self.buildPage()
        stack = page.sectionStack

        def liveGroups():
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            return len(stack.findChildren(QParallelAnimationGroup))

        # 不等动画结束就换目标，走 stopAnimations() 那条收尾路径。
        for _ in range(12):
            page.navigateToRoute("broadcast")
            page.navigateToRoute(ROOT_SECTION_KEY)
        self.app.processEvents()
        interrupted = liveGroups()

        for _ in range(60):
            page.navigateToRoute("broadcast")
            page.navigateToRoute(ROOT_SECTION_KEY)
        self.app.processEvents()
        self.assertEqual(liveGroups(), interrupted)

    def testBackgroundSectionsCarryAPreviewAndTheirOwnCards(self):
        page = self.buildPage()

        for key, backgroundCard in (
            ("broadcast.background", page.broadcastBackgroundModeCard),
            ("countdown.background", page.countdownBackgroundModeCard),
            ("fullscreenClock.background", page.fullscreenClockBackgroundModeCard),
        ):
            view = page.sectionStack.view(key)
            with self.subTest(section=key):
                self.assertIn(backgroundCard, view.settingCards())
                self.assertEqual(len(view.settingCards()), 4)
                self.assertEqual(view.navigationCards(), ())

    def testAboutSectionKeepsErrorLogBetweenAuthorAndAbout(self):
        page = self.buildPage()

        self.assertEqual(
            page.sectionStack.view("about").settingCards(),
            (page.authorCard, page.errorLogCard, page.aboutCard),
        )

    def testCacheCardBelongsToTheApplicationSection(self):
        page = self.buildPage()

        self.assertIn(
            page.clearAppStoreCacheCard,
            page.sectionStack.view("software").settingCards(),
        )
        self.assertNotIn(
            page.clearAppStoreCacheCard,
            page.sectionStack.view("about").settingCards(),
        )

    @patch("app.view.pages.setting_page.appStoreImageCache")
    def testCacheCardShowsSizeAndDisablesTrashButtonWhenEmpty(self, imageCache):
        imageCache.size.return_value = 1536
        page = self.buildPage()

        self.assertEqual(page.clearAppStoreCacheCard.sizeLabel.text(), "1.5 KB")
        self.assertTrue(page.clearAppStoreCacheCard.clearButton.isEnabled())

        imageCache.size.return_value = 0
        page._refreshAppStoreCacheSize()

        self.assertEqual(page.clearAppStoreCacheCard.sizeLabel.text(), "0 B")
        self.assertFalse(page.clearAppStoreCacheCard.clearButton.isEnabled())

    def testWindowTitleSettingDefaultsToApplicationName(self):
        page = self.buildPage()

        self.assertEqual(cfg.windowTitle.defaultValue, "")
        self.assertEqual(page.windowTitleCard.lineEdit.placeholderText(), APP_NAME)

    def testErrorLogCardOpensLogDirectory(self):
        page = self.buildPage()

        with patch.object(QDesktopServices, "openUrl") as openUrl:
            page.errorLogCard.clicked.emit()

        openUrl.assert_called_once_with(QUrl.fromLocalFile(str(LOG_DIR)))

    def testNestedCardsToggleOnlyAfterValidRelease(self):
        page = self.buildPage()

        for key, card in (
            ("personalization.appearance", page.themeColorCard),
            ("aiMarkdown", page.aiStyleCard),
        ):
            self.navigate(page, key)
            card.setExpandedImmediately(False)
            self.app.processEvents()
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

    def testNewPromptSettingsDefaultToSafeValues(self):
        self.assertFalse(cfg.broadcastMarkdownEnabled.defaultValue)
        self.assertTrue(cfg.confirmBeforeResetCountdown.defaultValue)

    @patch("app.view.pages.setting_page.fetchQuota", return_value=None)
    def testQuotaResultIsIgnoredAfterSettingPageIsDestroyed(self, _):
        with patch("app.view.pages.setting_page.threading.Thread"):
            page = SettingPage()
        fetchAIQuota = page._fetchAIQuota
        delete(page)

        fetchAIQuota()


class SettingSuggestionTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patcher = patch("app.view.pages.setting_page.threading.Thread")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.page = SettingPage()
        self.addCleanup(self.page.deleteLater)
        self.page.resize(900, 640)
        self.page.show()
        self.app.processEvents()

    def testBlankSearchOffersNothing(self):
        self.assertEqual(self.page.searchSuggestions(""), [])
        self.assertEqual(self.page.searchSuggestions("   "), [])

    def testDuplicatedTitlesCarryTheirFullRouteAndUniqueOnesDoNot(self):
        duplicated = self.page.searchSuggestions("背景类型")
        unique = self.page.searchSuggestions("横幅亮度")

        self.assertEqual(
            [(item.text, item.routeKey) for item in duplicated],
            [
                ("全屏投送设置 › 背景 › 背景类型", "broadcast.background"),
                ("考试倒计时设置 › 背景 › 背景类型", "countdown.background"),
                ("全屏时钟设置 › 背景 › 背景类型", "fullscreenClock.background"),
            ],
        )
        self.assertEqual([item.text for item in unique], ["主页横幅亮度"])

    def testSuggestionsAreCappedAndMatchTitlesOnly(self):
        matches = self.page.searchSuggestions("置顶")

        self.assertLessEqual(len(matches), self.page.MAX_SUGGESTIONS)
        self.assertTrue(matches)
        for suggestion in matches:
            with self.subTest(suggestion=suggestion.text):
                self.assertIn("置顶", suggestion.text)

        # 说明文字里有"任务栏"，但标题是"显示任务栏"；只按标题匹配不会多出别的卡片。
        self.assertEqual(
            {suggestion.routeKey for suggestion in self.page.searchSuggestions("免打扰")},
            set(),
        )

    def testConditionallyHiddenCardsStayOutOfTheSuggestions(self):
        mode = cfg.broadcastBackgroundMode.value
        try:
            cfg.set(cfg.broadcastBackgroundMode, "主题色")
            self.assertEqual(
                [
                    item
                    for item in self.page.searchSuggestions("背景颜色")
                    if item.routeKey == "broadcast.background"
                ],
                [],
            )

            cfg.set(cfg.broadcastBackgroundMode, "纯色")
            self.assertEqual(
                [
                    item.routeKey
                    for item in self.page.searchSuggestions("背景颜色")
                ],
                ["broadcast.background"],
            )
        finally:
            cfg.set(cfg.broadcastBackgroundMode, mode)

    def testChoosingASuggestionNavigatesAndHighlightsTheCard(self):
        suggestion = next(
            item
            for item in self.page.searchSuggestions("启动时恢复")
            if item.card is self.page.broadcastRestoreCard
        )

        self.page.navigateToSuggestion(suggestion)
        QTest.qWait(SLIDE_DURATION_MS + 120)
        self.app.processEvents()

        self.assertEqual(self.page.currentRouteKey(), "broadcast")
        self.assertEqual(
            [item.text for item in self.page.breadcrumbBar.items],
            ["设置", "全屏投送设置"],
        )
        self.assertIs(self.page.highlight.parent(), self.page.broadcastRestoreCard)
        self.assertTrue(self.page.highlight.isVisible())

    def testEverySuggestionPointsAtACardThatLivesOnItsRoute(self):
        for suggestion in self.page._suggestions:
            view = self.page.sectionStack.view(suggestion.routeKey)
            with self.subTest(suggestion=suggestion.text):
                self.assertIsNotNone(view)
                self.assertIn(suggestion.card, view.settingCards())

    def testNavigationRowsAreNotOfferedAsSuggestions(self):
        cards = {
            suggestion.card
            for suggestion in self.page._suggestions
        }
        for card in cards:
            with self.subTest(card=type(card).__name__):
                self.assertNotIsInstance(card, SettingNavigationCard)
