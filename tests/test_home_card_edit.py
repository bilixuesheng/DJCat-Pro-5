import os
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScroller

from app.config.cfg import cfg
from app.view.pages.home_page import HomePage


class HomeCardEditTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.cardOrder = list(cfg.homeCardOrder.value)
        self.visibleDefaults = list(cfg.visibleDefaultHomeCards.value)
        self.customCards = list(cfg.customHomeCards.value)
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(
            cfg.homeCardOrder,
            ["全屏投送", "考试倒计时", "定时关机", "定时播报"],
        )
        cfg.set(
            cfg.visibleDefaultHomeCards,
            ["全屏投送", "考试倒计时", "定时关机", "定时播报"],
        )
        cfg.set(cfg.customHomeCards, [])
        self.page = HomePage()
        self.page.resize(800, 500)
        self.page.show()
        QTest.qWait(300)

    def tearDown(self):
        self.page.close()
        cfg.set(cfg.homeCardOrder, self.cardOrder)
        cfg.set(cfg.visibleDefaultHomeCards, self.visibleDefaults)
        cfg.set(cfg.customHomeCards, self.customCards)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testCardsCanBeReorderedWithoutTouchScrolling(self):
        self.assertEqual(
            cfg.homeCardOrder.defaultValue,
            ["全屏投送", "考试倒计时", "定时关机", "定时播报"],
        )
        touchGesture = QScroller.grabbedGesture(self.page.viewport())
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)

        for card in self.page.all_cards.values():
            self.assertEqual(card.size().toTuple(), (210, 120))
            self.assertTrue(card.deleteButton.isVisible())
            self.assertTrue(card.deleteButton.isEnabled())
            self.assertTrue(
                card.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
            )

        firstCard = self.page.all_cards["全屏投送"]
        targetCard = self.page.all_cards["定时关机"]
        targetStart = targetCard.pos()
        scrollBar = self.page.verticalScrollBar()
        scrollBar.setValue(scrollBar.maximum() // 2)
        scrollPosition = scrollBar.value()
        target = firstCard.mapFromGlobal(
            targetCard.mapToGlobal(targetCard.rect().center())
        )
        touchDevice = QTest.createTouchDevice(
            QInputDevice.DeviceType.TouchScreen
        )
        QTest.touchEvent(firstCard, touchDevice).press(
            0,
            firstCard.rect().center(),
            firstCard,
        ).commit()
        self.app.processEvents()
        self.assertTrue(self.page.dragPreview.isVisible())
        self.assertIsNotNone(firstCard.graphicsEffect())
        QTest.touchEvent(firstCard, touchDevice).move(
            0,
            target,
            firstCard,
        ).commit()
        QTest.qWait(300)
        self.assertNotEqual(targetCard.pos(), targetStart)
        QTest.touchEvent(firstCard, touchDevice).release(
            0,
            target,
            firstCard,
        ).commit()
        self.app.processEvents()

        self.assertEqual(
            cfg.homeCardOrder.value,
            ["考试倒计时", "定时关机", "全屏投送", "定时播报"],
        )
        self.assertEqual(scrollBar.value(), scrollPosition)
        self.assertFalse(self.page.dragPreview.isVisible())
        self.assertIsNone(firstCard.graphicsEffect())

        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        self.assertEqual(
            QScroller.grabbedGesture(self.page.viewport()),
            touchGesture,
        )
        self.assertFalse(
            firstCard.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        )

    def testCardPreviewFollowsMouse(self):
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        card = self.page.all_cards["全屏投送"]
        targetCard = self.page.all_cards["定时关机"]
        target = card.mapFromGlobal(
            targetCard.mapToGlobal(targetCard.rect().center())
        )

        QTest.mousePress(
            card,
            Qt.MouseButton.LeftButton,
            pos=card.rect().center(),
        )
        previewStart = self.page.dragPreview.pos()
        QTest.mouseMove(card, target)
        QTest.qWait(300)

        self.assertTrue(self.page.dragPreview.isVisible())
        self.assertNotEqual(self.page.dragPreview.pos(), previewStart)

        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=target)
        self.assertFalse(self.page.dragPreview.isVisible())
        self.assertEqual(
            cfg.homeCardOrder.value,
            ["考试倒计时", "定时关机", "全屏投送", "定时播报"],
        )

    def testCardReleaseOutsideDoesNotClick(self):
        card = self.page.all_cards["全屏投送"]
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))

        QTest.mousePress(
            card,
            Qt.MouseButton.LeftButton,
            pos=card.rect().center(),
        )
        QTest.mouseRelease(
            card,
            Qt.MouseButton.LeftButton,
            pos=QPoint(-20, -20),
        )

        self.assertEqual(clicks, [])

        start = card.rect().center()
        end = start + QPoint(QApplication.startDragDistance() + 1, 0)
        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(card, end)
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=end)

        self.assertEqual(clicks, [])

        QTest.mouseClick(
            card,
            Qt.MouseButton.LeftButton,
            pos=card.rect().center(),
        )

        self.assertEqual(clicks, [True])

    def testCardIgnoresRightClick(self):
        card = self.page.all_cards["全屏投送"]
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))

        QTest.mouseClick(
            card,
            Qt.MouseButton.RightButton,
            pos=card.rect().center(),
        )

        self.assertEqual(clicks, [])

    def testCardTitleAndDescriptionEndWithEllipsis(self):
        card = self.page.all_cards["全屏投送"]
        card.setCardData(
            card.iconWidget.icon,
            "Ghost Downloader 的标题非常非常长",
            "这是一段超过主页卡片两行可用空间的简介，必须在结尾显示省略号而不是把文字硬裁掉。" * 3,
        )
        self.app.processEvents()

        titleLines = card._titleElideFilter.displayLines(card.titleLabel)
        descriptionLines = card._descriptionElideFilter.displayLines(
            card.contentLabel
        )

        self.assertEqual(len(titleLines), 1)
        self.assertTrue(titleLines[0].endswith("…"))
        self.assertEqual(len(descriptionLines), 2)
        self.assertTrue(descriptionLines[-1].endswith("…"))

    def testTouchScrollStartingOnCardDoesNotClick(self):
        self.page.resize(500, 300)
        QTest.qWait(300)
        scrollBar = self.page.verticalScrollBar()
        scrollBar.setValue(300)
        scrollStart = scrollBar.value()
        card = self.page.all_cards["全屏投送"]
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))
        touchDevice = QTest.createTouchDevice(
            QInputDevice.DeviceType.TouchScreen
        )
        start = card.rect().center()
        end = start + QPoint(0, -80)

        QTest.touchEvent(card, touchDevice).press(
            0,
            start,
            card,
        ).commit()
        self.app.processEvents()
        QTest.touchEvent(card, touchDevice).move(
            0,
            end,
            card,
        ).commit()
        QTest.qWait(100)
        QTest.touchEvent(card, touchDevice).release(
            0,
            end,
            card,
        ).commit()
        QTest.qWait(300)

        self.assertGreater(scrollBar.value(), scrollStart)
        self.assertEqual(clicks, [])

    def testCardsShiftBeforePointerFullyEntersTarget(self):
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        card = self.page.all_cards["全屏投送"]
        targetCard = self.page.all_cards["考试倒计时"]
        nearTarget = targetCard.rect().center()
        nearTarget.setX(-24)
        target = card.mapFromGlobal(targetCard.mapToGlobal(nearTarget))

        QTest.mousePress(
            card,
            Qt.MouseButton.LeftButton,
            pos=card.rect().center(),
        )
        QTest.mouseMove(card, target)
        self.app.processEvents()

        self.assertEqual(
            self.page._card_order,
            ["考试倒计时", "全屏投送", "定时关机", "定时播报"],
        )
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=target)

    def testCardsDoNotBounceDuringContinuousMouseDrag(self):
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        card = self.page.all_cards["全屏投送"]
        targetCard = self.page.all_cards["考试倒计时"]
        target = targetCard.mapToGlobal(targetCard.rect().center())
        self.page._startCardDrag(
            card,
            card.mapToGlobal(card.rect().center()),
        )

        self.page._moveCard(card, target)
        self.page._moveCard(card, target + QPoint(1, 0))

        self.assertEqual(
            self.page._card_order,
            ["考试倒计时", "全屏投送", "定时关机", "定时播报"],
        )
