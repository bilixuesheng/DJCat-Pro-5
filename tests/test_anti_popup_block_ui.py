from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.components.setting_section import (
    BLOCK_SPACING,
    ROOT_SECTION_KEY,
    SLIDE_DURATION_MS,
)
from app.view.pages.setting_page import SettingPage
from tests.support import isolateCfg


class AntiPopupBlockUiTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        # 开关绑着 cfg：任何 cfg 变化（含 isolateCfg 收尾把值还原）都会回拨到确认重启那一步。
        # 全程替换成一个不弹真窗的 Mock，默认取消；要"确认"的用例把 return_value 设成 True。
        confirm = patch.object(
            SettingPage, "_confirmAntiBlockRestart", return_value=False
        )
        self.confirm = confirm.start()
        self.addCleanup(confirm.stop)

    def buildPage(self):
        isolateCfg(self)
        patcher = patch("app.view.pages.setting_page.threading.Thread")
        patcher.start()
        self.addCleanup(patcher.stop)
        page = SettingPage()
        # 同步销毁：开关绑着 cfg 单例，上一轮残留的页面若还活着会和新页面互相回拨开关、
        # 无限递归。deleteLater 不处理事件循环就删不掉，这里直接 delete。
        self.addCleanup(lambda: delete(page))
        page.resize(900, 640)
        page.show()
        self.app.processEvents()
        return page

    def navigate(self, page, key):
        page.navigateToRoute(key)
        QTest.qWait(SLIDE_DURATION_MS + 80)
        self.app.processEvents()

    def tipHidden(self, page):
        # 提示在根 Section 里：根页被推走时它跟着藏起来，自己的显隐标志不变。
        return not page.antiBlockTip.isVisibleTo(page)

    def rootView(self, page):
        return page.sectionStack.view(ROOT_SECTION_KEY)

    def antiPopupBlockRow(self, page):
        return next(
            card
            for card in self.rootView(page).navigationCards()
            if card.titleLabel.text() == "反弹窗拦截"
        )

    def rowInView(self, page, row):
        view = self.rootView(page)
        top = row.mapTo(view.viewport(), QPoint()).y()
        return top >= 0 and top + row.height() <= view.viewport().height()

    def testTipShowsOnRootWhenDisabledAndUndismissed(self):
        page = self.buildPage()
        self.assertFalse(self.tipHidden(page))

    def testTipHiddenOutsideRootAndBackAgain(self):
        page = self.buildPage()
        self.navigate(page, "broadcast")
        self.assertTrue(self.tipHidden(page))
        self.navigate(page, ROOT_SECTION_KEY)
        self.assertFalse(self.tipHidden(page))

    def testTipNeverShowsWhenEnabled(self):
        page = self.buildPage()
        self.confirm.return_value = True
        cfg.set(cfg.antiPopupBlockEnabled, True)
        self.app.processEvents()
        self.assertTrue(self.tipHidden(page))

    def testDismissForNowHidesWithoutPersisting(self):
        page = self.buildPage()
        page._onAntiBlockTipDismissForNow()
        self.assertTrue(self.tipHidden(page))
        self.assertFalse(bool(cfg.antiPopupBlockTipDismissed.value))
        # 下次启动（新页面）又出现。
        page2 = self.buildPage()
        self.assertFalse(self.tipHidden(page2))

    def testDismissForeverPersistsAndStaysHidden(self):
        page = self.buildPage()
        page._onAntiBlockTipDismissForever()
        self.assertTrue(self.tipHidden(page))
        self.assertTrue(bool(cfg.antiPopupBlockTipDismissed.value))

    def testTipIsTheFirstBlockOfTheRootAndScrollsWithIt(self):
        page = self.buildPage()
        view = self.rootView(page)
        self.assertTrue(view.container.isAncestorOf(page.antiBlockTip))
        self.assertLess(
            page.antiBlockTipContainer.y(), view.navigationCards()[0].y()
        )

        before = page.antiBlockTip.mapTo(page, QPoint()).y()
        view.verticalScrollBar().setValue(40)
        self.app.processEvents()
        self.assertEqual(page.antiBlockTip.mapTo(page, QPoint()).y(), before - 40)

    def testHiddenTipLeavesNoGapAboveTheRows(self):
        page = self.buildPage()
        firstRow = self.rootView(page).navigationCards()[0]
        tip = page.antiBlockTipContainer
        # 提示和第一行之间照"其他内容前后隔 10 px"。
        self.assertEqual(
            firstRow.y() - tip.y() - page.antiBlockTip.height(), BLOCK_SPACING
        )

        page._onAntiBlockTipDismissForNow()
        self.app.processEvents()
        layout = self.rootView(page).vBoxLayout
        self.assertEqual(firstRow.y(), layout.contentsMargins().top())

    def testGoStaysOnRootAndScrollsTheRowIntoView(self):
        page = self.buildPage()
        row = self.antiPopupBlockRow(page)
        self.assertFalse(self.rowInView(page, row))

        page._onAntiBlockTipGo()
        QTest.qWait(SLIDE_DURATION_MS + 500)
        self.app.processEvents()

        self.assertEqual(page.currentRouteKey(), ROOT_SECTION_KEY)
        self.assertTrue(self.rowInView(page, row))
        self.assertIs(page.highlight.parentWidget(), row)
        self.assertTrue(page.highlight.isVisible())

    def testGoOnlyHighlightsARowAlreadyInView(self):
        page = self.buildPage()
        page.resize(900, 1200)
        self.app.processEvents()
        row = self.antiPopupBlockRow(page)
        self.assertTrue(self.rowInView(page, row))

        page._onAntiBlockTipGo()
        QTest.qWait(SLIDE_DURATION_MS + 500)
        self.app.processEvents()

        self.assertEqual(self.rootView(page).verticalScrollBar().value(), 0)
        self.assertIs(page.highlight.parentWidget(), row)

    def testRerollChangesNameAndRequestsRestart(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        self.confirm.return_value = True
        page._onRerollDisguisedName()
        self.assertTrue(requested)
        self.assertNotEqual(cfg.disguisedProductName.value, "DJCat Pro")
        self.assertNotEqual(cfg.disguisedProductName.value, APP_NAME)

    # 直接调处理函数、只断言本页自己的信号：开关绑着 cfg 单例，走 setValue 会被别的测试
    # 残留的、仍连在同一 cfg 上的 SettingPage 串扰（整套跑时才暴露）。真实运行只有一个页面。
    def testToggleOnConfirmedRequestsRestart(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        self.confirm.return_value = True
        page._onAntiPopupBlockToggled(True)
        self.assertEqual(len(requested), 1)

    def testToggleCanceledRevertsAndDoesNotRequestRestart(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        self.confirm.return_value = False
        page._onAntiPopupBlockToggled(True)
        self.assertEqual(requested, [])

    def testCardsAllHiddenWhenDisabled(self):
        page = self.buildPage()
        vis = page._conditionalCardVisibility()
        for card in (
            page.antiBlockModeCard,
            page.rotateDaysCard,
            page.disguisedNameCard,
            page.customNameCard,
        ):
            self.assertFalse(vis[card])

    def testAutoModeShowsIntervalAndHidesManualControls(self):
        page = self.buildPage()
        self.confirm.return_value = True
        cfg.set(cfg.antiPopupBlockEnabled, True)
        cfg.set(cfg.antiPopupBlockMode, "auto")
        vis = page._conditionalCardVisibility()
        self.assertTrue(vis[page.antiBlockModeCard])
        self.assertTrue(vis[page.rotateDaysCard])
        self.assertFalse(vis[page.disguisedNameCard])
        self.assertFalse(vis[page.customNameCard])

    def testManualModeShowsNameControlsAndHidesInterval(self):
        page = self.buildPage()
        self.confirm.return_value = True
        cfg.set(cfg.antiPopupBlockEnabled, True)
        cfg.set(cfg.antiPopupBlockMode, "manual")
        vis = page._conditionalCardVisibility()
        self.assertFalse(vis[page.rotateDaysCard])
        self.assertTrue(vis[page.disguisedNameCard])
        self.assertTrue(vis[page.customNameCard])

    def testFirstEnableInAutoRollsRandomNameAndStampsBaseline(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        self.confirm.return_value = True
        cfg.set(cfg.antiPopupBlockMode, "auto")
        page._onAntiPopupBlockToggled(True)
        self.assertEqual(len(requested), 1)
        self.assertNotEqual(cfg.disguisedProductName.value, "DJCat Pro")
        self.assertNotEqual(cfg.disguisedProductName.value, APP_NAME)
        self.assertTrue(cfg.antiPopupBlockRotatedOn.value)

    def testFirstEnableInManualKeepsDefaultNameButStampsBaseline(self):
        page = self.buildPage()
        self.confirm.return_value = True
        cfg.set(cfg.antiPopupBlockMode, "manual")
        page._onAntiPopupBlockToggled(True)
        # 手动管理开启不自动换名，仍是默认名；基线照样落定。
        self.assertEqual(cfg.disguisedProductName.value, "DJCat Pro")
        self.assertTrue(cfg.antiPopupBlockRotatedOn.value)

    def testCustomNameAppliesAndRequestsRestart(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        with patch("app.view.pages.setting_page.CustomNameDialog") as Dialog:
            instance = Dialog.return_value
            instance.exec.return_value = True
            instance.name.return_value = "SmartClass 4"
            page._onSetCustomName()
        self.assertEqual(cfg.disguisedProductName.value, "SmartClass 4")
        self.assertEqual(len(requested), 1)
        self.assertTrue(cfg.antiPopupBlockRotatedOn.value)

    def testCustomNameCanceledDoesNothing(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        with patch("app.view.pages.setting_page.CustomNameDialog") as Dialog:
            Dialog.return_value.exec.return_value = False
            page._onSetCustomName()
        self.assertEqual(requested, [])

    def testChangingIntervalDoesNotRequestRestart(self):
        page = self.buildPage()
        requested = []
        page.antiPopupBlockApplyRequested.connect(lambda: requested.append(True))
        page.rotateDaysCard.spinBox.setValue(7)
        self.assertEqual(cfg.antiPopupBlockRotateDays.value, 7)
        self.assertEqual(requested, [])
