"""Pressed look under a finger, while Windows keeps deciding what the touch means.

Windows turns a touch into mouse messages only once it has told a tap from a drag or a
press-and-hold, so a control under a still finger shows nothing until the lift. Letting
Qt synthesize the press at touch-down instead (``nomousefromtouch``) bypassed Windows'
own handling and broke press-and-hold menus, text selection, title-bar moves and popup
buttons; see docs/adr/0008. So the input stays Windows', and this only paints the
control under the finger as pressed until Windows' own press takes over or the touch
ends.
"""

import math

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSlider,
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
)
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


def _pressable(widget):
    """The control a mouse press at ``widget`` would push down, if any."""
    while widget is not None:
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


def _showPressed(widget, pressed: bool) -> None:
    if isinstance(widget, QAbstractButton):
        # setDown 只改外观，不发 pressed／clicked。
        widget.setDown(pressed)
    if isinstance(getattr(widget, "isPressed", None), bool):
        widget.isPressed = pressed
        if hasattr(widget, "_updateBackgroundColor"):
            widget._updateBackgroundColor()
        else:
            widget.update()


class _TouchPressFeedback(QObject):
    def __init__(self, application):
        super().__init__(application)
        self.target = None
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
        elif eventType == QEvent.Type.MouseButtonPress and obj is self.target:
            # Windows 自己的按下到了，按下态从此归控件本身管。
            self.target = None
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
        _showPressed(target, True)

    def _follow(self, event):
        if not event.points():
            return
        offset = event.points()[0].globalPosition().toPoint() - self.touchStart
        if math.hypot(offset.x(), offset.y()) > max(
            QApplication.startDragDistance(), TAP_TOLERANCE
        ):
            self._end()

    def _end(self):
        target = self.target
        self.target = None
        if target is not None and isValid(target):
            _showPressed(target, False)


def enableTouchPressFeedback(application) -> None:
    """Show the control under a finger as pressed until Windows acts; idempotent."""
    if getattr(application, "_djcatTouchPressFeedback", None) is None:
        application._djcatTouchPressFeedback = _TouchPressFeedback(application)
