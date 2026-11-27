"""Pressed look under a finger, while Windows keeps deciding what the touch means.

Windows turns a touch into mouse messages only once it has told a tap from a drag or a
press-and-hold, so a control under a still finger shows nothing until the lift. Letting
Qt synthesize the press at touch-down instead (``nomousefromtouch``) bypassed Windows'
own handling and broke press-and-hold menus, text selection, title-bar moves and popup
buttons; see docs/adr/0008. So the input stays Windows', and this only paints the
control under the finger the way a held mouse button would, until Windows' own press
takes over or the touch ends.
"""

import math

from PySide6.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QObject,
    QPersistentModelIndex,
    QPointF,
    Qt,
)
from PySide6.QtGui import QHoverEvent, QWindow
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
)
from qfluentwidgets.common.animation import TranslateYAnimation
from qfluentwidgets.components.widgets.menu import MenuActionListWidget
from shiboken6 import isValid

# 微软的触控规范：手指移动 2.7 mm（目标分辨率下约 10 px）以内仍算轻点。
TAP_TOLERANCE = 10

# 按下时自己接住鼠标的控件：鼠标按在它们上面不会按下外层卡片，手指也一样。
_PRESS_CONSUMERS = (QLineEdit, QAbstractSlider, QAbstractSpinBox, QAbstractItemView)


def _isScrollViewport(widget) -> bool:
    parent = widget.parentWidget()
    return isinstance(parent, QAbstractScrollArea) and parent.viewport() is widget


def _handlesTouchItself(widget) -> bool:
    # 横幅、主页编辑态、排序把手自己处理触控和按下态；滚动区视口接触控只为滚动。
    while widget is not None and not widget.isWindow():
        if widget.testAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents) and not (
            _isScrollViewport(widget)
        ):
            return True
        widget = widget.parentWidget()
    return False


def _paintsItsOwnPress(widget) -> bool:
    # 自绘多个可按区域的控件（字体列表、图标格）自己知道手指下是哪一格。
    return callable(getattr(widget, "showTouchPress", None)) and callable(
        getattr(widget, "cancelTouchPress", None)
    )


def _pressable(widget):
    """The widget a mouse press at ``widget`` would land on and push down, if any."""
    while widget is not None:
        if isinstance(widget, MenuActionListWidget):
            # 下拉框、右键菜单、托盘菜单和搜索建议的行不是控件，鼠标按下落在整个视口上。
            return widget.viewport()
        if _paintsItsOwnPress(widget):
            return widget if widget.isEnabled() else None
        if isinstance(widget, QAbstractButton):
            if widget.isEnabled() and not widget.autoRepeat():
                return widget
            return None
        if isinstance(getattr(widget, "isPressed", None), bool):
            return widget if widget.isEnabled() else None
        if widget.isWindow() or isinstance(widget, (_PRESS_CONSUMERS, QAbstractScrollArea)):
            return None
        widget = widget.parentWidget()
    return None


def _isMenuViewport(widget) -> bool:
    return isinstance(widget.parentWidget(), MenuActionListWidget)


def _arrow(widget):
    # 下拉框和下拉按钮的箭头跟着鼠标按下、松开下沉和弹回，不看 isDown／isPressed。
    arrow = getattr(widget, "arrowAni", None)
    return arrow if isinstance(arrow, TranslateYAnimation) else None


def _repaintPressed(widget) -> None:
    if hasattr(widget, "_updateBackgroundColor"):
        widget._updateBackgroundColor()
    else:
        widget.update()


def dropPressedLook(widget) -> None:
    """Take back a button's or card's pressed look as its release would; idempotent.

    For a press whose release will never reach the widget, such as a touch that the
    scroll area turned into a scroll after Windows had already sent the press.
    """
    if isinstance(widget, QAbstractButton) and widget.isDown():
        widget.setDown(False)
    if getattr(widget, "isPressed", None) is True:
        widget.isPressed = False
        _repaintPressed(widget)
    arrow = _arrow(widget)
    if arrow is not None and arrow.ani.endValue() == arrow.maxOffset:
        arrow._onRelease(None)


def _sendHover(viewport, eventType, local, position) -> None:
    QApplication.sendEvent(
        viewport, QHoverEvent(eventType, QPointF(local), QPointF(position), QPointF(local))
    )


def _withoutAutoScroll(view, change) -> None:
    # 鼠标按下选中一行时 Qt 同样关掉自动滚动，按住的行不会被挪走；还原时也不能把
    # 列表滚回原来那一项。
    autoScroll = view.hasAutoScroll()
    view.setAutoScroll(False)
    try:
        change()
    finally:
        view.setAutoScroll(autoScroll)


def _clickFocusTarget(widget):
    # 鼠标按下时 Qt 把焦点交给按下处往外第一个接受点击焦点的控件。
    while widget is not None:
        if widget.isEnabled() and (
            widget.focusPolicy().value & Qt.FocusPolicy.ClickFocus.value
        ):
            return widget
        if widget.isWindow():
            return None
        widget = widget.parentWidget()
    return None


