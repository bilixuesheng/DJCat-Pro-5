from math import sqrt
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QImage, QInputDevice, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QScroller,
    QScrollerProperties,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.view.pages.home_page import ActionCard, HomePage
from tests.support import isolateCfg


class HomeCardEditTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
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

    def testCardsCanBeReorderedWithoutTouchScrolling(self):
        self.assertEqual(
            cfg.homeCardOrder.defaultValue,
            [
                "全屏投送",
                "考试倒计时",
                "全屏时钟",
                "定时播报",
                "自动任务",
                "定时关机",
            ],
        )
        self.assertTrue(self.page.isTouchGestureGrabbed)
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)

        for card in (
            self.page.allCards[name] for name in self.page._cardOrder
        ):
            self.assertEqual(card.size().toTuple(), (210, 120))
            self.assertTrue(card.deleteButton.isVisible())
            self.assertTrue(card.deleteButton.isEnabled())
            self.assertTrue(
                card.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
            )

        firstCard = self.page.allCards["全屏投送"]
        targetCard = self.page.allCards["定时关机"]
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
        self.assertTrue(self.page.isTouchGestureGrabbed)
        self.assertFalse(self.page.isTouchScrollSuppressed)
        self.assertFalse(
            firstCard.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        )

    def testEditModeSuppressesTouchScrollWithoutReleasingTheGesture(self):
        area = self.page
        original = QScroller.scroller(area.viewport()).scrollerProperties().scrollMetric(
            QScrollerProperties.ScrollMetric.DragStartDistance
        )

        def dragStartDistance():
            return (
                QScroller.scroller(area.viewport())
                .scrollerProperties()
                .scrollMetric(QScrollerProperties.ScrollMetric.DragStartDistance)
            )

        with patch.object(
            QScroller, "ungrabGesture", wraps=QScroller.ungrabGesture
        ) as ungrab:
            for _ in range(3):
                QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
                self.assertTrue(self.page._editingCards)
                self.assertTrue(area.isTouchScrollSuppressed)
                self.assertGreater(dragStartDistance(), 1.0)

                QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
                self.assertFalse(self.page._editingCards)
                self.assertFalse(area.isTouchScrollSuppressed)
                self.assertEqual(dragStartDistance(), original)

            # 抓了又放的循环会在 Qt 的手势管理器里留下残留，之后建任意窗口都可能崩。
            ungrab.assert_not_called()
        self.assertTrue(area.isTouchGestureGrabbed)

    def testEditAndDeleteButtonsRespondToTouchInEditingMode(self):
        card = self.page.allCards["全屏投送"]
        card.setEditable(True)
        card.setRemovable(True)
        card.setEditing(True)
        editClicks = []
        deleteClicks = []
        card.editButton.clicked.connect(lambda: editClicks.append(True))
        card.deleteButton.clicked.connect(lambda: deleteClicks.append(True))
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)

        for button, clicks in (
            (card.editButton, editClicks),
            (card.deleteButton, deleteClicks),
        ):
            position = button.geometry().center()
            QTest.touchEvent(card, device).press(0, position, card).commit()
            self.app.processEvents()
            QTest.touchEvent(card, device).release(0, position, card).commit()
            self.app.processEvents()
            self.assertEqual(clicks, [True])

        self.assertFalse(self.page.dragPreview.isVisible())

    def testCardPreviewFollowsMouse(self):
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        card = self.page.allCards["全屏投送"]
        targetCard = self.page.allCards["定时关机"]
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
        card = self.page.allCards["全屏投送"]
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
        card = self.page.allCards["全屏投送"]
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))

        QTest.mouseClick(
            card,
            Qt.MouseButton.RightButton,
            pos=card.rect().center(),
        )

        self.assertEqual(clicks, [])

    def testCardTitleAndDescriptionEndWithEllipsis(self):
        card = self.page.allCards["全屏投送"]
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
        card = self.page.allCards["全屏投送"]
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
        card = self.page.allCards["全屏投送"]
        targetCard = self.page.allCards["考试倒计时"]
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
            self.page._cardOrder,
            ["考试倒计时", "全屏投送", "定时关机", "定时播报"],
        )
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=target)

    def testCardsDoNotBounceDuringContinuousMouseDrag(self):
        QTest.mouseClick(self.page.sortBtn, Qt.MouseButton.LeftButton)
        card = self.page.allCards["全屏投送"]
        targetCard = self.page.allCards["考试倒计时"]
        target = targetCard.mapToGlobal(targetCard.rect().center())
        self.page._startCardDrag(
            card,
            card.mapToGlobal(card.rect().center()),
        )

        self.page._moveCard(card, target)
        self.page._moveCard(card, target + QPoint(1, 0))

        self.assertEqual(
            self.page._cardOrder,
            ["考试倒计时", "全屏投送", "定时关机", "定时播报"],
        )

    def testCardDragAutoScrollsNearViewportEdge(self):
        scrollBar = self.page.verticalScrollBar()
        scrollBar.setRange(0, 1000)
        scrollBar.setValue(0)
        card = self.page.allCards["全屏投送"]
        self.page._dragCard = card
        self.page._dragPosition = self.page.viewport().mapToGlobal(
            QPoint(self.page.viewport().width() // 2, self.page.viewport().height() - 1)
        )

        self.page._autoScrollCardDrag()

        self.assertGreater(scrollBar.value(), 0)


class ActionCardOutlineTest(TestCase):
    SCALE = 4

    def setUp(self):
        isolateCfg(self)

    def _render(self, card):
        image = QImage(
            card.size() * self.SCALE,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.setDevicePixelRatio(self.SCALE)
        image.fill(0)
        card.render(image, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        return image.convertToFormat(QImage.Format.Format_ARGB32)

    def testBackgroundAndOutlineShareOneRoundedCorner(self):
        # CardWidget 画底色，ActionCard 再叠一圈描边；两层圆角不同时，底色会从描边外面的角上露出来。
        states = {
            "normal": lambda card: None,
            "hover": lambda card: setattr(card, "isHover", True),
            "editing": lambda card: card.setEditing(True),
        }
        radius = 10
        # 外轮廓距边 1 px、圆角 10，沿 45° 对角线从角上走到它的距离（设备像素）。
        expected = self.SCALE * (1 + radius - radius / sqrt(2))
        for state, apply in states.items():
            card = ActionCard(FIF.EDIT, "全屏投送", "将信息以大字全屏展示")
            self.addCleanup(card.deleteLater)
            apply(card)
            image = self._render(card)
            right, bottom = image.width() - 1, image.height() - 1
            corners = {
                "top-left": (0, 0, 1, 1),
                "top-right": (right, 0, -1, 1),
                "bottom-left": (0, bottom, 1, -1),
                "bottom-right": (right, bottom, -1, -1),
            }
            for corner, (x, y, dx, dy) in corners.items():
                with self.subTest(state=state, corner=corner):
                    diagonal = [
                        image.pixelColor(x + dx * step, y + dy * step)
                        for step in range(int(expected) * 3)
                    ]
                    first = next(
                        step
                        for step, color in enumerate(diagonal)
                        if color.alpha() >= 100
                    )
                    self.assertAlmostEqual(first, expected, delta=1)
                    edge = diagonal[first]
                    interior = diagonal[-1]
                    difference = sum(
                        abs(a - b)
                        for a, b in zip(edge.getRgb(), interior.getRgb())
                    )
                    # 轮廓最外一圈是描边，不是底色。
                    self.assertGreater(difference, 40)
