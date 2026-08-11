import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import RoundMenu

from app.common.home_cards import (
    ActionSequenceWorker,
    DEFAULT_HOME_CARD_NAMES,
    execute_action,
    extract_icon_images,
    normalize_custom_cards,
    validate_action,
)
from app.config.cfg import cfg
from app.view.components.home_card_dialog import CustomCardDialog
from app.view.pages.home_page import HomePage


class HomeCustomCardTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_file = cfg.file
        self.card_order = list(cfg.homeCardOrder.value)
        self.visible_defaults = list(cfg.visibleDefaultHomeCards.value)
        self.custom_cards = list(cfg.customHomeCards.value)
        cfg.file = Path(self.temp_dir.name) / "config.json"
        cfg.set(cfg.homeCardOrder, ["全屏投送", "考试倒计时", "定时关机", "定时播报"])
        cfg.set(cfg.visibleDefaultHomeCards, ["全屏投送", "考试倒计时", "定时关机", "定时播报"])
        cfg.set(cfg.customHomeCards, [])
        self.page = HomePage()
        self.page.resize(900, 700)
        self.page.show()
        self.app.processEvents()

    def tearDown(self):
        self.page.close()
        cfg.set(cfg.homeCardOrder, self.card_order)
        cfg.set(cfg.visibleDefaultHomeCards, self.visible_defaults)
        cfg.set(cfg.customHomeCards, self.custom_cards)
        cfg.file = self.config_file
        self.temp_dir.cleanup()

    def testDefaultCardsCanBeRemovedAndRestored(self):
        self.page._removeDefaultCard("全屏投送")
        self.assertNotIn("全屏投送", self.page._card_order)
        self.assertNotIn("全屏投送", cfg.visibleDefaultHomeCards.value)
        self.page._restoreDefaultCard("全屏投送")
        self.assertIn("全屏投送", self.page._card_order)
        self.assertIn("全屏投送", cfg.visibleDefaultHomeCards.value)

    def testNewMenuShowsOnlyMissingDefaultsWithIcons(self):
        visible = list(DEFAULT_HOME_CARD_NAMES[:-1])
        cfg.set(cfg.visibleDefaultHomeCards, visible)
        self.page._renderCards()
        with mock.patch.object(RoundMenu, "exec", autospec=True) as execute:
            self.page._showAddMenu()
        menu = execute.call_args.args[0]
        submenu = menu._subMenus[0]
        self.assertFalse(submenu.icon().isNull())
        self.assertEqual(
            [action.text() for action in submenu.actions()],
            [DEFAULT_HOME_CARD_NAMES[-1]],
        )
        self.assertFalse(submenu.actions()[0].icon().isNull())
        self.assertEqual(menu.actions()[0].text(), "自定义")

    def testNewButtonUsesOnlyIconAndMatchesEditButton(self):
        self.assertEqual(self.page.addBtn.text(), "")
        self.assertEqual(self.page.addBtn.size(), self.page.sortBtn.size())

    def testCustomCardPersistsAndUsesStableKey(self):
        data = {
            "id": "custom-one",
            "title": "测试卡片",
            "description": "测试说明",
            "icon": {"type": "fluent", "name": "APPLICATION"},
            "actions": [{"id": "action-one", "type": "delay", "seconds": 1}],
        }
        self.page._addCustomCard(data)
        self.page._renderCards()
        self.page._saveCardOrder()
        self.assertIn("custom:custom-one", self.page._card_order)
        self.assertEqual(cfg.customHomeCards.value[0]["id"], "custom-one")

        second = HomePage()
        try:
            self.assertIn("custom:custom-one", second._card_order)
            self.assertEqual(second._customCardData["custom-one"]["title"], "测试卡片")
        finally:
            second.close()

    def testActionListHasTouchSizedDragHandle(self):
        parent = QWidget()
        parent.resize(900, 700)
        dialog = CustomCardDialog(
            {
                "id": "card",
                "title": "卡片",
                "description": "",
                "icon": {"type": "fluent", "name": "APPLICATION"},
                "actions": [
                    {"id": "one", "type": "delay", "seconds": 1},
                    {"id": "two", "type": "delay", "seconds": 2},
                ],
            },
            parent,
        )
        try:
            self.assertEqual(len(dialog.actionList.rows), 2)
            self.assertGreaterEqual(dialog.actionList.rows[0].dragHandle.width(), 44)
            self.assertTrue(dialog.actionList.rows[0].dragHandle.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents))
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def testActionBodyTouchScrollsWithoutReordering(self):
        parent = QWidget()
        parent.resize(900, 700)
        parent.show()
        dialog = CustomCardDialog(
            {
                "id": "card",
                "title": "卡片",
                "actions": [
                    {"id": str(index), "type": "delay", "seconds": 1}
                    for index in range(20)
                ],
            },
            parent,
        )
        dialog.show()
        self.app.processEvents()
        row = dialog.actionList.rows[0]
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = row.rect().center()
        end = start + QPoint(0, -120)
        QTest.touchEvent(row, device).press(0, start, row).commit()
        self.app.processEvents()
        QTest.touchEvent(row, device).move(0, end, row).commit()
        QTest.qWait(100)
        QTest.touchEvent(row, device).release(0, end, row).commit()
        self.assertGreater(dialog.scrollArea.verticalScrollBar().value(), 0)
        self.assertEqual(dialog.actionList.rows[0].action["id"], "0")
        dialog.deleteLater()
        parent.deleteLater()

    def testSequenceUsesLatestListWithoutRepeatingExecutedActions(self):
        first = {"id": "one", "type": "delay", "seconds": 1}
        second = {"id": "two", "type": "delay", "seconds": 1}
        added = {"id": "three", "type": "delay", "seconds": 1}
        state = {"actions": [first, second]}
        calls = []

        def get_actions(_card_id):
            return state["actions"]

        def fake_execute(action, _cancel):
            calls.append(action["id"])
            if action["id"] == "one":
                state["actions"] = [second, added]
            return None

        worker = ActionSequenceWorker("card", get_actions)
        with mock.patch("app.common.home_cards.execute_action", side_effect=fake_execute):
            worker._run()
        self.assertEqual(calls, ["one", "two", "three"])

    @mock.patch("app.common.home_cards.subprocess.Popen")
    def testCancelStopsWaitingProcess(self, popen):
        process = popen.return_value
        process.poll.return_value = None
        process.wait.return_value = 0
        cancel = threading.Event()
        cancel.set()

        error = execute_action(
            {"type": "program", "target": "demo.exe", "wait": True},
            cancel,
        )

        self.assertIsNone(error)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)

    @mock.patch("app.common.home_cards.subprocess.Popen")
    def testCancelStopsProcessAfterItHasStarted(self, popen):
        process = popen.return_value
        process.poll.return_value = None
        process.wait.return_value = 0
        cancel = mock.Mock()
        cancel.is_set.return_value = False
        cancel.wait.return_value = True

        error = execute_action(
            {"type": "program", "target": "demo.exe", "wait": True},
            cancel,
        )

        self.assertIsNone(error)
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=2)

    def testDeletingPageWhileCardRunsDoesNotDestroyWorkerSignalSource(self):
        page = HomePage()
        page._addCustomCard(
            {
                "id": "running",
                "title": "running",
                "actions": [{"id": "wait", "type": "delay", "seconds": 0.1}],
            }
        )
        page._runCustomCard("running")
        worker = page._customWorkers["running"][0]
        errors = []
        originalHook = threading.excepthook
        threading.excepthook = lambda args: errors.append(args)
        try:
            QTest.qWait(20)
            page.deleteLater()
            self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            worker._thread.join(timeout=2)
        finally:
            threading.excepthook = originalHook

        self.assertFalse(worker._thread.is_alive())
        self.assertEqual(errors, [])

    def testAddMenuIsDeletedAfterClosing(self):
        def closeMenu(menu, *_):
            menu.closedSignal.emit()

        with mock.patch.object(RoundMenu, "exec", closeMenu):
            self.page._showAddMenu()

        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(self.page.findChildren(RoundMenu), [])

    def testNormalizeSkipsInvalidCardsAndRepairsDuplicateActionIds(self):
        cards = normalize_custom_cards(
            [
                {"title": "缺动作"},
                {
                    "id": "card",
                    "title": "有效",
                    "actions": [
                        {"id": "same", "type": "delay", "seconds": 1},
                        {"id": "same", "type": "delay", "seconds": 1},
                    ],
                },
            ]
        )
        self.assertEqual(len(cards), 1)
        self.assertNotEqual(cards[0]["actions"][0]["id"], cards[0]["actions"][1]["id"])

    def testMalformedDefaultAndOrderConfigDoesNotBreakHomePage(self):
        cfg.set(cfg.visibleDefaultHomeCards, [[], DEFAULT_HOME_CARD_NAMES[0]])
        cfg.set(cfg.homeCardOrder, [[], DEFAULT_HOME_CARD_NAMES[0]])
        self.page._renderCards()
        self.assertIn(DEFAULT_HOME_CARD_NAMES[0], self.page._card_order)

    @mock.patch("app.common.home_cards.subprocess.Popen")
    def testProgramArgumentsAreStartedWithoutShell(self, popen):
        popen.return_value.poll.return_value = 0
        error = execute_action(
            {
                "type": "program",
                "target": "demo.exe",
                "arguments": '"two words" --flag',
            },
            threading.Event(),
        )
        self.assertIsNone(error)
        popen.assert_called_once_with(
            ["demo.exe", "two words", "--flag"],
            cwd=None,
        )

    @mock.patch("app.common.home_cards.subprocess.Popen")
    def testShellUsesConfiguredConsoleMode(self, popen):
        popen.return_value.poll.return_value = 0
        error = execute_action(
            {"type": "shell", "command": "echo ready", "show_console": True},
            threading.Event(),
        )
        self.assertIsNone(error)
        self.assertEqual(popen.call_args.kwargs["shell"], True)
        self.assertNotEqual(popen.call_args.kwargs["creationflags"], 0)

    @mock.patch("app.common.home_cards.webbrowser.open", return_value=True)
    def testUrlAddsHttpsWhenMissing(self, open_url):
        self.assertIsNone(
            execute_action({"type": "url", "target": "example.com"}, threading.Event())
        )
        open_url.assert_called_once_with("https://example.com", new=2)

    def testActionValidationRejectsUnsafeUrl(self):
        self.assertIn("HTTP", validate_action({"type": "url", "target": "file:///bad"}))

    @unittest.skipUnless(os.name == "nt", "Windows icon resources are platform-specific")
    def testExtractsMultipleWindowsIcons(self):
        shell32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "shell32.dll"
        if not shell32.exists():
            self.skipTest("shell32.dll not found")
        self.assertGreater(len(extract_icon_images(shell32)), 1)
