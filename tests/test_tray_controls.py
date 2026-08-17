import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QInputDevice
from PySide6.QtWidgets import QApplication, QScroller, QWidget
from PySide6.QtTest import QTest
from qfluentwidgets import FluentIcon as FIF, RoundMenu

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.pages.home_page import HomePage
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow


class TrayConfigTest(TestCase):
    def testDefaultsPreserveExistingTrayBehavior(self):
        self.assertEqual(cfg.trayLeftClickAction.defaultValue, "ShowWindow")
        self.assertEqual(cfg.trayTooltip.defaultValue, "")
        self.assertTrue(cfg.showBroadcastTrayAction.defaultValue)
        self.assertTrue(cfg.showShutdownTrayAction.defaultValue)
        self.assertEqual(cfg.trayHomeCardKeys.defaultValue, [])
        self.assertFalse(cfg.trayHomeCardsInSubmenu.defaultValue)


class HomeCardTrayInterfaceTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.values = [
            (item, item.value)
            for item in (
                cfg.homeCardOrder,
                cfg.visibleDefaultHomeCards,
                cfg.customHomeCards,
                cfg.pinnedHomeCards,
                cfg.trayHomeCardKeys,
            )
        ]
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(
            cfg.homeCardOrder,
            ["考试倒计时", "全屏投送", "定时播报", "定时关机"],
        )
        cfg.set(
            cfg.visibleDefaultHomeCards,
            ["全屏投送", "考试倒计时", "定时关机", "定时播报"],
        )
        cfg.set(cfg.customHomeCards, [])
        cfg.set(cfg.pinnedHomeCards, [])
        cfg.set(cfg.trayHomeCardKeys, [])
        self.page = HomePage()

    def tearDown(self):
        self.page.close()
        for item, value in self.values:
            cfg.set(item, value)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testEntriesFollowHomeOrderAndIdentifyDefaultCards(self):
        entries = self.page.homeCardEntries()

        self.assertEqual(
            [entry["key"] for entry in entries],
            ["考试倒计时", "全屏投送", "定时播报", "定时关机"],
        )
        self.assertEqual({entry["source"] for entry in entries}, {"default"})
        self.assertEqual(entries[0]["title"], "考试倒计时")
        self.assertIn("icon", entries[0])

    def testEntriesIncludeCustomAndApplicationHomeCards(self):
        self.page.close()
        cfg.set(
            cfg.customHomeCards,
            [
                {
                    "id": "custom-one",
                    "title": "自定义入口",
                    "description": "执行动作序列",
                    "icon": {"type": "fluent", "name": "LINK"},
                    "actions": [
                        {"id": "wait", "type": "delay", "seconds": 1}
                    ],
                }
            ],
        )
        cfg.set(
            cfg.homeCardOrder,
            ["custom:custom-one", "app:7:0", "全屏投送"],
        )
        self.page = HomePage()
        self.page.setApplicationCards(
            [
                {
                    "app_id": 7,
                    "preset_id": 0,
                    "title": "应用入口",
                    "description": "打开应用",
                    "action": {"type": "url", "url": "https://example.test"},
                }
            ]
        )

        entries = self.page.homeCardEntries()

        self.assertEqual(
            [
                (entry["key"], entry["source"], entry["title"])
                for entry in entries[:2]
            ],
            [
                ("custom:custom-one", "custom", "自定义入口"),
                ("app:7:0", "application", "应用入口"),
            ],
        )
        self.assertTrue(all(entry["icon"] is not None for entry in entries[:2]))

    def testApplicationCardChangesPublishCurrentEntries(self):
        updates = []
        self.page.homeCardsChanged.connect(updates.append)

        self.page.setApplicationCards(
            [
                {
                    "app_id": 7,
                    "preset_id": 0,
                    "title": "应用入口",
                    "action": {"type": "url", "url": "https://example.test"},
                }
            ]
        )

        self.assertIn("app:7:0", [entry["key"] for entry in updates[-1]])

    def testAHomeCardCanBeActivatedByItsStableKey(self):
        clicks = []
        self.page.all_cards["全屏投送"].clicked.connect(
            lambda: clicks.append("全屏投送")
        )

        self.assertTrue(self.page.activateHomeCard("全屏投送"))
        self.assertFalse(self.page.activateHomeCard("missing"))
        self.assertEqual(clicks, ["全屏投送"])

    def testTrayControlPageDropsMissingCardSelections(self):
        from app.view.pages.tray_control_page import TrayControlPage

        cfg.set(cfg.trayHomeCardKeys, ["missing", "全屏投送"])
        trayPage = TrayControlPage()
        try:
            trayPage.setHomeCards(self.page.homeCardEntries())

            self.assertEqual(cfg.trayHomeCardKeys.value, ["全屏投送"])
            self.assertEqual(
                list(trayPage.homeCardSwitches),
                ["考试倒计时", "全屏投送", "定时播报", "定时关机"],
            )
        finally:
            trayPage.deleteLater()

    def testTrayControlPagePersistsClickAndCardChoices(self):
        from app.view.pages.tray_control_page import TrayControlPage

        trayPage = TrayControlPage()
        try:
            trayPage.setHomeCards(self.page.homeCardEntries())
            trayPage.leftClickCard.comboBox.setCurrentIndex(1)
            trayPage.homeCardSwitches["考试倒计时"].setChecked(True)

            self.assertEqual(cfg.trayLeftClickAction.value, "ShowMenu")
            self.assertEqual(cfg.trayHomeCardKeys.value, ["考试倒计时"])
        finally:
            trayPage.deleteLater()

    def testTrayControlPageKeepsTouchScrollingAndSizedControls(self):
        from app.view.pages.tray_control_page import TrayControlPage

        trayPage = TrayControlPage()
        trayPage.setHomeCards(self.page.homeCardEntries())
        trayPage.show()
        self.app.processEvents()
        try:
            self.assertTrue(QScroller.hasScroller(trayPage.viewport()))
            self.assertGreaterEqual(trayPage.leftClickCard.comboBox.height(), 40)
            self.assertTrue(
                all(
                    card.switchButton.height() >= 40
                    for card in trayPage.homeCardSwitches.values()
                )
            )
        finally:
            trayPage.deleteLater()


class TrayControlNavigationTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        self.quotaPatcher.start()
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)

    def tearDown(self):
        self.window.tray = None
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.quotaPatcher.stop()

    def testTrayControlsSitBetweenCreditsAndSettings(self):
        routeKeys = list(self.window.navigationInterface.items)

        self.assertLess(
            routeKeys.index(self.window.creditsPage.objectName()),
            routeKeys.index(self.window.trayControlPage.objectName()),
        )
        self.assertLess(
            routeKeys.index(self.window.trayControlPage.objectName()),
            routeKeys.index(self.window.settingPage.objectName()),
        )

        self.assertEqual(
            list(self.window.trayControlPage.homeCardSwitches),
            ["全屏投送", "考试倒计时", "定时关机", "定时播报"],
        )

    def testTrayDefaultCardShowsMainWindowBeforeActivation(self):
        with (
            patch.object(self.window, "show") as show,
            patch.object(self.window, "raise_") as raiseWindow,
            patch.object(self.window, "activateWindow") as activateWindow,
            patch.object(
                self.window.homePage,
                "activateHomeCard",
                return_value=True,
            ) as activateCard,
        ):
            self.window._onTrayHomeCardTriggered("全屏投送")

        show.assert_called_once_with()
        raiseWindow.assert_called_once_with()
        activateWindow.assert_called_once_with()
        activateCard.assert_called_once_with("全屏投送")

    def testLazyApplicationPagePropagatesPinnedCardResult(self):
        from app.view.windows.main_window import LazyAppStorePage

        page = LazyAppStorePage()
        loaded = type("Loaded", (), {"executePinnedCard": lambda self, item: False})()
        page.ensureLoaded = lambda: loaded

        self.assertIs(page.executePinnedCard({"app_id": 7, "preset_id": 0}), False)

    def testTrayCustomCardDoesNotShowWindowOnSuccess(self):
        entry = {
            "key": "custom:one",
            "source": "custom",
            "title": "自定义入口",
            "description": "",
            "icon": FIF.APPLICATION,
        }
        with (
            patch.object(
                self.window.homePage,
                "homeCardEntries",
                return_value=[entry],
            ),
            patch.object(
                self.window.homePage,
                "activateHomeCard",
                return_value=True,
            ) as activateCard,
            patch.object(self.window, "_showMainWindow") as showWindow,
        ):
            self.window._onTrayHomeCardTriggered("custom:one")

        showWindow.assert_not_called()
        activateCard.assert_called_once_with("custom:one")

    def testFailedApplicationCardShowsWindowButSuccessDoesNot(self):
        with patch.object(self.window, "_showMainWindow") as showWindow:
            self.window.appStorePage.executePinnedCard = lambda item: True
            self.window._onPinnedHomeCardClicked({"app_id": 7})
            showWindow.assert_not_called()

            self.window.appStorePage.executePinnedCard = lambda item: False
            self.window._onPinnedHomeCardClicked({"app_id": 7})
            showWindow.assert_called_once_with()


class TrayMenuTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.values = [
            (item, item.value)
            for item in (
                cfg.broadcastTasks,
                cfg.shutdownTasks,
                cfg.showBroadcastTrayAction,
                cfg.showShutdownTrayAction,
                cfg.trayTooltip,
                cfg.trayHomeCardKeys,
                cfg.trayHomeCardsInSubmenu,
            )
        ]
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(
            cfg.broadcastTasks,
            [{"enabled": True}],
        )
        cfg.set(
            cfg.shutdownTasks,
            [{"enabled": True}],
        )
        cfg.set(cfg.showBroadcastTrayAction, True)
        cfg.set(cfg.showShutdownTrayAction, True)
        cfg.set(cfg.trayHomeCardKeys, ["custom:one"])
        cfg.set(cfg.trayHomeCardsInSubmenu, False)
        self.parent = QWidget()

    def tearDown(self):
        self.parent.deleteLater()
        for item, value in self.values:
            cfg.set(item, value)
        cfg.file = self.configFile
        self.tempDir.cleanup()
        self.app.processEvents()

    def _createTray(self):
        from app.view.shell.tray import SystemTrayIcon

        tray = SystemTrayIcon(self.parent)
        tray.setHomeCards(
            [
                {
                    "key": "custom:one",
                    "source": "custom",
                    "title": "自定义入口",
                    "description": "执行自定义动作",
                    "icon": FIF.APPLICATION,
                }
            ]
        )
        return tray

    def testBlankTrayTooltipUsesApplicationNameAndEditingUpdatesIt(self):
        from app.view.shell.tray import SystemTrayIcon

        cfg.set(cfg.trayTooltip, "")
        tray = SystemTrayIcon(self.parent)
        page = SettingPage()
        try:
            tooltipCard = next(
                card
                for card in page.personalGroup.settingCards()
                if card.titleLabel.text() == "自定义托盘文本"
            )
            self.assertEqual(tooltipCard.lineEdit.placeholderText(), APP_NAME)
            self.assertEqual(tray.toolTip(), APP_NAME)

            tooltipCard.lineEdit.setText("值班托盘")
            tooltipCard.lineEdit.editingFinished.emit()
            self.assertEqual(cfg.trayTooltip.value, "值班托盘")
            self.assertEqual(tray.toolTip(), "值班托盘")

            tooltipCard.lineEdit.setText("   ")
            tooltipCard.lineEdit.editingFinished.emit()
            self.assertEqual(tray.toolTip(), APP_NAME)
        finally:
            page.deleteLater()
            tray.deleteLater()

    def testMenuKeepsFixedEntriesAndPlacesCardsAfterTaskActions(self):
        tray = self._createTray()
        try:
            self.assertEqual(
                [action.text() for action in tray.menu.actions()],
                [
                    "主页",
                    "关闭所有播报",
                    "关闭所有关机",
                    "自定义入口",
                    "退出程序",
                ],
            )
        finally:
            tray.deleteLater()

    def testHiddenTaskActionIsAbsentFromMenu(self):
        cfg.set(cfg.showBroadcastTrayAction, False)
        tray = self._createTray()
        try:
            self.assertNotIn(
                "关闭所有播报",
                [action.text() for action in tray.menu.actions()],
            )
            self.assertIn(
                "关闭所有关机",
                [action.text() for action in tray.menu.actions()],
            )
        finally:
            tray.deleteLater()

    def testCardMenuOrderFollowsLatestHomeOrder(self):
        cfg.set(cfg.trayHomeCardKeys, ["custom:one", "custom:two"])
        tray = self._createTray()
        try:
            tray.setHomeCards(
                [
                    {
                        "key": "custom:two",
                        "source": "custom",
                        "title": "第二项",
                        "description": "",
                        "icon": FIF.APPLICATION,
                    },
                    {
                        "key": "custom:one",
                        "source": "custom",
                        "title": "第一项",
                        "description": "",
                        "icon": FIF.APPLICATION,
                    },
                ]
            )
            self.assertEqual(
                [action.text() for action in tray.menu.actions()][3:5],
                ["第二项", "第一项"],
            )
        finally:
            tray.deleteLater()

    def testCardActionDelegatesToMainWindowTrigger(self):
        triggered = []
        self.parent._onTrayHomeCardTriggered = triggered.append
        tray = self._createTray()
        try:
            cardAction = next(
                action
                for action in tray.menu.actions()
                if action.text() == "自定义入口"
            )
            cardAction.trigger()
            self.assertEqual(triggered, ["custom:one"])
        finally:
            tray.deleteLater()

    def testSelectedCardsCanBeGroupedInHomeCardSubmenu(self):
        cfg.set(cfg.trayHomeCardsInSubmenu, True)
        tray = self._createTray()
        try:
            self.assertNotIn(
                "自定义入口",
                [action.text() for action in tray.menu.actions()],
            )
            submenus = tray.menu.findChildren(RoundMenu)
            self.assertEqual([menu.title() for menu in submenus], ["主页卡片"])
            self.assertEqual(
                [action.text() for action in submenus[0].actions()],
                ["自定义入口"],
            )
        finally:
            tray.deleteLater()

    def testLeftClickCanOpenMenuOrMainWindow(self):
        tray = self._createTray()
        try:
            with patch.object(tray.menu, "exec") as showMenu, patch.object(
                tray, "_onShowActionTriggered"
            ) as showWindow:
                cfg.set(cfg.trayLeftClickAction, "ShowMenu")
                tray.onTrayIconClick(
                    tray.ActivationReason.Trigger
                )
                showMenu.assert_called_once()
                showWindow.assert_not_called()

                cfg.set(cfg.trayLeftClickAction, "ShowWindow")
                tray.onTrayIconClick(
                    tray.ActivationReason.Trigger
                )
                showWindow.assert_called_once_with()

                tray.onTrayIconClick(tray.ActivationReason.Context)
                self.assertEqual(showMenu.call_count, 1)
        finally:
            tray.deleteLater()

    def testTrayMenusUseTouchSizedRows(self):
        cfg.set(cfg.trayHomeCardsInSubmenu, True)
        tray = self._createTray()
        try:
            self.assertEqual(tray.menu.itemHeight, 44)
            self.assertTrue(QScroller.hasScroller(tray.menu.view.viewport()))
            submenu = tray.menu.findChildren(RoundMenu)[0]
            self.assertEqual(submenu.itemHeight, 44)
            self.assertTrue(QScroller.hasScroller(submenu.view.viewport()))
        finally:
            tray.deleteLater()

    def testClickingSubmenuEntryOpensItForTouchUsers(self):
        cfg.set(cfg.trayHomeCardsInSubmenu, True)
        tray = self._createTray()
        tray.menu.show()
        self.app.processEvents()
        try:
            submenu = tray.menu.findChildren(RoundMenu)[0]
            item = next(
                tray.menu.view.item(index)
                for index in range(tray.menu.view.count())
                if tray.menu.view.item(index).data(Qt.ItemDataRole.UserRole) is submenu
            )
            widget = tray.menu.view.itemWidget(item)
            with patch.object(submenu, "exec") as showSubmenu:
                device = QTest.createTouchDevice(
                    QInputDevice.DeviceType.TouchScreen
                )
                position = widget.rect().center()
                QTest.touchEvent(widget, device).press(0, position, widget).commit()
                QTest.touchEvent(widget, device).release(0, position, widget).commit()
                self.app.processEvents()
                showSubmenu.assert_called_once()
        finally:
            tray.menu.hide()
            tray.deleteLater()

    def testHoveringSubmenuEntryOpensItAfterMenuDelay(self):
        cfg.set(cfg.trayHomeCardsInSubmenu, True)
        tray = self._createTray()
        tray.menu.show()
        self.app.processEvents()
        try:
            submenu = tray.menu.findChildren(RoundMenu)[0]
            item = next(
                tray.menu.view.item(index)
                for index in range(tray.menu.view.count())
                if tray.menu.view.item(index).data(Qt.ItemDataRole.UserRole) is submenu
            )
            with patch.object(submenu, "exec") as showSubmenu:
                tray.menu._showSubMenu(item)
                QTest.qWait(tray.menu.timer.interval() + 50)
                showSubmenu.assert_called_once()
        finally:
            tray.menu.hide()
            tray.deleteLater()
