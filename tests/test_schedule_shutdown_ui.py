import os
import threading
from unittest import TestCase
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QInputDevice, QPixmap, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QPushButton,
    QScroller,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox
from shiboken6 import delete, isValid

from app.view.components.scroll_area import ScrollArea
from app.view.components.task_picker import TouchTimePicker
from app.view.pages.home_card_task_page import (
    AddHomeCardTaskDialog,
    HomeCardTaskSettingCard,
    create_home_card_task_form,
)
from app.view.pages.schedule_page import (
    AddTaskDialog,
    BroadcastSettingCard,
    ChineseVoiceLoader,
    SchedulePage,
    TaskCard,
    create_task_form,
)
from app.view.pages.shutdown_page import (
    AddShutdownTaskDialog,
    ShutdownSettingCard,
    ShutdownPromptDialog,
    ShutdownPage,
    ShutdownTaskCard,
    create_shutdown_form,
    show_shutdown_prompt,
)


def broadcast_task():
    return {
        "name": "午间播报",
        "time": "12:30:00",
        "weeks": list(range(7)),
        "type": "预设: 12:30报时",
        "content": "",
        "file": "",
        "repeat": 3,
        "volume": 100,
        "enabled": True,
    }


def shutdown_task():
    return {
        "name": "晚间关机",
        "time": "22:30:00",
        "weeks": list(range(7)),
        "notify": True,
        "promptTitle": "Windows 即将关闭你的计算机",
        "promptMessage": "请保存工作",
        "allowSkip": True,
        "waitSeconds": 30,
        "enabled": True,
    }


class ScheduleShutdownUiTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def testPromptPlacesPrimaryShutdownButtonFirst(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        dialog = ShutdownPromptDialog(shutdown_task(), parent)
        self.addCleanup(dialog.deleteLater)

        widgets = [
            dialog.buttonLayout.itemAt(index).widget()
            for index in range(dialog.buttonLayout.count())
        ]
        buttons = [
            widget
            for widget in widgets
            if widget is not dialog.countdownLabel
        ]

        self.assertIs(widgets[0], dialog.countdownLabel)
        self.assertIs(buttons[0], dialog.yesButton)
        self.assertIs(buttons[1], dialog.cancelButton)
        self.assertIs(buttons[2], dialog.skipButton)
        self.assertEqual(dialog.yesButton.text(), "立即关机")

    def testPromptUsesDarkerMask(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        dialog = ShutdownPromptDialog(shutdown_task(), parent)
        self.addCleanup(dialog.deleteLater)

        self.assertIn(
            "rgba(0, 0, 0, 180)",
            dialog.windowMask.styleSheet(),
        )

    def testTaskHeadersIgnoreReleaseAfterDrag(self):
        cards = (TaskCard(broadcast_task()), ShutdownTaskCard(shutdown_task()))
        for card in cards:
            self.addCleanup(card.deleteLater)
            header = card.expandCard.card
            header.resize(600, header.height())
            start = QPoint(120, header.height() // 2)
            end = QPoint(start.x() + QApplication.startDragDistance() + 5, start.y())

            QTest.mousePress(header, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(header, end)
            QTest.mouseRelease(header, Qt.MouseButton.LeftButton, pos=end)

            with self.subTest(card=type(card).__name__):
                self.assertFalse(card.expandCard.isExpand)

    def testTouchDragStartingOnTaskHeaderScrollsOuterPage(self):
        scroll = ScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
        cards = [TaskCard(broadcast_task()) for _ in range(8)]
        for card in cards:
            layout.addWidget(card)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.resize(640, 280)
        scroll.show()
        self.addCleanup(scroll.deleteLater)
        self.app.processEvents()
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)

        header = cards[0].expandCard.card
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = header.rect().center()
        end = start + QPoint(0, -120)
        QTest.touchEvent(header, device).press(0, start, header).commit()
        self.app.processEvents()
        QTest.touchEvent(header, device).move(0, end, header).commit()
        QTest.qWait(100)
        QTest.touchEvent(header, device).release(0, end, header).commit()
        QTest.qWait(200)
        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertFalse(cards[0].expandCard.isExpand)

    def testTouchDragStartingOnButtonDoesNotClickIt(self):
        scroll = ScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
        button = QPushButton("下载")
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        layout.addWidget(button)
        for index in range(20):
            layout.addWidget(QPushButton(str(index)))
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.resize(320, 240)
        scroll.show()
        self.addCleanup(scroll.deleteLater)
        self.app.processEvents()

        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = button.rect().center()
        end = start + QPoint(0, -100)
        QTest.touchEvent(button, device).press(0, start, button).commit()
        self.app.processEvents()
        QTest.touchEvent(button, device).move(0, end, button).commit()
        QTest.qWait(100)
        QTest.touchEvent(button, device).release(0, end, button).commit()
        QTest.qWait(200)

        self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertEqual(clicks, [])
        self.assertFalse(button.isDown())

    def testTouchDragStartingOnComboBoxDoesNotOpenIt(self):
        scroll = ScrollArea()
        content = QWidget()
        layout = QVBoxLayout(content)
        comboBox = ComboBox()
        comboBox.addItems(["第一项", "第二项"])
        layout.addWidget(comboBox)
        for index in range(20):
            layout.addWidget(QPushButton(str(index)))
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.resize(320, 240)
        scroll.show()
        self.addCleanup(scroll.deleteLater)
        self.app.processEvents()

        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = comboBox.rect().center()
        end = start + QPoint(0, -100)
        QTest.touchEvent(comboBox, device).press(0, start, comboBox).commit()
        self.app.processEvents()
        QTest.touchEvent(comboBox, device).move(0, end, comboBox).commit()
        QTest.qWait(100)
        QTest.touchEvent(comboBox, device).release(0, end, comboBox).commit()
        QTest.qWait(200)

        self.assertIsNone(comboBox.dropMenu)
        self.assertFalse(comboBox.isDown())

    def testSmoothScrollBarAnimationsFollowTheirOwner(self):
        scroll = ScrollArea()
        self.addCleanup(scroll.deleteLater)
        delegate = getattr(scroll, "delegate", None)
        if delegate is None:
            self.skipTest("当前平台使用原生滚动条")
        for name in ("vScrollBar", "hScrollBar"):
            bar = getattr(delegate, name)
            self.assertIs(bar.ani.parent(), bar)

    def testTaskHeadersWaitForReleaseAndShowPressedMaterial(self):
        cards = (TaskCard(broadcast_task()), ShutdownTaskCard(shutdown_task()))
        for card in cards:
            self.addCleanup(card.deleteLater)
            card.resize(600, card.sizeHint().height())
            card.show()
            self.app.processEvents()
            header = card.expandCard.card
            start = QPoint(120, header.height() // 2)

            QTest.mousePress(header, Qt.MouseButton.LeftButton, pos=start)
            QTest.qWait(250)
            with self.subTest(card=type(card).__name__):
                self.assertFalse(card.expandCard.isExpand)
                self.assertTrue(card.isPressed)

            QTest.mouseRelease(header, Qt.MouseButton.LeftButton, pos=start)
            self.assertTrue(card.expandCard.isExpand)
            self.assertFalse(card.isPressed)

    def testTaskBodyRevealKeepsHeaderAndIconStationary(self):
        cards = (TaskCard(broadcast_task()), ShutdownTaskCard(shutdown_task()))
        for card in cards:
            self.addCleanup(card.deleteLater)
            card.resize(600, card.sizeHint().height())
            card.show()
            self.app.processEvents()
            expandCard = card.expandCard
            header = expandCard.card
            iconPosition = header.iconLabel.mapTo(card, QPoint())
            headerPosition = header.mapTo(card, QPoint())
            self.assertIsNotNone(expandCard.view.graphicsEffect())

            revealSpy = QSignalSpy(expandCard.revealAnimation.valueChanged)
            expandCard.setExpand(True)
            with self.subTest(card=type(card).__name__, frame="initial"):
                self.assertEqual(expandCard.revealHeight, 0)
                self.assertIsNotNone(expandCard.view.graphicsEffect())

            self.app.processEvents()
            if expandCard.view.graphicsEffect() is not None:
                self.assertTrue(revealSpy.wait(250))
            with self.subTest(card=type(card).__name__, frame="expanding"):
                self.assertIsNone(expandCard.view.graphicsEffect())
                self.assertEqual(header.iconLabel.mapTo(card, QPoint()), iconPosition)
                self.assertEqual(header.mapTo(card, QPoint()), headerPosition)
                self.assertEqual(expandCard.verticalScrollBar().value(), 0)

            QTest.qWait(160)
            expandCard.setExpand(False)
            QTest.qWait(80)
            with self.subTest(card=type(card).__name__, frame="collapsing"):
                self.assertEqual(header.iconLabel.mapTo(card, QPoint()), iconPosition)
                self.assertEqual(header.mapTo(card, QPoint()), headerPosition)
                self.assertEqual(expandCard.verticalScrollBar().value(), 0)

            QTest.qWait(160)
            self.assertIsNotNone(expandCard.view.graphicsEffect())

    def testTaskHeadersStillExpandOnClick(self):
        card = TaskCard(broadcast_task())
        self.addCleanup(card.deleteLater)
        header = card.expandCard.card
        header.resize(600, header.height())

        QTest.mouseClick(
            header,
            Qt.MouseButton.LeftButton,
            pos=QPoint(120, header.height() // 2),
        )

        self.assertTrue(card.expandCard.isExpand)

    def testExpandArrowHasNoHoverBackground(self):
        card = TaskCard(broadcast_task())
        self.addCleanup(card.deleteLater)
        button = card.expandCard.card.expandButton
        normalImage = QPixmap(button.size())
        normalImage.fill(Qt.GlobalColor.transparent)
        button.render(normalImage)

        button.setHover(True)
        hoverImage = QPixmap(button.size())
        hoverImage.fill(Qt.GlobalColor.transparent)
        button.render(hoverImage)

        self.assertEqual(normalImage.toImage(), hoverImage.toImage())

    def testExpandedContentHasHeaderSeparator(self):
        card = TaskCard(broadcast_task())
        self.addCleanup(card.deleteLater)
        card.expandCard.setExpand(True)
        card.expandCard.resize(
            600,
            card.expandCard.card.height() + 20,
        )
        card.expandCard.borderWidget.resize(
            600,
            card.expandCard.card.height() + 20,
        )
        image = QPixmap(card.expandCard.borderWidget.size())
        image.fill(Qt.GlobalColor.transparent)

        card.expandCard.borderWidget.render(image)

        y = card.expandCard.card.height()
        rendered = image.toImage()
        self.assertNotEqual(
            rendered.pixelColor(300, y),
            rendered.pixelColor(300, y - 1),
        )

    def testTaskFormsUseFullWidthRowsWithSeparators(self):
        forms = (
            (*create_task_form(None), BroadcastSettingCard),
            (*create_shutdown_form(None), ShutdownSettingCard),
            (*create_home_card_task_form(None, []), HomeCardTaskSettingCard),
        )
        for form, _, cardType in forms:
            self.addCleanup(form.deleteLater)
            form.resize(700, form.sizeHint().height())
            form.show()
            self.app.processEvents()

            cards = form.findChildren(cardType)
            self.assertGreater(len(cards), 1)
            for card in cards:
                if card.isHidden():
                    continue
                image = QImage(card.size(), QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                card.render(image)
                x = card.width() // 2
                with self.subTest(card=card.titleLabel.text()):
                    self.assertEqual(card.x(), 0)
                    self.assertEqual(card.width(), form.width())
                    self.assertNotEqual(
                        image.pixelColor(x, card.height() - 1),
                        image.pixelColor(x, card.height() - 2),
                    )

    def testNewTaskDialogsPaintSeparateSettingCards(self):
        parent = QWidget()
        parent.resize(900, 700)
        parent.show()
        self.addCleanup(parent.deleteLater)
        dialogs = (
            (AddTaskDialog(parent), BroadcastSettingCard),
            (AddShutdownTaskDialog(parent), ShutdownSettingCard),
            (AddHomeCardTaskDialog([], parent), HomeCardTaskSettingCard),
        )

        for dialog, cardType in dialogs:
            self.addCleanup(dialog.deleteLater)
            dialog.show()
            self.app.processEvents()
            cards = dialog.formWidget.findChildren(cardType)
            self.assertGreater(len(cards), 1)

            for card in cards:
                if card.isHidden():
                    continue
                image = QImage(card.size(), QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                card.render(image)
                y = card.height() // 2

                with self.subTest(
                    dialog=type(dialog).__name__,
                    card=card.titleLabel.text(),
                ):
                    self.assertNotEqual(
                        image.pixelColor(5, y),
                        image.pixelColor(0, y),
                    )

            dialog.close()

    def testTaskFormsStartDirectlyBelowHeader(self):
        cards = (TaskCard(broadcast_task()), ShutdownTaskCard(shutdown_task()))
        for card in cards:
            self.addCleanup(card.deleteLater)
            card.resize(700, card.sizeHint().height())
            card.show()
            card.expandCard.setExpand(True)
            QTest.qWait(card.expandCard.revealAnimation.duration())
            self.app.processEvents()
            firstRow = card.formWidget.layout().itemAt(0).widget()

            with self.subTest(card=type(card).__name__):
                self.assertLessEqual(firstRow.mapTo(card.expandCard, QPoint()).x(), 1)
                self.assertLessEqual(
                    firstRow.mapTo(card.expandCard, QPoint()).y(),
                    card.expandCard.card.height() + 1,
                )

    @patch.object(ChineseVoiceLoader, "start")
    def testEdgeTtsFormKeepsAConstrainedWidth(self, startLoader):
        form, widgets = create_task_form(None)
        self.addCleanup(form.deleteLater)
        defaultWidth = form.minimumSizeHint().width()
        form.resize(560, form.sizeHint().height())

        widgets["typeCombo"].setCurrentText("Edge TTS（需要联网）")
        widgets["voiceLoader"].finished.emit(
            [
                {
                    "label": "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
                    "name": "zh-CN-XiaoxiaoNeural",
                }
            ],
            "",
        )
        QApplication.processEvents()

        self.assertEqual(widgets["voiceCombo"].width(), 260)
        self.assertLessEqual(form.minimumSizeHint().width(), defaultWidth)
        self.assertEqual(
            widgets["voiceCard"].contentLabel.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Ignored,
        )
        startLoader.assert_called_once()

    def testNewAndExistingTaskFormsUseTouchTimePicker(self):
        broadcastForm, broadcastWidgets = create_task_form(None)
        shutdownForm, shutdownWidgets = create_shutdown_form(None)
        broadcastCard = TaskCard(broadcast_task())
        shutdownCard = ShutdownTaskCard(shutdown_task())
        self.addCleanup(broadcastForm.deleteLater)
        self.addCleanup(shutdownForm.deleteLater)
        self.addCleanup(broadcastCard.deleteLater)
        self.addCleanup(shutdownCard.deleteLater)

        self.assertIsInstance(
            broadcastWidgets["timePicker"], TouchTimePicker
        )
        self.assertIsInstance(
            shutdownWidgets["timePicker"], TouchTimePicker
        )
        self.assertIsInstance(
            broadcastCard.formWidgets["timePicker"], TouchTimePicker
        )
        self.assertIsInstance(
            shutdownCard.formWidgets["timePicker"], TouchTimePicker
        )

    def testTimePickerTouchDragStopsRunningSnapAnimation(self):
        picker = TouchTimePicker(showSeconds=True)
        self.addCleanup(picker.deleteLater)

        picker.show()
        QApplication.processEvents()
        picker._showPanel()
        QApplication.processEvents()
        column = picker.findChildren(QAbstractItemView)[0]
        smoothScroll = column.vScrollBar
        smoothScroll.scrollTo(smoothScroll.value() + 74)

        self.assertEqual(
            smoothScroll.ani.state(),
            QAbstractAnimation.State.Running,
        )
        TouchTimePicker._settleColumn(column, QScroller.State.Dragging)
        self.assertEqual(
            smoothScroll.ani.state(),
            QAbstractAnimation.State.Stopped,
        )

        column.window().close()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def testTimePickerPopupColumnsEnableTouchScrolling(self):
        picker = TouchTimePicker(showSeconds=True)
        self.addCleanup(picker.deleteLater)

        picker.show()
        QApplication.processEvents()
        picker._showPanel()
        QApplication.processEvents()
        columns = picker.findChildren(QAbstractItemView)

        self.assertEqual(len(columns), 3)
        for column in columns:
            self.assertTrue(QScroller.hasScroller(column.viewport()))
            self.assertFalse(
                column.viewport().testAttribute(
                    Qt.WidgetAttribute.WA_AcceptTouchEvents
                )
            )

        panel = columns[0].window()
        self.assertTrue(
            panel.itemMaskWidget.testAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents
            )
        )
        panel.ani.setCurrentTime(panel.ani.duration())
        QApplication.processEvents()

        for columnIndex, column in enumerate(columns):
            viewport = column.viewport()
            starts = {
                "top": 70,
                "middle": viewport.height() // 2,
                "bottom": viewport.height() - 70,
            }
            for startName, startY in starts.items():
                for direction, deltaY in (("up", -50), ("down", 50)):
                    scroller = QScroller.scroller(viewport)
                    scroller.stop()
                    QTest.qWait(20)
                    start = QPoint(viewport.width() // 2, startY)
                    end = start + QPoint(0, deltaY)
                    target = QApplication.widgetAt(
                        viewport.mapToGlobal(start)
                    )
                    scrollBar = column.verticalScrollBar()
                    startValue = scrollBar.value()

                    with self.subTest(
                        column=columnIndex,
                        start=startName,
                        direction=direction,
                    ):
                        self.assertIs(target, viewport)
                        QTest.mousePress(
                            target,
                            Qt.MouseButton.LeftButton,
                            pos=start,
                        )
                        QTest.qWait(30)
                        QTest.mouseMove(
                            target,
                            end,
                            delay=30,
                        )
                        QTest.qWait(30)
                        self.assertEqual(
                            scroller.state(),
                            QScroller.State.Dragging,
                        )
                        if deltaY < 0:
                            self.assertGreater(
                                scrollBar.value(),
                                startValue,
                            )
                        else:
                            self.assertLess(
                                scrollBar.value(),
                                startValue,
                            )
                        QTest.mouseRelease(
                            target,
                            Qt.MouseButton.LeftButton,
                            pos=end,
                        )
                        scroller.stop()

        column = columns[0]
        viewport = column.viewport()
        center = viewport.rect().center()
        globalCenter = viewport.mapToGlobal(center)
        startIndex = column.currentIndex()
        QApplication.sendEvent(
            viewport,
            QWheelEvent(
                QPointF(center),
                QPointF(globalCenter),
                QPoint(),
                QPoint(0, -120),
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate,
                False,
            ),
        )
        self.assertEqual(column.currentIndex(), startIndex + 1)

        QTest.qWait(300)
        clickedItem = column.itemAt(center + QPoint(0, 37))
        clickedText = clickedItem.text()
        QTest.mouseClick(
            viewport,
            Qt.MouseButton.LeftButton,
            pos=center + QPoint(0, 37),
        )
        QTest.qWait(300)
        self.assertEqual(column.currentItem().text(), clickedText)
        self.assertIs(column.currentItem(), column.itemAt(center))

        column.verticalScrollBar().setValue(
            column.verticalScrollBar().value() + 74
        )
        TouchTimePicker._settleColumn(column, QScroller.State.Inactive)
        QTest.qWait(300)
        self.assertIs(
            column.currentItem(),
            column.itemAt(column.viewport().rect().center()),
        )

        panel.close()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertFalse(isValid(panel))

    @patch(
        "app.view.pages.schedule_page.load_chinese_voices",
        return_value=[],
    )
    def testVoiceLoaderIgnoresResultAfterOwnerIsDestroyed(self, loadVoices):
        owner = QWidget()
        loader = ChineseVoiceLoader(owner)
        delete(owner)

        loader._load()

        loadVoices.assert_called_once()

    def testVoiceLoadIsSharedAcrossTaskCards(self):
        loaderType = ChineseVoiceLoader
        with loaderType._lock:
            previous = (
                loaderType._loading,
                loaderType._cachedVoices,
                loaderType._waiters,
            )
            loaderType._loading = False
            loaderType._cachedVoices = None
            loaderType._waiters = []
        started = threading.Event()
        release = threading.Event()
        voice = {"name": "zh-CN-XiaoxiaoNeural", "label": "晓晓"}

        def load():
            started.set()
            release.wait(1)
            return [voice]

        first = loaderType()
        second = loaderType()
        self.addCleanup(first.deleteLater)
        self.addCleanup(second.deleteLater)
        firstResult = QSignalSpy(first.finished)
        secondResult = QSignalSpy(second.finished)
        try:
            with patch(
                "app.view.pages.schedule_page.load_chinese_voices",
                side_effect=load,
            ) as loadVoices:
                first.start()
                second.start()
                self.assertTrue(started.wait(1))
                self.assertEqual(loadVoices.call_count, 1)
                release.set()
                self.assertTrue(firstResult.wait(1000))
                if not secondResult:
                    self.assertTrue(secondResult.wait(1000))
                self.assertEqual(loadVoices.call_count, 1)
                self.assertEqual(firstResult.at(0)[0], [voice])
                self.assertEqual(secondResult.at(0)[0], [voice])
        finally:
            release.set()
            if first._thread is not None:
                first._thread.join(1)
            with loaderType._lock:
                (
                    loaderType._loading,
                    loaderType._cachedVoices,
                    loaderType._waiters,
                ) = previous

    def testTaskEditsAreSavedAfterOneDebounce(self):
        cases = (
            (
                SchedulePage,
                broadcast_task(),
                "app.view.pages.schedule_page.cfg.set",
            ),
            (
                ShutdownPage,
                shutdown_task(),
                "app.view.pages.shutdown_page.cfg.set",
            ),
        )
        for pageType, task, setting in cases:
            with self.subTest(page=pageType.__name__), patch.object(
                pageType,
                "_loadTasks",
                lambda page: setattr(page, "current_tasks", []),
            ):
                page = pageType()
                self.addCleanup(page.deleteLater)
                page.current_tasks = [task]
                with patch(setting) as save:
                    page._updateTask(0, task | {"name": "第一次"})
                    page._updateTask(0, task | {"name": "第二次"})
                    save.assert_not_called()
                    QTest.qWait(350)
                    save.assert_called_once()

    @patch("app.view.pages.schedule_page.AddTaskDialog")
    def testClosedBroadcastTaskDialogIsDeleted(self, dialogType):
        page = MagicMock()
        dialog = dialogType.return_value
        dialog.exec.return_value = False

        SchedulePage._addTask(page)

        dialog.deleteLater.assert_called_once_with()

    @patch("app.view.pages.shutdown_page.AddShutdownTaskDialog")
    def testClosedShutdownTaskDialogIsDeleted(self, dialogType):
        page = MagicMock()
        dialog = dialogType.return_value
        dialog.exec.return_value = False

        ShutdownPage._addTask(page)

        dialog.deleteLater.assert_called_once_with()

    @patch("app.view.pages.shutdown_page.ShutdownPromptDialog")
    @patch("app.view.pages.shutdown_page.QWidget")
    def testShutdownPromptReleasesDialogAndOverlay(
        self,
        overlayType,
        dialogType,
    ):
        overlay = overlayType.return_value
        dialog = dialogType.return_value
        dialog.exec.return_value = 2

        result = show_shutdown_prompt(shutdown_task())

        self.assertEqual(result, 2)
        dialog.deleteLater.assert_called_once_with()
        overlay.close.assert_called_once_with()
        overlay.deleteLater.assert_called_once_with()
