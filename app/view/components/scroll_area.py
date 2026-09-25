import sys
import weakref

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QScroller,
    QScrollerProperties,
    QWidget,
)

if sys.platform == "darwin":
    from qfluentwidgets import ScrollArea as FluentScrollArea
else:
    from qfluentwidgets import SmoothScrollArea as FluentScrollArea


# qfluentwidgets 默认 500 ms,滚轮滚一格要缓半秒才停,教室机上尤其像没跟上手。
WHEEL_SCROLL_DURATION_MS = 250

# DragStartDistance 的单位是米,手指够不到 1000 m,滚动因此永远不会起手。
SUPPRESSED_DRAG_START_DISTANCE = 1000.0


def setTouchScrollSuppressed(viewport, suppressed: bool, restoreDistance=None):
    """Make a grabbed viewport's scroller inert, or bring it back.

    Returns the drag threshold to pass back as ``restoreDistance`` when lifting
    the suppression. Views outside ``ScrollArea`` (Projection body, nested
    scroll areas) use this instead of ``QScroller.ungrabGesture``: releasing and
    re-grabbing is the cycle that leaves stale targets in Qt's gesture manager.
    """
    scroller = QScroller.scroller(viewport)
    scroller.stop()
    properties = scroller.scrollerProperties()
    metric = QScrollerProperties.ScrollMetric.DragStartDistance
    if suppressed:
        # 记下当前值再抬高，恢复时才不会把别处调过的阈值一并抹掉。
        current = properties.scrollMetric(metric)
        if current < SUPPRESSED_DRAG_START_DISTANCE:
            restoreDistance = current
        properties.setScrollMetric(metric, SUPPRESSED_DRAG_START_DISTANCE)
    elif restoreDistance is not None:
        properties.setScrollMetric(metric, restoreDistance)
    scroller.setScrollerProperties(properties)
    return restoreDistance


# 自绘多个可按区域的控件（不是 QAbstractButton）登记在这里，起滑时和按钮一样被取消按压。
_touchPressTargets = weakref.WeakSet()


def registerTouchPressTarget(widget) -> None:
    """Let a custom-painted widget drop its pressed cell when a touch turns into a scroll.

    The widget must provide ``cancelTouchPress()``. Buttons need no registration:
    the guard finds every pressed ``QAbstractButton`` under the scroll area.
    """
    _touchPressTargets.add(widget)


class _TouchScrollGuard(QObject):
    def __init__(self, application):
        super().__init__(application)
        self.activeScrollArea = None
        self.suppressScrollArea = None
        self.touchStart = None
        application.installEventFilter(self)

    @classmethod
    def instance(cls):
        application = QApplication.instance()
        guard = getattr(application, "_djcatTouchScrollGuard", None)
        if guard is None:
            guard = cls(application)
            application._djcatTouchScrollGuard = guard
        return guard

    @staticmethod
    def _scrollAreaFor(obj):
        if not isinstance(obj, QWidget):
            return None
        widget = obj
        while widget is not None:
            if isinstance(widget, QAbstractScrollArea):
                return widget if isinstance(widget, ScrollArea) else None
            widget = widget.parentWidget()
        return None

    @staticmethod
    def _cancelPressedButtons(scrollArea):
        for button in scrollArea.findChildren(QAbstractButton):
            if button.isDown():
                button.setDown(False)
        for target in tuple(_touchPressTargets):
            try:
                if scrollArea.isAncestorOf(target):
                    target.cancelTouchPress()
            except RuntimeError:
                _touchPressTargets.discard(target)

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType == QEvent.Type.TouchBegin:
            self.activeScrollArea = self._scrollAreaFor(obj)
            self.suppressScrollArea = None
            if self.activeScrollArea is not None and event.points():
                self.touchStart = event.points()[0].globalPosition().toPoint()
            else:
                self.touchStart = None
            return False

        if eventType == QEvent.Type.TouchUpdate:
            if (
                self.activeScrollArea is not None
                and self.touchStart is not None
                and event.points()
            ):
                position = event.points()[0].globalPosition().toPoint()
                distance = (position - self.touchStart).manhattanLength()
                if distance >= QApplication.startDragDistance():
                    self.suppressScrollArea = self.activeScrollArea
                    self._cancelPressedButtons(self.activeScrollArea)
            return False

        if eventType in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            activeScrollArea = self.activeScrollArea
            self.activeScrollArea = None
            self.touchStart = None
            if eventType == QEvent.Type.TouchCancel and activeScrollArea is not None:
                self._cancelPressedButtons(activeScrollArea)
            return False

        if eventType not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            return False

        # 过滤器装在 QApplication 上,父链遍历只在真正用得到的两个分支里做。
        scrollArea = self._scrollAreaFor(obj)
        if (
            eventType == QEvent.Type.MouseButtonPress
            and self.activeScrollArea is None
            and event.source() == Qt.MouseEventSource.MouseEventNotSynthesized
            and scrollArea is not None
        ):
            self.suppressScrollArea = None
            return False

        if (
            eventType == QEvent.Type.MouseButtonRelease
            and scrollArea is not None
            and scrollArea is self.suppressScrollArea
        ):
            if self.activeScrollArea is None:
                self.suppressScrollArea = None
            self._cancelPressedButtons(scrollArea)
            event.accept()
            return True

        return False


