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
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(
            cfg.homeCardOrder,
            ["全屏投送", "考试倒计时", "定时关机", "定时播报"],
        )
        self.page = HomePage()
        self.page.resize(800, 500)
        self.page.show()
        QTest.qWait(300)

    def tearDown(self):
        self.page.close()
        cfg.set(cfg.homeCardOrder, self.cardOrder)
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
            self.assertFalse(card.deleteButton.isEnabled())
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
