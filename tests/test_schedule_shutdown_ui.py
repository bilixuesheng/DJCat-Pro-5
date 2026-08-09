import os
from unittest import TestCase
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import (
    QEventPoint,
    QImage,
    QInputDevice,
    QPixmap,
    QTouchEvent,
)
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QScroller,
    QSizePolicy,
    QWidget,
)
from shiboken6 import delete, isValid

from app.view.components.task_picker import TouchTimePicker
from app.view.pages.schedule_page import (
    BroadcastSettingCard,
    ChineseVoiceLoader,
    SchedulePage,
    TaskCard,
    create_task_form,
)
from app.view.pages.shutdown_page import (
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
            self.assertTrue(
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
        device = QTest.createTouchDevice(
            QInputDevice.DeviceType.TouchScreen
        )

        def sendTouch(target, viewport, eventType, state, position):
            globalPosition = QPointF(
                viewport.mapToGlobal(position.toPoint())
            )
            point = QEventPoint(0, state, position, globalPosition)
            event = QTouchEvent(
                eventType,
                device,
                Qt.KeyboardModifier.NoModifier,
                [point],
            )
            QApplication.sendEvent(target, event)

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
                    start = QPointF(viewport.width() // 2, startY)
                    end = start + QPointF(0, deltaY)
                    target = QApplication.widgetAt(
                        viewport.mapToGlobal(start.toPoint())
                    )
                    scrollBar = column.verticalScrollBar()
                    startValue = scrollBar.value()

                    with self.subTest(
                        column=columnIndex,
                        start=startName,
                        direction=direction,
                    ):
                        self.assertIs(target, viewport)
                        sendTouch(
                            target,
                            viewport,
                            QEvent.Type.TouchBegin,
                            QEventPoint.State.Pressed,
                            start,
                        )
                        QTest.qWait(30)
                        sendTouch(
                            target,
                            viewport,
                            QEvent.Type.TouchUpdate,
                            QEventPoint.State.Updated,
                            end,
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
                        sendTouch(
                            target,
                            viewport,
                            QEvent.Type.TouchEnd,
                            QEventPoint.State.Released,
                            end,
                        )
                        scroller.stop()

        column = columns[0]
        column.verticalScrollBar().setValue(
            column.verticalScrollBar().value() + 74
        )
        centeredItem = column.itemAt(column.viewport().rect().center())
        TouchTimePicker._settleColumn(column, QScroller.State.Inactive)
        self.assertIs(column.currentItem(), centeredItem)

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