class ScrollArea(FluentScrollArea):
    def __init__(self, parent=None, grabTouch=True):
        super().__init__(parent)
        self._tuneScrollAnimations()
        self.isTouchGestureGrabbed = False
        self.isTouchScrollSuppressed = False
        # 不在这里碰 QScroller.scroller()：它会顺手建出一个 scroller，
        # 连从不打开、因而从不抓手势的 Section 也会多一个。
        self._dragStartDistance = None
        if grabTouch:
            self.grabTouchGesture()
        self._touchScrollGuard = _TouchScrollGuard.instance()

    def setTouchScrollSuppressed(self, suppressed: bool) -> None:
        """Stop the page scrolling under touch without releasing the gesture.

        A mode that needs touch for something else (card sorting) must not give
        the gesture back and take it again: that is the grab/release cycle which
        leaves stale targets in Qt's gesture manager. Raising the drag threshold
        out of reach makes the scroller inert and is fully reversible.
        """
        if suppressed == self.isTouchScrollSuppressed:
            return
        if not suppressed and self._dragStartDistance is None:
            return
        self._dragStartDistance = setTouchScrollSuppressed(
            self.viewport(),
            suppressed,
            self._dragStartDistance,
        )
        self.isTouchScrollSuppressed = suppressed

    def grabTouchGesture(self):
        """Grab the viewport once, and only once.

        Grabbing and releasing repeatedly leaves Qt's gesture manager holding
        stale targets, which later crashes while an unrelated window is being
        created, so areas that may never be scrolled defer the grab until they
        are shown instead of taking one and giving it back. The bookkeeping is
        per instance because `QScroller.grabbedGesture()` answers with the
        globally registered recognizer type, not with this viewport's state.
        """
        if self.isTouchGestureGrabbed:
            return
        QScroller.grabGesture(
            self.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        self.isTouchGestureGrabbed = True

    def _tuneScrollAnimations(self):
        """Keep qfluentwidgets' smooth-bar animations inside the bar lifetime."""
        delegate = getattr(self, "delegate", None)
        if delegate is None:
            return
        for name in ("vScrollBar", "hScrollBar"):
            bar = getattr(delegate, name, None)
            animation = getattr(bar, "ani", None)
            if animation is None:
                continue
            if animation.parent() is None:
                animation.setParent(bar)
            bar.setScrollAnimation(WHEEL_SCROLL_DURATION_MS)

    def enableTransparentBackground(self):
        self.setStyleSheet("QScrollArea{border: none; background: transparent}")
        self.viewport().setStyleSheet("background: transparent")