def _takeClickFocus(widget):
    """Move focus as a mouse press on ``widget`` would; returns what gives it back."""
    target = _clickFocusTarget(widget)
    if target is None or target.hasFocus():
        return lambda: None
    previous = QApplication.focusWidget()
    target.setFocus(Qt.FocusReason.MouseFocusReason)

    def giveBack():
        if not isValid(target) or not target.hasFocus():
            return
        # 别的窗口里的焦点不能趁弹出菜单开着时抢回去，菜单关闭时 Qt 自己会还给它。
        if previous is not None and isValid(previous) and previous.window() is target.window():
            previous.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            target.clearFocus()

    return giveBack


def _pressMenuRow(viewport, position):
    view = viewport.parentWidget()
    local = viewport.mapFromGlobal(position)
    # 鼠标按住一行时，它既是悬停的那一行，也是被按下选中的那一行：底色变深，列表拿到
    # 焦点后文字变淡，下拉框的主题色竖条也跳过来。
    _sendHover(viewport, QEvent.Type.HoverMove, local, position)
    giveBackFocus = _takeClickFocus(viewport)
    selection = view.selectionModel()
    index = view.indexAt(local)
    previous = None
    enabled = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    if index.isValid() and (index.flags() & enabled) == enabled:
        previous = (
            QItemSelection(selection.selection()),
            QPersistentModelIndex(selection.currentIndex()),
        )

        def select():
            selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )

        _withoutAutoScroll(view, select)

    def release():
        if not isValid(view):
            return
        if previous is not None:
            selected, current = previous

            def restore():
                selection.select(selected, QItemSelectionModel.SelectionFlag.ClearAndSelect)
                selection.setCurrentIndex(current, QItemSelectionModel.SelectionFlag.NoUpdate)

            _withoutAutoScroll(view, restore)
        giveBackFocus()
        _sendHover(viewport, QEvent.Type.HoverLeave, local, position)

    return release


def _press(widget, position):
    """Paint ``widget`` as a held mouse button at the global ``position`` would.

    Returns what takes the look back. Nothing here emits pressed or clicked.
    """
    if _isMenuViewport(widget):
        return _pressMenuRow(widget, position)
    if _paintsItsOwnPress(widget):
        widget.showTouchPress(widget.mapFromGlobal(position))
        return widget.cancelTouchPress
    if isinstance(widget, QAbstractButton):
        widget.setDown(True)
    if isinstance(getattr(widget, "isPressed", None), bool):
        widget.isPressed = True
        _repaintPressed(widget)
    arrow = _arrow(widget)
    if arrow is not None:
        arrow._onPress(None)
    return lambda: dropPressedLook(widget)


class _TouchPressFeedback(QObject):
    def __init__(self, application):
        super().__init__(application)
        self.target = None
        self.release = None
        self.touchStart = None
        application.installEventFilter(self)

    def eventFilter(self, obj, event):
        eventType = event.type()
        # 触控事件先送到窗口再送到控件；弹出窗口的控件根本收不到，所以只看窗口这一份。
        if isinstance(obj, QWindow):
            if eventType == QEvent.Type.TouchBegin:
                self._begin(event)
            elif self.target is not None and eventType == QEvent.Type.TouchUpdate:
                self._follow(event)
            elif eventType in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
                self._end()
        elif (
            eventType in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
            and obj is self.target
        ):
            # Windows 自己的按下到了，按下态从此归控件本身管。连点的第二下 Qt 只给控件发
            # 双击、不发按下；漏掉它的话抬手时按钮被复位，随后的松开就点不中了。
            self.target = self.release = None
        return False

    def _begin(self, event):
        self._end()
        if not event.points():
            return
        position = event.points()[0].globalPosition().toPoint()
        under = QApplication.widgetAt(position)
        target = _pressable(under)
        if target is None or _handlesTouchItself(under):
            return
        self.target = target
        self.touchStart = position
        self.release = _press(target, position)

    def _follow(self, event):
        if not event.points():
            return
        offset = event.points()[0].globalPosition().toPoint() - self.touchStart
        if math.hypot(offset.x(), offset.y()) > max(
            QApplication.startDragDistance(), TAP_TOLERANCE
        ):
            self._end()

    def _end(self):
        target, release = self.target, self.release
        self.target = self.release = None
        if target is not None and isValid(target):
            release()


def setTouchPressFeedbackEnabled(application, enabled: bool) -> None:
    """Show the control under a finger as pressed until Windows acts, or stop; idempotent.

    Off leaves touch exactly as Qt handles it: a control looks pressed only once
    Windows has turned the touch into a mouse press.
    """
    feedback = getattr(application, "_djcatTouchPressFeedback", None)
    if enabled and feedback is None:
        application._djcatTouchPressFeedback = _TouchPressFeedback(application)
    elif not enabled and feedback is not None:
        application.removeEventFilter(feedback)
        feedback._end()
        feedback.deleteLater()
        application._djcatTouchPressFeedback = None


def enableTouchPressFeedback(application) -> None:
    setTouchPressFeedbackEnabled(application, True)
