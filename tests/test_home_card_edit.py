import os
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
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
            ["全屏投送", "考试倒计时", "定时播报", "定时关机"],
        )
        self.page = HomePage()
        self.page.resize(800, 500)
        self.page.show()
        self.app.processEvents()

    def tearDown(self):
        self.page.close()
        cfg.set(cfg.homeCardOrder, self.cardOrder)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testCardsCanBeReorderedWithoutTouchScrolling(self):
        touchGesture = QScroller.grabbedGesture(self.page.viewport())
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)

        for card in self.page.all_cards.values():
            self.assertTrue(card.deleteButton.isVisible())
            self.assertFalse(card.deleteButton.isEnabled())
            self.assertTrue(
                card.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
            )

        firstCard = self.page.all_cards["全屏投送"]
        lastCard = self.page.all_cards["定时关机"]
        scrollBar = self.page.verticalScrollBar()
        scrollBar.setValue(scrollBar.maximum() // 2)
        scrollPosition = scrollBar.value()
        target = firstCard.mapFromGlobal(
            lastCard.mapToGlobal(lastCard.rect().center())
        )
        touchDevice = QTest.createTouchDevice(
            QInputDevice.DeviceType.TouchScreen
        )
        QTest.touchEvent(firstCard, touchDevice).press(
            0,
            firstCard.rect().center(),
            firstCard,
        ).commit()
        QTest.touchEvent(firstCard, touchDevice).move(
            0,
            target,
            firstCard,
        ).commit()
        QTest.touchEvent(firstCard, touchDevice).release(
            0,
            target,
            firstCard,
        ).commit()
        self.app.processEvents()

        self.assertEqual(
            cfg.homeCardOrder.value,
            ["考试倒计时", "定时播报", "定时关机", "全屏投送"],
        )
        self.assertEqual(scrollBar.value(), scrollPosition)

        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        self.assertEqual(
            QScroller.grabbedGesture(self.page.viewport()),
            touchGesture,
        )
        self.assertFalse(
            firstCard.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        )

        self.page.resize(360, 500)
        self.app.processEvents()
        firstVisibleCard = self.page.all_cards["考试倒计时"]
        secondVisibleCard = self.page.all_cards["定时播报"]
        self.assertEqual(firstVisibleCard.x(), secondVisibleCard.x())
        self.assertGreater(secondVisibleCard.y(), firstVisibleCard.y())
