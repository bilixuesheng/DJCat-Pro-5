import sys

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QScroller,
    QWidget,
)

if sys.platform == "darwin":
    from qfluentwidgets import ScrollArea as FluentScrollArea
else:
    from qfluentwidgets import SmoothScrollArea as FluentScrollArea


# qfluentwidgets 默认 500 ms,滚轮滚一格要缓半秒才停,教室机上尤其像没跟上手。
WHEEL_SCROLL_DURATION_MS = 250


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tuneScrollAnimations()
        QScroller.grabGesture(
            self.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        self._touchScrollGuard = _TouchScrollGuard.instance()

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
