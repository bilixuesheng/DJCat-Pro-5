from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

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
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import FluentIcon, MessageBox, StrongBodyLabel
from shiboken6 import delete

from app.common import install_location
from app.common.application_store import ApplicationStoreError, packageSlots
from app.config.cfg import BANNER_IMAGE_PRESETS, cfg
from app.config.constants import APP_NAME
from app.config.paths import LOG_DIR
from app.view.components.setting_card_group import SettingCardList
from app.view.components.setting_section import (
    BLOCK_SPACING,
    CARD_SPACING,
    ROOT_SECTION_KEY,
    SLIDE_DURATION_MS,
    SettingNavigationCard,
)
from app.view.pages.setting_page import SettingPage
from tests.support import isolateCfg

TOP_LEVEL_SECTIONS = [
    "全屏投送",
    "考试倒计时",
    "全屏时钟",
    "个性化",
    "应用",
    "关于",
]


class SettingSectionTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

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

    def testPreviewsOnlyLiveOnLeavesAndNeverRepeatAlongARoute(self):
        page = self.buildPage()
        root = page.sectionStack.view(ROOT_SECTION_KEY)
        layout = root.vBoxLayout
        rootWidgets = [layout.itemAt(i).widget() for i in range(layout.count())]

        self.assertTrue(
            all(isinstance(widget, SettingNavigationCard) for widget in rootWidgets)
        )
        for view in page.sectionStack.views():
            with self.subTest(section=view.key):
                if view.navigationCards():
                    self.assertEqual(view.previews(), ())
                else:
                    self.assertLessEqual(len(view.previews()), 1)

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
            self.crumbs(page), ["设置", "全屏投送", "背景"]
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
        self.assertEqual(self.crumbs(page), ["设置", "考试倒计时"])

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

        self.assertEqual(page.currentRouteKey(), "broadcast")

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

    def testTransitionSlidesSnapshotsInsteadOfLivePages(self):
        page = self.buildPage()
        stack = page.sectionStack
        root = stack.view(ROOT_SECTION_KEY)
        target = stack.view("broadcast")

        page.navigateToRoute("broadcast")
        self.app.processEvents()

        # 整页挂不透明度效果时每个 Animation Tick 都要重新栅格化整棵子树。
        for view in (root, target):
            with self.subTest(view=view.key):
                self.assertIsNone(view.graphicsEffect())
                self.assertTrue(view.isHidden())

        QTest.qWait(SLIDE_DURATION_MS + 80)
        self.app.processEvents()

        self.assertTrue(root.isHidden())
        self.assertFalse(target.isHidden())
        self.assertEqual(target.pos(), QPoint(0, 0))
        self.assertEqual(target.size(), stack.size())

    def testResizeDuringTransitionSettlesOnTheTarget(self):
        page = self.buildPage()
        stack = page.sectionStack

        page.navigateToRoute("broadcast")
        self.app.processEvents()
        page.resize(1000, 700)
        self.app.processEvents()

        self.assertFalse(stack.view("broadcast").isHidden())
        self.assertTrue(stack.view(ROOT_SECTION_KEY).isHidden())
        self.assertEqual(stack.view("broadcast").size(), stack.size())

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

    def testAppearanceSectionOffersGhostDownloadersBackgroundEffects(self):
        isolateCfg(self)
        page = self.buildPage()
        card = page.backgroundEffectCard

        self.assertIn(card, page.sectionStack.view("personalization.appearance").settingCards())
        self.assertEqual(card.titleLabel.text(), "窗口背景透明材质")
        self.assertEqual(
            [card.comboBox.itemText(i) for i in range(card.comboBox.count())],
            ["Acrylic", "Mica", "MicaAlt", "Aero", "None"],
        )

        card.comboBox.setCurrentIndex(0)
        self.assertEqual(cfg.backgroundEffect.value, "Acrylic")

    def testFontSectionShowsTheCardsOfTheChosenFontMode(self):
        isolateCfg(self)
        page = self.buildPage()
        view = page.sectionStack.view("personalization.font")

        self.assertEqual(
            view.settingCards(),
            (page.fontModeCard, page.appFontCard, page.latinFontCard, page.cjkFontCard),
        )
        self.assertEqual(page.routeLabel("personalization.font"), "个性化 › 字体")
        self.assertFalse(page.appFontCard.isHidden())
        self.assertTrue(page.latinFontCard.isHidden())
        self.assertTrue(page.cjkFontCard.isHidden())

        page.fontModeCard.comboBox.setCurrentIndex(1)
        self.assertEqual(cfg.appFontMode.value, "中西文分开")
        self.assertTrue(page.appFontCard.isHidden())
        self.assertFalse(page.latinFontCard.isHidden())
        self.assertFalse(page.cjkFontCard.isHidden())

    def testAppearanceSectionOwnsWindowTitleAndCreditsEntry(self):
        page = self.buildPage()

        self.assertEqual(
            page.sectionStack.view("personalization.appearance").settingCards()[-2:],
            (page.windowTitleCard, page.showCreditsCard),
        )

    def testAppearanceSectionSwitchesWindowTransitionsForAllDisplayWindows(self):
        isolateCfg(self)
        page = self.buildPage()
        card = page.windowTransitionCard

        self.assertIn(card, page.sectionStack.view("personalization.appearance").settingCards())
        self.assertEqual(card.titleLabel.text(), "窗口过渡动画")
        self.assertTrue(cfg.windowTransitionEnabled.defaultValue)

        card.switchButton.setChecked(False)
        self.assertFalse(cfg.windowTransitionEnabled.value)

    def panel(self, card) -> SettingCardList:
        widget = card.parentWidget()
        while not isinstance(widget, SettingCardList):
            widget = widget.parentWidget()
        return widget

    def gap(self, upper: QWidget, lower: QWidget) -> int:
        return lower.geometry().top() - upper.geometry().bottom() - 1

    def testOnlyLinkedSettingCardsShareAPanel(self):
        page = self.buildPage()
        linked = {
            tuple(page._backgroundCardSets[prefix])
            for prefix in ("broadcast", "countdown", "fullscreenClock")
        } | {
            (
                page.showBannerCard,
                page.bannerSourceCard,
                page.chooseImageCard,
                page.bannerScaleCard,
                page.bannerBrightnessCard,
            ),
            (page.fontModeCard, page.appFontCard, page.latinFontCard, page.cjkFontCard),
            (page.applicationIconSourceCard, page.applicationIconCard),
            (page.trayIconSourceCard, page.trayIconCard),
        }

        shared = {
            cardList.settingCards()
            for view in page.sectionStack.views()
            for cardList in view.cardLists()
            if len(cardList.settingCards()) > 1
        }
        self.assertEqual(shared, linked)

    def testTrayCardShortcutsStandAloneToo(self):
        page = self.buildPage()
        page.trayCardShortcutList.setHomeCards(
            [
                {"key": "a", "icon": FluentIcon.HOME, "title": "甲"},
                {"key": "b", "icon": FluentIcon.HOME, "title": "乙"},
            ]
        )
        cards = page.trayCardShortcutList.cards()

        self.assertEqual(len(cards), 2)
        for card in cards:
            with self.subTest(card=card.titleLabel.text()):
                self.assertEqual(self.panel(card).settingCards(), (card,))

    def testAdjacentCardsSitCloserThanOtherContent(self):
        page = self.buildPage()
        self.navigate(page, "broadcast")
        view = page.sectionStack.view("broadcast")
        background, aiMarkdown = view.navigationCards()
        title = next(
            label
            for label in view.container.findChildren(StrongBodyLabel)
            if label.text() == "窗口与显示"
        )
        taskbar = self.panel(page.broadcastTaskbarCard)

        self.assertEqual(self.gap(background, aiMarkdown), CARD_SPACING)
        self.assertEqual(
            self.gap(taskbar, self.panel(page.broadcastTopmostFullscreenCard)),
            CARD_SPACING,
        )
        self.assertEqual(self.gap(aiMarkdown, title), BLOCK_SPACING)
        self.assertEqual(self.gap(title, taskbar), BLOCK_SPACING)

        self.navigate(page, "broadcast.background")
        preview = page.sectionStack.view("broadcast.background").previews()[0]
        self.assertEqual(
            self.gap(preview, self.panel(page.broadcastBackgroundModeCard)),
            BLOCK_SPACING,
        )

    def testTurningTheBannerOffHidesTheRestOfItsLinkedCards(self):
        isolateCfg(self)
        cfg.set(cfg.showBanner, True)
        cfg.set(cfg.bannerImageSource, "自定义")
        page = self.buildPage()
        rest = (
            page.bannerSourceCard,
            page.chooseImageCard,
            page.bannerScaleCard,
            page.bannerBrightnessCard,
        )
        self.assertFalse(any(card.isHidden() for card in rest))

        cfg.set(cfg.showBanner, False)
        self.assertFalse(page.showBannerCard.isHidden())
        self.assertTrue(all(card.isHidden() for card in rest))
        self.assertEqual(page.searchSuggestions("横幅亮度"), [])

        cfg.set(cfg.showBanner, True)
        cfg.set(cfg.bannerImageSource, next(iter(BANNER_IMAGE_PRESETS)))
        self.assertTrue(page.chooseImageCard.isHidden())
        self.assertFalse(
            any(card.isHidden() for card in rest if card is not page.chooseImageCard)
        )
        self.assertEqual(
            [item.card for item in page.searchSuggestions("横幅亮度")],
            [page.bannerBrightnessCard],
        )

    def testShortSectionListDoesNotStretchToThePageBottom(self):
        page = self.buildPage()
        page.resize(900, 1200)
        self.navigate(page, "broadcast.aiMarkdown")
        cardList = page.aiStyleCard.parentWidget()
        while not isinstance(cardList, SettingCardList):
            cardList = cardList.parentWidget()

        self.assertEqual(cardList.height(), cardList.sizeHint().height())
        self.assertLess(
            cardList.geometry().bottom(),
            page.sectionStack.view("broadcast.aiMarkdown").viewport().height() - 100,
        )

    def testLineEditSettingSavesWhileTypingAndFlushesOnLeave(self):
        original = cfg.windowTitle.value
        self.addCleanup(cfg.set, cfg.windowTitle, original)
        page = self.buildPage()
        lineEdit = page.windowTitleCard.lineEdit

        lineEdit.setText("第一版")
        self.assertEqual(cfg.windowTitle.value, original)
        self.assertTrue(page.windowTitleCard.saveTimer.isActive())
        for _ in range(100):
            if cfg.windowTitle.value == "第一版":
                break
            QTest.qWait(20)
        self.assertEqual(cfg.windowTitle.value, "第一版")

        lineEdit.setText("第二版")
        page.flushPendingSave()
        self.assertEqual(cfg.windowTitle.value, "第二版")
        self.assertFalse(page.windowTitleCard.saveTimer.isActive())

    def testLogCardFollowsTheCacheCardInTheApplicationSection(self):
        page = self.buildPage()

        self.assertEqual(
            page.sectionStack.view("software").settingCards()[-2:],
            (page.cacheCard, page.logCard),
        )
        self.assertEqual(
            page.sectionStack.view("about").settingCards(),
            (page.authorCard, page.aboutCard),
        )

    def testInstallLocationLivesInTheApplicationStoreSection(self):
        page = self.buildPage()

        self.assertEqual(
            page.routeFor("software.appStore"),
            [ROOT_SECTION_KEY, "software", "software.appStore"],
        )
        self.assertEqual(
            [card.titleLabel.text() for card in page.sectionStack.view("software").navigationCards()],
            ["应用市场", "开发人员选项"],
        )
        self.assertEqual(
            page.sectionStack.view("software.appStore").settingCards(),
            (page.installLocationCard,),
        )
        self.assertIn(
            "应用安装位置",
            [suggestion.text for suggestion in page.searchSuggestions("安装位置")],
        )

    def testInstallLocationCardFollowsTheLocationAndRelocationState(self):
        isolateCfg(self)
        page = self.buildPage()
        card = page.installLocationCard
        requested = []
        page.installLocationChangeRequested.connect(requested.append)
        self.addCleanup(install_location.setRelocationState, install_location.IDLE)

        self.assertIn("（默认）", card.contentLabel.text())
        self.assertFalse(card.resetButton.isEnabled())

        cfg.set(cfg.appInstallLocation, "D:/missing-apps-folder", save=False)
        self.assertIn("（不可用）", card.contentLabel.text())
        self.assertTrue(card.resetButton.isEnabled())
        card.resetButton.click()
        self.assertEqual(requested, [""])

        install_location.setRelocationState(install_location.RELOCATING)
        self.assertIn("正在迁移", card.contentLabel.text())
        self.assertFalse(card.changeButton.isEnabled())
        self.assertFalse(card.resetButton.isEnabled())

        install_location.setRelocationState(install_location.IDLE)
        with patch(
            "app.view.pages.setting_page.QFileDialog.getExistingDirectory",
            return_value="E:/apps",
        ):
            card.changeButton.click()
        self.assertEqual(requested, ["", str(Path("E:/apps"))])

    def testBannerAndAIMarkdownLiveUnderTheirOwners(self):
        page = self.buildPage()

        self.assertEqual(
            page.routeFor("personalization.banner"),
            [ROOT_SECTION_KEY, "personalization", "personalization.banner"],
        )
        self.assertEqual(
            [card.titleLabel.text() for card in page.sectionStack.view("personalization").navigationCards()],
            ["外观", "字体", "主页横幅", "软件图标", "系统托盘"],
        )
        self.assertEqual(
            [card.titleLabel.text() for card in page.sectionStack.view("broadcast").navigationCards()],
            ["背景", "AI 整理"],
        )
        self.assertIn(
            page.aiStyleCard,
            page.sectionStack.view("broadcast.aiMarkdown").settingCards(),
        )

    def testCacheCardBelongsToTheApplicationSection(self):
        page = self.buildPage()

        self.assertIn(
            page.cacheCard,
            page.sectionStack.view("software").settingCards(),
        )
        self.assertNotIn(
            page.cacheCard,
            page.sectionStack.view("about").settingCards(),
        )

    @patch("app.view.pages.setting_page.clearableLogSize", return_value=512)
    @patch("app.view.pages.setting_page.appStoreImageCache")
    def testCacheCardCountsLogsAndDisablesTrashButtonWhenEmpty(
        self, imageCache, logSize
    ):
        imageCache.size.return_value = 1024
        page = self.buildPage()

        self.assertEqual(page.cacheCard.sizeLabel.text(), "1.5 KB")
        self.assertTrue(page.cacheCard.clearButton.isEnabled())

        imageCache.size.return_value = 0
        logSize.return_value = 0
        page._refreshCacheSize()

        self.assertEqual(page.cacheCard.sizeLabel.text(), "0 B")
        self.assertFalse(page.cacheCard.clearButton.isEnabled())

    @patch("app.view.pages.setting_page.InfoBar")
    @patch("app.view.pages.setting_page.clearLogs")
    @patch("app.view.pages.setting_page.clearAppStoreCache")
    def testClearingCacheAsksFirstAndCancelKeepsEverything(
        self, clearAppStoreCache, clearLogs, infoBar
    ):
        page = self.buildPage()
        cleared = []
        page.appStoreCacheCleared.connect(lambda: cleared.append(True))
        boxes = []

        class _Cancel(MessageBox):
            def exec(self):
                boxes.append(
                    (self.titleLabel.text(), self.yesButton.text(), self.cancelButton.text())
                )
                return 0

        with patch("app.view.pages.setting_page.MessageBox", _Cancel):
            page.cacheCard.clicked.emit()

        self.assertEqual(boxes, [("清除缓存", "清除", "取消")])
        clearAppStoreCache.assert_not_called()
        clearLogs.assert_not_called()
        self.assertEqual(cleared, [])
        infoBar.success.assert_not_called()

    @patch("app.view.pages.setting_page.InfoBar")
    @patch("app.view.pages.setting_page.clearLogs")
    @patch("app.view.pages.setting_page.clearAppStoreCache")
    @patch.object(MessageBox, "exec", return_value=1)
    def testClearingCacheAlsoClearsLogs(
        self, _confirm, clearAppStoreCache, clearLogs, infoBar
    ):
        page = self.buildPage()
        cleared = []
        page.appStoreCacheCleared.connect(lambda: cleared.append(True))

        page.cacheCard.clicked.emit()

        clearAppStoreCache.assert_called_once_with()
        clearLogs.assert_called_once_with()
        self.assertEqual(cleared, [True])
        infoBar.success.assert_called_once()

    @patch("app.view.pages.setting_page.InfoBar")
    @patch("app.view.pages.setting_page.clearLogs")
    def testClearingCacheDuringADownloadFailsWithoutAsking(self, clearLogs, infoBar):
        page = self.buildPage()
        cleared = []
        page.appStoreCacheCleared.connect(lambda: cleared.append(True))
        packageSlots.acquire()
        self.addCleanup(packageSlots.release)

        with patch.object(MessageBox, "exec", return_value=1) as confirm:
            page.cacheCard.clicked.emit()

        confirm.assert_not_called()
        clearLogs.assert_not_called()
        self.assertEqual(cleared, [])
        infoBar.error.assert_called_once()

    @patch("app.view.pages.setting_page.InfoBar")
    @patch("app.view.pages.setting_page.clearLogs")
    @patch(
        "app.view.pages.setting_page.clearAppStoreCache",
        side_effect=ApplicationStoreError("有应用正在下载或安装，请完成后再清理缓存"),
    )
    @patch.object(MessageBox, "exec", return_value=1)
    def testRefusedClearLeavesLogsAlone(
        self, _confirm, _clearAppStoreCache, clearLogs, infoBar
    ):
        page = self.buildPage()
        cleared = []
        page.appStoreCacheCleared.connect(lambda: cleared.append(True))

        page.cacheCard.clicked.emit()

        clearLogs.assert_not_called()
        self.assertEqual(cleared, [])
        infoBar.error.assert_called_once()

    def testWindowTitleSettingDefaultsToApplicationName(self):
        page = self.buildPage()

        self.assertEqual(cfg.windowTitle.defaultValue, "")
        self.assertEqual(page.windowTitleCard.lineEdit.placeholderText(), APP_NAME)

    def testLogCardOpensLogDirectory(self):
        page = self.buildPage()

        with patch.object(QDesktopServices, "openUrl") as openUrl:
            page.logCard.clicked.emit()

        openUrl.assert_called_once_with(QUrl.fromLocalFile(str(LOG_DIR)))

    def testNestedCardsToggleOnlyAfterValidRelease(self):
        page = self.buildPage()

        for key, card in (
            ("personalization.appearance", page.themeColorCard),
            ("broadcast.aiMarkdown", page.aiStyleCard),
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
        cls.app = QApplication.instance()

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
                ("全屏投送 › 背景 › 背景类型", "broadcast.background"),
                ("考试倒计时 › 背景 › 背景类型", "countdown.background"),
                ("全屏时钟 › 背景 › 背景类型", "fullscreenClock.background"),
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
            ["设置", "全屏投送"],
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
