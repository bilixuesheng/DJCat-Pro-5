"""Touch behaviour Windows stops supplying once Qt synthesizes touch presses.

With ``windows:nomousefromtouch`` (docs/adr/0004) Qt turns an unaccepted touch into
left-button mouse events itself. Two things Windows used to derive from its own mouse
messages are gone: press-and-hold as a right click (Qt drops mouse-triggered
``WM_CONTEXTMENU``), and the title-bar move loop, which follows the system's left button
that Windows never pressed for the finger. A third gap has no known cause: on the touch
screens a tap on a popup's button (the time picker's check mark) lights it up and then
does not click, which offscreen never reproduces, so popup buttons get a safety net.
"""

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QContextMenuEvent, QGuiApplication
from PySide6.QtWidgets import QAbstractButton, QApplication
from shiboken6 import isValid

_SYNTHESIZED_BY_QT = Qt.MouseEventSource.MouseEventSynthesizedByQt


def _isTouchMouse(event) -> bool:
    return event.source() == _SYNTHESIZED_BY_QT


class _TouchLongPress(QObject):
    """Holding a finger still opens the context menu a right click would open.

    The lift that follows reaches the open menu, which ignores a release it never saw
    pressed; with no menu it lands on the widget and clicks as a long mouse press would.
    """

    def __init__(self, application):
        super().__init__(application)
        self.pressPosition = QPoint()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._openContextMenu)
        application.installEventFilter(self)

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType == QEvent.Type.MouseButtonPress:
            # 同一次按压沿父链传播时过滤器会看到多次，只在第一次起算。
            if (
                _isTouchMouse(event)
                and event.button() == Qt.MouseButton.LeftButton
                and not self.timer.isActive()
            ):
                self.pressPosition = event.globalPosition().toPoint()
                self.timer.start(
                    QGuiApplication.styleHints().mousePressAndHoldInterval()
                )
        elif self.timer.isActive() and eventType in (
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
            QEvent.Type.MouseButtonRelease,
        ):
            self._followTouch(event)
        return False

    def _followTouch(self, event):
        # 滚动区一旦接管手势，Qt 就不再合成鼠标移动，只能从触控事件里看手指有没有动。
        if event.type() != QEvent.Type.TouchUpdate or not event.points():
            self.timer.stop()
            return
        position = event.points()[0].globalPosition().toPoint()
        if (position - self.pressPosition).manhattanLength() >= QApplication.startDragDistance():
            self.timer.stop()

    def _openContextMenu(self):
        target = QApplication.widgetAt(self.pressPosition)
        if target is not None:
            QApplication.sendEvent(
                target,
                QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    target.mapFromGlobal(self.pressPosition),
                    self.pressPosition,
                ),
            )


class _PopupTouchTap(QObject):
    """Click a popup button the finger pressed and lifted on, if the tap did not.

    Only popups: a popup never scrolls under the finger, whereas in a ``ScrollArea`` a
    lift on the pressed button can follow a scroll that must not click it.
    """

    def __init__(self, application):
        super().__init__(application)
        self.button = None
        self.clicked = False
        self.liftPosition = QPoint()
        application.installEventFilter(self)

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType == QEvent.Type.MouseButtonPress:
            self._followPress(obj, event)
        elif self.button is not None and eventType in (
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        ):
            if event.points():
                self.liftPosition = event.points()[0].globalPosition().toPoint()
            if eventType != QEvent.Type.TouchUpdate:
                # Qt 在抬手的触控事件之后才同步合成松开，排到事件循环里再看点没点上。
                QTimer.singleShot(0, self._settle)
        return False

    def _followPress(self, obj, event):
        popup = QApplication.activePopupWidget()
        if (
            not _isTouchMouse(event)
            or event.button() != Qt.MouseButton.LeftButton
            or not isinstance(obj, QAbstractButton)
            or popup is None
            or obj.window() is not popup
        ):
            return
        self._release()
        self.button = obj
        self.clicked = False
        self.liftPosition = event.globalPosition().toPoint()
        obj.clicked.connect(self._markClicked)

    def _markClicked(self):
        self.clicked = True

    def _settle(self):
        button = self.button
        clicked = self.clicked
        self._release()
        if (
            button is None
            or clicked
            or not isValid(button)
            or not button.isVisible()
            or not button.isEnabled()
            or not button.rect().contains(button.mapFromGlobal(self.liftPosition))
        ):
            return
        button.setDown(False)
        button.click()

    def _release(self):
        if self.button is not None and isValid(self.button):
            self.button.clicked.disconnect(self._markClicked)
        self.button = None


def enableTouchInput(application) -> None:
    """Install the application-wide touch fixes: long press and popup taps; idempotent."""
    if getattr(application, "_djcatTouchInput", None) is None:
        application._djcatTouchInput = (
            _TouchLongPress(application),
            _PopupTouchTap(application),
        )


class _TouchTitleBarDrag(QObject):
    """Drag the window by hand when a finger drags the title bar.

    qframelesswindow hands title-bar drags to the system move loop, which gives up at
    once for a finger. Mouse drags keep the system loop and its snapping. The window
    gets no WM_ENTERSIZEMOVE / WM_EXITSIZEMOVE for a finger drag, so the drag reports
    its own start and end.
    """

    moveStarted = Signal()
    moveFinished = Signal()

    def __init__(self, titleBar):
        super().__init__(titleBar)
        self.titleBar = titleBar
        self.pressPosition = None
        self.grabOffset = None
        titleBar.installEventFilter(self)

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonRelease,
        ) or not _isTouchMouse(event):
            return False

        position = event.globalPosition().toPoint()
        if eventType == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton or not self.titleBar.canDrag(
                event.position().toPoint()
            ):
                return False
            self.pressPosition = position
            self.grabOffset = None
            return True

        if self.pressPosition is None:
            return False
        if eventType == QEvent.Type.MouseButtonRelease:
            moved = self.grabOffset is not None
            self.pressPosition = None
            self.grabOffset = None
            if moved:
                self.moveFinished.emit()
            return False

        # 标题栏的 mouseMoveEvent 会启动系统移动，触控的移动一律在这里吃掉。
        if self.grabOffset is None:
            if (position - self.pressPosition).manhattanLength() < QApplication.startDragDistance():
                return True
            self.grabOffset = self._grabOffset()
            self.moveStarted.emit()
        self.titleBar.window().move(position - self.grabOffset)
        return True

    def _grabOffset(self) -> QPoint:
        window = self.titleBar.window()
        offset = self.pressPosition - window.pos()
        if not window.isMaximized():
            return offset
        # 与系统拖动一致：最大化时先还原，手指仍按在标题栏同样比例的位置上。
        ratio = offset.x() / max(1, window.width())
        normalWidth = window.normalGeometry().width() or window.width()
        window.showNormal()
        return QPoint(round(ratio * normalWidth), offset.y())


def enableTouchTitleBarDrag(titleBar) -> _TouchTitleBarDrag:
    """Let a finger drag the window by this qframelesswindow title bar."""
    return _TouchTitleBarDrag(titleBar)
