import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScroller, QWidget
from qfluentwidgets import (
    RoundMenu,
    ToggleToolButton,
    ToolTipFilter,
    themeColor,
)

from app.common.home_cards import (
    DEFAULT_HOME_CARD_NAMES,
    ActionSequenceWorker,
    execute_action,
    extract_icon_images,
    normalize_custom_cards,
    normalize_pinned_cards,
    validate_action,
)
from app.config.cfg import cfg
from app.view.components.home_card_dialog import (
    ActionEditorDialog,
    CustomCardDialog,
    IconPickerDialog,
)
from app.view.components.scroll_area import ScrollArea
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

    def testRestoringCardImmediatelyRefreshesHomeLayoutHeight(self):
        name = DEFAULT_HOME_CARD_NAMES[-1]
        self.page._removeDefaultCard(name)
        self.app.processEvents()

        self.page._restoreDefaultCard(name)
        QTest.qWait(100)

        expected_height = self.page.flowLayout.heightForWidth(
            self.page.cardsWidget.width()
        )
        self.assertGreaterEqual(self.page.cardsWidget.height(), expected_height)

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
        self.assertEqual(self.page.addBtn.size(), self.page.sortBtn.sizeHint())
        self.assertEqual(self.page.sortBtn.size(), self.page.sortBtn.sizeHint())
        card = self.page.all_cards[DEFAULT_HOME_CARD_NAMES[0]]
        self.assertEqual(card.editButton.size().toTuple(), (24, 24))
        self.assertEqual(card.deleteButton.size().toTuple(), (24, 24))

    def testCustomCardDialogOpensAfterAddMenuCallbackReturns(self):
        with mock.patch.object(RoundMenu, "exec", autospec=True) as execute:
            with mock.patch.object(self.page, "_createCustomCard") as create:
                self.page._showAddMenu()
                menu = execute.call_args.args[0]
                menu.actions()[0].trigger()

                create.assert_not_called()
                self.app.processEvents()
                create.assert_called_once_with()

    def testNewControlsUseFluentTooltips(self):
        card = self.page.all_cards[DEFAULT_HOME_CARD_NAMES[0]]
        for widget in (
            self.page.addBtn,
            self.page.sortBtn,
            card.editButton,
            card.deleteButton,
        ):
            with self.subTest(widget=widget.accessibleName()):
                self.assertTrue(widget.findChildren(ToolTipFilter))

    def testDialogsFitSmallWindowAndUseTouchScrollAreas(self):
        parent = QWidget()
        parent.resize(520, 360)
        parent.show()
        dialogs = (
            ActionEditorDialog(parent=parent),
            CustomCardDialog(parent=parent),
            IconPickerDialog(parent),
        )
        try:
            for dialog in dialogs:
                dialog.show()
                self.app.processEvents()
                with self.subTest(dialog=type(dialog).__name__):
                    self.assertLessEqual(dialog.widget.width(), dialog.width() - 16)
                    self.assertLessEqual(dialog.widget.height(), dialog.height() - 16)
                    self.assertIsInstance(dialog.scrollArea, ScrollArea)
                    self.assertGreater(
                        dialog.scrollArea.verticalScrollBar().maximum(),
                        0,
                    )
                    self.assertGreater(
                        QScroller.grabbedGesture(dialog.scrollArea.viewport()).value,
                        0,
                    )
                    self.assertTrue(dialog.yesButton.isVisible())
                    self.assertTrue(dialog.cancelButton.isVisible())
                    self.assertLessEqual(
                        dialog.buttonGroup.geometry().bottom(),
                        dialog.widget.height(),
                    )
                    if isinstance(dialog, IconPickerDialog):
                        self.assertEqual(
                            dialog.gridWidget.height(),
                            dialog.grid.heightForWidth(
                                dialog.scrollArea.viewport().width() - 8
                            ),
                        )
        finally:
            for dialog in dialogs:
                dialog.deleteLater()
            parent.deleteLater()

    def testCancelledDialogsAreDeleted(self):
        with mock.patch.object(CustomCardDialog, "exec", return_value=0):
            for _ in range(10):
                self.page._createCustomCard()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(self.page.findChildren(CustomCardDialog), [])

        parent = QWidget()
        parent.resize(900, 700)
        dialog = CustomCardDialog(parent=parent)
        with mock.patch.object(IconPickerDialog, "exec", return_value=0):
            for _ in range(10):
                dialog._chooseIcon()
        with mock.patch.object(ActionEditorDialog, "exec", return_value=0):
            for _ in range(10):
                dialog._addAction()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertEqual(parent.findChildren(IconPickerDialog), [])
        self.assertEqual(parent.findChildren(ActionEditorDialog), [])
        dialog.deleteLater()
        parent.deleteLater()

    def testDialogReleasesTouchScrollerBeforeClosing(self):
        parent = QWidget()
        parent.resize(900, 700)
        dialog = CustomCardDialog(parent=parent)
        viewport = dialog.scrollArea.viewport()
        self.assertGreater(QScroller.grabbedGesture(viewport).value, 0)

        with mock.patch.object(
            QScroller,
            "ungrabGesture",
            wraps=QScroller.ungrabGesture,
        ) as ungrab:
            dialog.reject()
            dialog.reject()

        ungrab.assert_called_once_with(viewport)
        dialog.deleteLater()
        parent.deleteLater()

    def testRealDialogAcceptAndRejectCyclesDoNotLeak(self):
        parent = QWidget()
        parent.resize(900, 700)
        parent.show()
        for index in range(3):
            for accepted in (False, True):
                dialog = CustomCardDialog(parent=parent)
                if accepted:
                    dialog.titleEdit.setText(f"card-{index}")
                    dialog.actionList.rows[0].setData(
                        {
                            "id": f"action-{index}",
                            "type": "delay",
                            "seconds": 1,
                        }
                    )
                    QTimer.singleShot(0, dialog.yesButton.click)
                else:
                    QTimer.singleShot(0, dialog.cancelButton.click)
                self.assertEqual(bool(dialog.exec()), accepted)
                dialog.deleteLater()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

        self.assertEqual(parent.findChildren(CustomCardDialog), [])

        for dialog_type in (IconPickerDialog, ActionEditorDialog):
            for _ in range(3):
                dialog = dialog_type(parent=parent)
                QTimer.singleShot(0, dialog.cancelButton.click)
                self.assertFalse(dialog.exec())
                dialog.deleteLater()
                self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
            self.assertEqual(parent.findChildren(dialog_type), [])

        parent.deleteLater()

    def testIconPickerClearsLayoutAndShowsSelectionImmediately(self):
        parent = QWidget()
        parent.resize(900, 700)
        dialog = IconPickerDialog(parent)
        try:
            dialog._selectFluent("ADD")
            self.assertEqual(dialog.previewLabel.text(), "ADD")
            selected = [button for button in dialog._buttons if button.isChecked()]
            self.assertEqual(len(selected), 1)
            self.assertIsInstance(selected[0], ToggleToolButton)
            self.assertIn(
                themeColor().name().lower(),
                selected[0].styleSheet().lower(),
            )
            dialog._clearGrid()
            self.assertEqual(dialog.grid.count(), 0)
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def testIconPickerSeparatesImagesFromIconResources(self):
        parent = QWidget()
        parent.resize(900, 700)
        dialog = IconPickerDialog(parent)
        try:
            self.assertEqual(
                [dialog.sourceCombo.itemText(index) for index in range(3)],
                ["QWF 图标库", "图片文件", "ICO / EXE / DLL"],
            )
            with mock.patch(
                "app.view.components.home_card_dialog.QFileDialog.getOpenFileName",
                return_value=("", ""),
            ) as choose_file:
                dialog.sourceCombo.setCurrentIndex(1)
                dialog._browse()
                image_filter = choose_file.call_args.args[3]
                dialog.sourceCombo.setCurrentIndex(2)
                dialog._browse()
                resource_filter = choose_file.call_args.args[3]
            self.assertIn("*.png", image_filter)
            self.assertNotIn("*.exe", image_filter)
            self.assertIn("*.exe", resource_filter)
            self.assertNotIn("*.png", resource_filter)
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def testCardEditorUsesNativeControlHeights(self):
        parent = QWidget()
        parent.resize(900, 700)
        dialog = CustomCardDialog(parent=parent)
        try:
            dialog.show()
            self.app.processEvents()
            row = dialog.actionList.rows[0]
            for button in (
                dialog.yesButton,
                dialog.cancelButton,
                dialog.iconSelectButton,
                dialog.addActionButton,
            ):
                with self.subTest(button=button):
                    self.assertLess(button.height(), 44)
                    self.assertLess(button.minimumHeight(), button.maximumHeight())
            for button in (row.dragHandle, row.editButton, row.deleteButton):
                with self.subTest(button=button):
                    self.assertEqual(button.minimumHeight(), 44)
                    self.assertEqual(button.maximumHeight(), 44)
        finally:
            dialog.deleteLater()
            parent.deleteLater()

    def testDialogIconControlsUseFluentTooltips(self):
        parent = QWidget()
        parent.resize(900, 700)
        card_dialog = CustomCardDialog(parent=parent)
        icon_dialog = IconPickerDialog(parent)
        try:
            row = card_dialog.actionList.rows[0]
            for widget in (
                card_dialog.iconPreview,
                row.dragHandle,
                row.editButton,
                row.deleteButton,
                icon_dialog._buttons[0],
            ):
                with self.subTest(widget=widget.toolTip()):
                    self.assertTrue(widget.findChildren(ToolTipFilter))
        finally:
            card_dialog.deleteLater()
            icon_dialog.deleteLater()
            parent.deleteLater()

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

        worker = ActionSequenceWorker("card", get_actions)
        with mock.patch("app.common.home_cards.execute_action", side_effect=fake_execute):
            worker._run()
        self.assertEqual(calls, ["one", "two", "three"])

    def testSequenceReportsActionConfigFailureAndFinishes(self):
        def broken(_card_id):
            raise RuntimeError("配置已损坏")

        worker = ActionSequenceWorker("card", broken)
        result = []
        worker.finished.connect(lambda card_id, errors: result.append((card_id, errors)))

        worker._run()

        self.assertEqual(result[0][0], "card")
        self.assertIn("配置已损坏", result[0][1][0])

    @mock.patch("app.common.home_cards.subprocess.Popen")
    def testCancelStopsSequenceWithoutTerminatingUserProcess(self, popen):
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
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    @mock.patch("app.common.home_cards.subprocess.Popen")
    def testCancelAfterLaunchLeavesUserProcessRunning(self, popen):
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
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

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

    def testShutdownUsesOneSharedWorkerDeadline(self):
        workers = [mock.Mock() for _ in range(3)]
        self.page._customWorkers = {"running": workers}

        with mock.patch(
            "app.view.pages.home_page.monotonic",
            side_effect=[10, 10.25, 10.8, 11.2],
        ):
            self.page.shutdown()

        self.assertAlmostEqual(workers[0].wait.call_args.args[0], 0.75)
        self.assertAlmostEqual(workers[1].wait.call_args.args[0], 0.2)
        self.assertEqual(workers[2].wait.call_args.args[0], 0)
        for worker in workers:
            worker.cancel.assert_called_once_with()
            worker.deleteLater.assert_called_once_with()

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

    def testDuplicateCustomCardIdsAreRepairedAndPersisted(self):
        cards = [
            {
                "id": "duplicate",
                "title": title,
                "actions": [{"type": "delay", "seconds": 1}],
            }
            for title in ("第一张", "第二张")
        ]
        cfg.set(cfg.customHomeCards, cards)

        page = HomePage()
        try:
            repairedIds = [item["id"] for item in cfg.customHomeCards.value]
            self.assertEqual(len(set(repairedIds)), 2)
        finally:
            page.close()

        second = HomePage()
        try:
            self.assertEqual(
                set(second._customCardData),
                set(repairedIds),
            )
        finally:
            second.close()

    def testMalformedPinnedCardsAreSkippedWithoutDuplicateWidgets(self):
        valid = {
            "app_id": "7",
            "preset_id": "9",
            "title": "打开应用",
            "action": {"type": "program", "target": "demo.exe"},
        }
        cards = normalize_pinned_cards(
            [None, {"app_id": "broken"}, valid, dict(valid)]
        )

        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0]["app_id"], cards[0]["preset_id"]), (7, 9))
        self.assertEqual(self.page.setApplicationCards([None, valid, dict(valid)]), cards)
        self.assertEqual(
            [key for key in self.page.all_cards if key.startswith("app:")],
            ["app:7:9"],
        )

    def testDirectApplicationPinnedCardUsesReservedZeroPresetId(self):
        cards = normalize_pinned_cards(
            [
                {
                    "app_id": 7,
                    "preset_id": 0,
                    "title": "打开应用",
                    "action": {"type": "program", "target": "demo.exe"},
                }
            ]
        )

        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0]["app_id"], cards[0]["preset_id"]), (7, 0))
        self.page.setApplicationCards(cards)
        self.assertIn("app:7:0", self.page.all_cards)

    def testApplicationCardFallsBackWhenCachedIconWasDeleted(self):
        missingIcon = Path(self.temp_dir.name) / "deleted-cache.png"
        cards = [
            {
                "app_id": 7,
                "preset_id": 0,
                "title": "Ghost Downloader",
                "description": "下载工具",
                "action": {"type": "program", "target": "ghost.exe"},
                "icon_path": str(missingIcon),
            }
        ]

        self.page.setApplicationCards(cards)

        card = self.page.all_cards["app:7:0"]
        self.assertFalse(card.iconWidget.getIcon().isNull())

    def testApplicationCardsStayEditableWhenRefreshedDuringEditing(self):
        self.page._toggleCardEditing()
        self.page.setApplicationCards(
            [
                {
                    "app_id": 7,
                    "preset_id": 0,
                    "title": "打开应用",
                    "action": {"type": "program", "target": "demo.exe"},
                }
            ]
        )

        card = self.page.all_cards["app:7:0"]
        self.assertTrue(card._editing)
        self.assertFalse(card.deleteButton.isHidden())

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
            env=os.environ,
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
        self.assertEqual(
            validate_action({"type": "url", "target": "https://["}),
            "网页地址无效",
        )

    @unittest.skipUnless(os.name == "nt", "Windows icon resources are platform-specific")
    def testExtractsMultipleWindowsIcons(self):
        shell32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "shell32.dll"
        if not shell32.exists():
            self.skipTest("shell32.dll not found")
        self.assertGreater(len(extract_icon_images(shell32)), 1)
