from unittest import TestCase

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTime
from PySide6.QtGui import QAction, QHoverEvent, QIcon, QInputDevice, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    LineEdit,
    RoundMenu,
    Theme,
    qconfig,
    setTheme,
)
from qfluentwidgets import FluentIcon as FIF

from app.platform.touch_input import (
    enableTouchPressFeedback,
    setTouchPressFeedbackEnabled,
)
from app.view.components.font_picker import FontChoice, FontList
from app.view.components.icon_grid import TOOLTIP_DELAY_MS, IconGrid, IconGridItem
from app.view.components.task_picker import TouchTimePicker
from app.view.shell.tray import buildTrayMenu


def _windowsTouchScreen():
    """A touch screen as Windows reports it: Qt synthesizes no mouse events, because
    Windows sends its own once it has told a tap from a drag or a press-and-hold."""
    return QTest.createTouchDevice(
        QInputDevice.DeviceType.TouchScreen,
        QInputDevice.Capability.Position | QInputDevice.Capability.MouseEmulation,
    )


def _mousePress(pressType, widget, point):
    """Windows' own left press at point, as Qt hands it to the widget."""
    return QMouseEvent(
        pressType,
        QPointF(point),
        QPointF(widget.mapToGlobal(point)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


class TouchPressFeedbackTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        enableTouchPressFeedback(cls.app)

    def setUp(self):
        self.device = _windowsTouchScreen()

    def _show(self, *widgets):
        window = QWidget()
        layout = QVBoxLayout(window)
        for widget in widgets:
            layout.addWidget(widget)
        window.resize(320, 240)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()
        return window

    def _press(self, widget, point=None):
        point = widget.rect().center() if point is None else point
        QTest.touchEvent(widget, self.device).press(0, point, widget).commit()
        self.app.processEvents()
        return point

    def _release(self, widget, point):
        QTest.touchEvent(widget, self.device).release(0, point, widget).commit()
        self.app.processEvents()

    def _clicks(self, button):
        clicks = []
        button.clicked.connect(lambda: clicks.append(True))
        return clicks

    def testButtonLooksPressedWhileTheFingerIsDown(self):
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        self.assertTrue(button.isDown())
        self._release(button, point)

        self.assertFalse(button.isDown())
        self.assertEqual(clicks, [])

    def testWindowsTapAfterTheLiftClicksOnce(self):
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        self._release(button, point)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicks, [True])
        self.assertFalse(button.isDown())

    def testWindowsPressBeforeTheLiftKeepsTheButtonPressed(self):
        # 手指挪过轻点容差后 Windows 当场补发按下；抬手时不能再把按钮复位，否则
        # 随后到来的松开就点不中了。
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=point)
        self._release(button, point)
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicks, [True])

    def testBothTapsOfADoubleTapClick(self):
        # 连点的第二下 Qt 只给控件发双击、不发按下；它同样是 Windows 自己的按下，
        # 抬手时不能把按钮复位。
        button = QPushButton("确定")
        clicks = self._clicks(button)
        self._show(button)

        for pressType in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            point = self._press(button)
            QApplication.sendEvent(button, _mousePress(pressType, button, point))
            self._release(button, point)
            QTest.mouseRelease(button, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(clicks, [True, True])

    def testCardLooksPressedWhileTheFingerIsDown(self):
        card = CardWidget()
        card.setFixedHeight(80)
        self._show(card)

        point = self._press(card)
        self.assertTrue(card.isPressed)
        self._release(card, point)

        self.assertFalse(card.isPressed)

    def testPopupButtonLooksPressedWhileTheFingerIsDown(self):
        picker = TouchTimePicker(showSeconds=True)
        picker.setTime(QTime(6, 30, 30))
        self._show(picker)
        picker._showPanel()
        panel = QApplication.activePopupWidget()
        panel.ani.setCurrentTime(panel.ani.duration())
        self.app.processEvents()
        self.addCleanup(lambda: panel.isVisible() and panel.close())

        point = self._press(panel.yesButton)
        self.assertTrue(panel.yesButton.isDown())
        self._release(panel.yesButton, point)

        self.assertFalse(panel.yesButton.isDown())

    def _mousePressLook(self, widget, point):
        """What ``widget`` shows under a mouse held down at ``point``: hovered and pressed."""
        local = QPointF(point)
        QApplication.sendEvent(
            widget,
            QHoverEvent(
                QEvent.Type.HoverMove, local, QPointF(widget.mapToGlobal(point)), local
            ),
        )
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=point)
        return widget.grab().toImage()

    def _openMenu(self, menu, popup=None):
        # 照真实的样子展开到底：展开途中的遮罩还盖着没露出来的行。
        if popup is None:
            RoundMenu.exec(menu, QPoint(200, 200))
        menu = popup or menu
        self.addCleanup(menu.deleteLater)
        self.addCleanup(menu.close)
        reveal = menu.aniManager.ani
        reveal.setCurrentTime(reveal.duration())
        self.app.processEvents()
        return menu

    def _triggered(self, menu):
        triggered = []
        for action in menu.menuActions():
            action.triggered.connect(lambda checked=False: triggered.append(True))
        return triggered

    def _actionRows(self, menu):
        view = menu.view
        return [
            row
            for row in range(view.count())
            if view.item(row).flags() & Qt.ItemFlag.ItemIsSelectable
        ]

    def _rowPoint(self, menu, row):
        return menu.view.visualItemRect(menu.view.item(row)).center()

    def _assertMenuRowLooksPressedWhileTheFingerIsDown(self, menu):
        # 菜单的行不是按钮：鼠标按住时那一行变成选中，底色变深、文字变淡；手指按住时
        # 一模一样，只是不触发。
        menu = self._openMenu(menu)
        triggered = self._triggered(menu)
        viewport = menu.view.viewport()
        point = self._rowPoint(menu, self._actionRows(menu)[1])
        idle = viewport.grab().toImage()

        self._press(viewport, point)
        held = viewport.grab().toImage()
        self._release(viewport, point)

        self.assertEqual(viewport.grab().toImage(), idle)
        self.assertEqual(triggered, [])
        self.assertEqual(held, self._mousePressLook(viewport, point))

    def _themes(self):
        self.addCleanup(setTheme, qconfig.themeMode.value)
        for theme in (Theme.LIGHT, Theme.DARK):
            setTheme(theme)
            self.app.processEvents()
            yield theme

    def testMenuRowLooksPressedWhileTheFingerIsDown(self):
        for theme in self._themes():
            with self.subTest(theme=theme):
                menu = RoundMenu()
                for text in ("第一项", "第二项", "第三项"):
                    menu.addAction(QAction(text, menu))
                self._assertMenuRowLooksPressedWhileTheFingerIsDown(menu)

    def testTrayMenuRowLooksPressedWhileTheFingerIsDown(self):
        for theme in self._themes():
            with self.subTest(theme=theme):
                self._assertMenuRowLooksPressedWhileTheFingerIsDown(
                    buildTrayMenu([], QIcon()).menu
                )

    def _openDropDown(self, *texts):
        combo = ComboBox()
        combo.addItems(list(texts))
        combo.setCurrentIndex(0)
        self._show(combo)
        combo._showComboMenu()
        return combo, self._openMenu(None, QApplication.activePopupWidget())

    def testDropDownIndicatorFollowsTheFingerAndGoesBackWhenItSlidesOff(self):
        # 鼠标按住下拉菜单的一行时，主题色竖条从当前选项跳到这一行；手指也一样。
        # 手指挪开就不算点按，竖条回到当前选项。
        combo, menu = self._openDropDown("每天", "每周", "每月")
        view = menu.view
        viewport = view.viewport()
        point = self._rowPoint(menu, 2)
        idle = viewport.grab().toImage()

        self._press(viewport, point)
        self.assertEqual(view.currentRow(), 2)
        held = viewport.grab().toImage()
        moved = point + QPoint(0, 15)
        QTest.touchEvent(viewport, self.device).move(0, moved, viewport).commit()
        self.app.processEvents()

        self.assertEqual(view.currentRow(), 0)
        self.assertEqual([view.row(item) for item in view.selectedItems()], [0])
        self.assertEqual(viewport.grab().toImage(), idle)
        self._release(viewport, moved)
        self.assertEqual(combo.currentIndex(), 0)
        self.assertEqual(held, self._mousePressLook(viewport, point))

    def testWindowsTapOnAMenuRowTriggersItOnce(self):
        menu = RoundMenu()
        for text in ("第一项", "第二项"):
            menu.addAction(QAction(text, menu))
        menu = self._openMenu(menu)
        triggered = self._triggered(menu)
        viewport = menu.view.viewport()
        point = self._rowPoint(menu, 1)

        self._press(viewport, point)
        self._release(viewport, point)
        QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(triggered, [True])

    def testWindowsPressBeforeTheLiftKeepsTheMenuRowPressed(self):
        menu = RoundMenu()
        for text in ("第一项", "第二项"):
            menu.addAction(QAction(text, menu))
        menu = self._openMenu(menu)
        triggered = self._triggered(menu)
        viewport = menu.view.viewport()
        point = self._rowPoint(menu, 1)

        self._press(viewport, point)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=point)
        self._release(viewport, point)
        self.assertEqual(menu.view.currentRow(), 1)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=point)

        self.assertEqual(triggered, [True])

    def testDropDownArrowSinksWhileTheFingerIsDownAndSpringsBack(self):
        combo = ComboBox()
        combo.addItems(["每天", "每周"])
        self._show(combo)
        arrow = combo.arrowAni

        point = self._press(combo)
        QTest.qWait(arrow.ani.duration() + 50)
        self.assertEqual(arrow.y, arrow.maxOffset)
        self._release(combo, point)

        # 和鼠标松开一样弹回去。
        self.assertEqual(arrow.ani.endValue(), 0)
        QTest.qWait(arrow.ani.duration() + 50)
        self.assertEqual(arrow.y, 0)
        self.assertFalse(combo.isPressed)
        self.assertIsNone(QApplication.activePopupWidget())

    def testWindowsPressBeforeTheLiftKeepsTheDropDownArrowDown(self):
        combo = ComboBox()
        combo.addItems(["每天", "每周"])
        self._show(combo)
        arrow = combo.arrowAni

        point = self._press(combo)
        QTest.mousePress(combo, Qt.MouseButton.LeftButton, pos=point)
        self._release(combo, point)

        self.assertEqual(arrow.ani.endValue(), arrow.maxOffset)
        self.assertTrue(combo.isPressed)
        QTest.mouseRelease(combo, Qt.MouseButton.LeftButton, pos=point)
        popup = QApplication.activePopupWidget()
        self.assertIsNotNone(popup)
        popup.close()

    def testFontRowLooksPressedWhileTheFingerIsDown(self):
        fonts = FontList()
        fonts.setChoices([FontChoice(str(index), f"字体 {index}", ()) for index in range(3)])
        fonts.setFixedWidth(300)
        clicks = []
        fonts.choiceClicked.connect(clicks.append)
        self._show(fonts)
        point = fonts.rowRect(1).center()
        idle = fonts.grab().toImage()

        self._press(fonts, point)
        held = fonts.grab().toImage()
        self._release(fonts, point)

        self.assertEqual(fonts.grab().toImage(), idle)
        self.assertEqual(clicks, [])
        self.assertEqual(held, self._mousePressLook(fonts, point))

    def testIconCellLooksPressedWhileTheFingerIsDownWithoutATooltip(self):
        grid = IconGrid()
        grid.setItems([IconGridItem(str(index), FIF.ADD, "添加") for index in range(6)])
        grid.setFixedWidth(300)
        clicks = []
        grid.iconClicked.connect(clicks.append)
        self._show(grid)
        point = grid.cellRect(1).center()
        idle = grid.grab().toImage()

        self._press(grid, point)
        QTest.qWait(TOOLTIP_DELAY_MS + 50)
        self.assertEqual(grid.toolTipText(), "")
        held = grid.grab().toImage()
        self._release(grid, point)

        self.assertEqual(grid.grab().toImage(), idle)
        self.assertEqual(clicks, [])
        self.assertEqual(held, self._mousePressLook(grid, point))

    def testMovingTheFingerAwayDropsThePressedLook(self):
        button = QPushButton("确定")
        self._show(button)

        point = self._press(button)
        QTest.touchEvent(button, self.device).move(0, point + QPoint(0, 15), button).commit()
        self.app.processEvents()

        self.assertFalse(button.isDown())
        self._release(button, point + QPoint(0, 15))

    def testAutoRepeatButtonIsLeftAlone(self):
        button = QPushButton("+")
        button.setAutoRepeat(True)
        clicks = self._clicks(button)
        self._show(button)

        point = self._press(button)
        QTest.qWait(button.autoRepeatDelay() + 2 * button.autoRepeatInterval())

        self.assertFalse(button.isDown())
        self.assertEqual(clicks, [])
        self._release(button, point)

    def testWidgetThatHandlesTouchKeepsItsButtonsToItself(self):
        host = QWidget()
        host.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        button = QPushButton("确定", host)
        button.resize(120, 40)
        self._show(host)

        point = self._press(button)

        self.assertFalse(button.isDown())
        self._release(button, point)

    def testHoldingInsideATextBoxKeepsTheSelection(self):
        edit = LineEdit()
        edit.setText("全屏投送标题")
        self._show(edit)
        edit.setSelection(2, 2)

        point = self._press(edit)
        QTest.qWait(300)
        self._release(edit, point)

        self.assertEqual(edit.selectedText(), "投送")


class TouchPressFeedbackSwitchTest(TestCase):
    """「新触控」默认开，可在开发人员选项里停用；停用时按住按钮与 Qt 原样相同，立即生效。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.addCleanup(enableTouchPressFeedback, self.app)
        self.button = QPushButton("确定")
        window = QWidget()
        QVBoxLayout(window).addWidget(self.button)
        window.resize(320, 240)
        window.show()
        self.addCleanup(window.deleteLater)
        self.app.processEvents()

    def _pressedWhileFingerDown(self):
        device = _windowsTouchScreen()
        point = self.button.rect().center()
        QTest.touchEvent(self.button, device).press(0, point, self.button).commit()
        self.app.processEvents()
        pressed = self.button.isDown()
        QTest.touchEvent(self.button, device).release(0, point, self.button).commit()
        self.app.processEvents()
        return pressed

    def testSwitchingOffLeavesTheButtonToWindowsAndBackOnRestoresTheLook(self):
        setTouchPressFeedbackEnabled(self.app, False)
        self.assertFalse(self._pressedWhileFingerDown())

        setTouchPressFeedbackEnabled(self.app, True)
        self.assertTrue(self._pressedWhileFingerDown())
