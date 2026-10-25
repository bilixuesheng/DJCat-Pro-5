import sys
import weakref

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QImage, QPainter, QRegion
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QScroller,
    QScrollerProperties,
    QWidget,
)

from qfluentwidgets import CardWidget

if sys.platform == "darwin":
    from qfluentwidgets import ScrollArea as FluentScrollArea
else:
    from qfluentwidgets import SmoothScrollArea as FluentScrollArea


# qfluentwidgets 默认 500 ms,滚轮滚一格要缓半秒才停,教室机上尤其像没跟上手。
WHEEL_SCROLL_DURATION_MS = 250

# DragStartDistance 的单位是米,手指够不到 1000 m,滚动因此永远不会起手。
SUPPRESSED_DRAG_START_DISTANCE = 1000.0

# QFluentWidgets 的竖直悬浮滚动条贴着右边，占最右 13 px（ScrollBar._adjustPos）。
OVERLAY_SCROLL_BAR_WIDTH = 13

_opaqueScrollAreas = weakref.WeakSet()


def _wholePixelStep(ratio: float) -> int:
    """The smallest scroll step that is a whole number of physical pixels: 4 at 125%, 2 at 150%."""
    return next((step for step in (1, 2, 4) if (step * ratio).is_integer()), 1)


def refreshOpaqueScrolling() -> None:
    """Look again at what lies behind every opaque-scrolling area.

    MainWindow calls this after the theme or the Background Effect changes.
    """
    for area in tuple(_opaqueScrollAreas):
        try:
            area._updateBackdrop()
        except RuntimeError:
            _opaqueScrollAreas.discard(area)


def _backdropColor(viewport: QWidget, point: QPoint):
    """What the viewport's ancestors paint at ``point``, children left out."""
    chain = []
    widget = viewport
    while widget is not None:
        chain.append(widget)
        if widget.isWindow():
            break
        widget = widget.parentWidget()
    image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    for widget in reversed(chain):
        origin = viewport.mapTo(widget, point)
        # 只取各层自己画的，不取系统给窗口铺的底：主窗口自己画整窗底色，挂了 Background
        # Effect 时画成全透明，系统底那时也不会显示出来。漏算只会让内容保持透明，不会画错。
        widget.render(
            painter,
            QPoint(),
            QRegion(QRect(origin.x(), origin.y(), 1, 1)),
            QWidget.RenderFlag(0),
        )
    painter.end()
    return image.pixelColor(0, 0)


class _BackdropPainter(QObject):
    """Paints the colour behind the viewport under the scrolled content."""

    def __init__(self, area):
        super().__init__(area)
        self.color = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint and self.color is not None:
            painter = QPainter(obj)
            painter.fillRect(event.rect(), self.color)
            painter.end()
        return False


# 「新滑动触控」的手感，照 Edge 调：甩得越快滑得越远，减速带长尾，到头轻轻回弹。
# 在开发人员选项里停用后一律用 Qt 的默认值，与以前完全相同。
# 速度单位 m/s，减速度 m/s²，滑行距离 = 2v²/(9a)：86 寸大屏上 1.5 m/s 一甩约滑一屏。
_TUNED_TOUCH_SCROLL_METRICS = (
    (QScrollerProperties.ScrollMetric.DragVelocitySmoothingFactor, 1.0),
    (QScrollerProperties.ScrollMetric.MaximumVelocity, 3.0),
    (QScrollerProperties.ScrollMetric.DecelerationFactor, 0.42),
    (QScrollerProperties.ScrollMetric.ScrollingCurve, QEasingCurve(QEasingCurve.Type.OutCubic)),
    (QScrollerProperties.ScrollMetric.OvershootDragDistanceFactor, 0.25),
    (QScrollerProperties.ScrollMetric.OvershootScrollDistanceFactor, 0.1),
    (QScrollerProperties.ScrollMetric.OvershootScrollTime, 0.3),
)
# 起滑距离沿用 Qt 的 5 mm：红外框本身有约 ±2 mm 抖动，再小就容易把轻点当成拖动。
# 大屏报给系统的物理尺寸不一定对，换成逻辑像素后限制在合理范围内。
TUNED_DRAG_START_MM = 5.0
TUNED_DRAG_START_PIXELS = (3.0, 12.0)

_touchScrollViewports = weakref.WeakSet()
_tunedTouchScroll = True


def isTunedTouchScrollEnabled() -> bool:
    return _tunedTouchScroll


def setTunedTouchScrollEnabled(enabled: bool) -> None:
    """Switch every touch-scrollable viewport between Qt's feel and the tuned one."""
    global _tunedTouchScroll
    _tunedTouchScroll = bool(enabled)
    for viewport in tuple(_touchScrollViewports):
        try:
            _applyTouchScrollProfile(viewport)
        except RuntimeError:
            _touchScrollViewports.discard(viewport)


def trackTouchScroller(viewport) -> None:
    """Give a viewport already grabbed for touch the current scroll feel, and keep it in step."""
    _touchScrollViewports.add(viewport)
    _applyTouchScrollProfile(viewport)


def _profileProperties(scroller) -> QScrollerProperties:
    properties = QScrollerProperties()
    if not _tunedTouchScroll:
        return properties
    for metric, value in _TUNED_TOUCH_SCROLL_METRICS:
        properties.setScrollMetric(metric, value)
    pixelsPerMeter = scroller.pixelPerMeter().y()
    if pixelsPerMeter > 0:
        low, high = TUNED_DRAG_START_PIXELS
        pixels = min(max(TUNED_DRAG_START_MM / 1000 * pixelsPerMeter, low), high)
        properties.setScrollMetric(
            QScrollerProperties.ScrollMetric.DragStartDistance,
            pixels / pixelsPerMeter,
        )
    return properties


def _applyTouchScrollProfile(viewport) -> None:
    scroller = QScroller.scroller(viewport)
    metric = QScrollerProperties.ScrollMetric.DragStartDistance
    suppressed = scroller.scrollerProperties().scrollMetric(metric) >= SUPPRESSED_DRAG_START_DISTANCE
    properties = _profileProperties(scroller)
    if suppressed:
        properties.setScrollMetric(metric, SUPPRESSED_DRAG_START_DISTANCE)
    scroller.setScrollerProperties(properties)


def setTouchScrollSuppressed(viewport, suppressed: bool, restoreDistance=None):
    """Make a grabbed viewport's scroller inert, or bring it back.

    Returns the drag threshold to pass back as ``restoreDistance`` when lifting
    the suppression. Views outside ``ScrollArea`` (Projection body, nested
    scroll areas) use this instead of ``QScroller.ungrabGesture``: releasing and
    re-grabbing is the cycle that leaves stale targets in Qt's gesture manager.
    A tracked viewport goes back to its scroll feel's threshold, which may have
    been switched while it was suppressed.
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
    elif viewport in _touchScrollViewports:
        properties.setScrollMetric(metric, _profileProperties(scroller).scrollMetric(metric))
    elif restoreDistance is not None:
        properties.setScrollMetric(metric, restoreDistance)
    scroller.setScrollerProperties(properties)
    return restoreDistance


# 自绘多个可按区域的控件（不是 QAbstractButton）登记在这里，起滑时和按钮一样被取消按压。
_touchPressTargets = weakref.WeakSet()


def registerTouchPressTarget(widget) -> None:
    """Let a custom-painted widget drop its pressed cell when a touch turns into a scroll.

    The widget must provide ``cancelTouchPress()``. Buttons and cards need no
    registration: the guard finds every pressed ``QAbstractButton`` and
    ``CardWidget`` under the scroll area.
    """
    _touchPressTargets.add(widget)


# 拖动本身就是操作的控件（色板、滑块）。从它们上起滑归控件，不滚动、不取消按压、不吞松开。
_touchDragTargets = weakref.WeakSet()


def registerTouchDragTarget(widget) -> None:
    """Give every touch that starts on ``widget`` to the widget instead of the scroll area."""
    _touchDragTargets.add(widget)


def _isTouchDragTarget(widget) -> bool:
    while widget is not None:
        if widget in _touchDragTargets:
            return True
        widget = widget.parentWidget()
    return False


class _TouchScrollGuard(QObject):
    def __init__(self, application):
        super().__init__(application)
        self.activeScrollArea = None
        self.suppressScrollArea = None
        self.dragTargetScrollArea = None
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
    def _cancelPresses(scrollArea):
        for button in scrollArea.findChildren(QAbstractButton):
            if button.isDown():
                button.setDown(False)
        # 卡片的按下态只有松开能复位，而起滑后的那次松开会被这里吞掉。
        for card in scrollArea.findChildren(CardWidget):
            if card.isPressed:
                card.isPressed = False
                card._updateBackgroundColor()
        for target in tuple(_touchPressTargets):
            try:
                if scrollArea.isAncestorOf(target):
                    target.cancelTouchPress()
            except RuntimeError:
                _touchPressTargets.discard(target)

    def scrollStarted(self, scrollArea):
        # 「新滑动触控」：页面一动就不再算点按，没动就照常点击。不再自己量距离，
        # 以免和 QScroller 的起滑距离对不上，出现按钮已经弹起、页面却还没动的空档。
        if _tunedTouchScroll and scrollArea is self.activeScrollArea:
            self.suppressScrollArea = scrollArea
            self._cancelPresses(scrollArea)

    def _yieldToDragTarget(self):
        # 触控先经手势管理器再到这里，scroller 已记下按下；抬高阈值时顺带把它停掉。
        scrollArea = self.activeScrollArea
        self.activeScrollArea = None
        self.touchStart = None
        if not scrollArea.isTouchScrollSuppressed:
            scrollArea.setTouchScrollSuppressed(True)
            self.dragTargetScrollArea = scrollArea

    def _restoreAfterDragTarget(self):
        scrollArea = self.dragTargetScrollArea
        self.dragTargetScrollArea = None
        if scrollArea is None:
            return
        try:
            scrollArea.setTouchScrollSuppressed(False)
        except RuntimeError:
            pass

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType == QEvent.Type.TouchBegin:
            self._restoreAfterDragTarget()
            self.activeScrollArea = self._scrollAreaFor(obj)
            self.suppressScrollArea = None
            if self.activeScrollArea is not None and event.points():
                self.touchStart = event.points()[0].globalPosition().toPoint()
            else:
                self.touchStart = None
            if self.touchStart is not None and _isTouchDragTarget(
                QApplication.widgetAt(self.touchStart)
            ):
                self._yieldToDragTarget()
            return False

        if eventType == QEvent.Type.TouchUpdate:
            if (
                not _tunedTouchScroll
                and self.activeScrollArea is not None
                and self.touchStart is not None
                and event.points()
            ):
                position = event.points()[0].globalPosition().toPoint()
                distance = (position - self.touchStart).manhattanLength()
                if distance >= QApplication.startDragDistance():
                    self.suppressScrollArea = self.activeScrollArea
                    self._cancelPresses(self.activeScrollArea)
            return False

        if eventType in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            activeScrollArea = self.activeScrollArea
            self.activeScrollArea = None
            self.touchStart = None
            self._restoreAfterDragTarget()
            if eventType == QEvent.Type.TouchCancel and activeScrollArea is not None:
                self._cancelPresses(activeScrollArea)
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
            self._cancelPresses(scrollArea)
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
        self._backdropPainter = None
        if grabTouch:
            self.grabTouchGesture()
        self._touchScrollGuard = _TouchScrollGuard.instance()

    def enableOpaqueScrolling(self) -> None:
        """Let Qt move already painted pixels when this area scrolls.

        Qt shifts the content's pixels and paints only the newly exposed strip
        when the scrolled content is opaque and nothing overlaps it; otherwise
        every scroll step repaints the whole viewport and everything behind it.
        The content paints the colour that lies behind it, so it looks the same,
        and the viewport stops short of the overlay scroll bar, giving back as
        much of the content's right margin as it takes. When what lies behind is
        not one solid colour (a Background Effect, a hidden page) the content
        stays transparent and scrolling repaints as before. Call after
        ``setWidget()``.
        """
        if self._backdropPainter is not None:
            return
        margins = self.viewportMargins()
        self.setViewportMargins(
            margins.left(),
            margins.top(),
            margins.right() + OVERLAY_SCROLL_BAR_WIDTH,
            margins.bottom(),
        )
        layout = self.widget().layout()
        if layout is not None:
            margins = layout.contentsMargins()
            layout.setContentsMargins(
                margins.left(),
                margins.top(),
                max(0, margins.right() - OVERLAY_SCROLL_BAR_WIDTH),
                margins.bottom(),
            )
        self._backdropPainter = _BackdropPainter(self)
        self.widget().installEventFilter(self._backdropPainter)
        _opaqueScrollAreas.add(self)
        delegate = getattr(self, "delegate", None)
        if delegate is not None:
            # 只接管滚轮和滚动条：触控（QScroller）直接设原生滚动条，照旧逐像素跟着手指。
            bar = delegate.vScrollBar
            bar.valueChanged.disconnect(self.verticalScrollBar().setValue)
            bar.valueChanged.connect(self._setWholePixelScrollValue)

    def _setWholePixelScrollValue(self, value: int) -> None:
        # Qt 只在位移是整物理像素时平移像素（QBackingStore::scroll），125% 下滚 1 px 是
        # 1.25 个物理像素，就又整块重画了。滚到底时不对齐，否则最后几像素到不了。
        bar = self.verticalScrollBar()
        # 原生滚动条一变，组件库的滚动条就把同一个值发回来；那是触控设的，不改。
        if value == bar.value():
            return
        if value < bar.maximum():
            value -= value % _wholePixelStep(self.devicePixelRatioF())
        bar.setValue(value)

    def _updateBackdrop(self) -> None:
        if self._backdropPainter is None:
            return
        color = self._uniformBackdrop() if self.isVisible() else None
        # 藏着的页面切过来前会被截快照，那时还按透明画，不会带上换主题前的底色。
        self._backdropPainter.color = color
        content = self.widget()
        content.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, color is not None)
        content.update()

    def _uniformBackdrop(self):
        viewport = self.viewport()
        right, bottom = viewport.width() - 2, viewport.height() - 2
        if right < 1 or bottom < 1:
            return None
        points = (
            QPoint(1, 1),
            QPoint(right, 1),
            QPoint(1, bottom),
            QPoint(right, bottom),
            QPoint(right // 2, bottom // 2),
        )
        colors = {_backdropColor(viewport, point).rgba() for point in points}
        if len(colors) != 1:
            return None
        color = _backdropColor(viewport, points[0])
        return color if color.alpha() == 255 else None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._updateBackdrop()

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
        trackTouchScroller(self.viewport())
        QScroller.scroller(self.viewport()).stateChanged.connect(
            self._onScrollerStateChanged
        )

    def _onScrollerStateChanged(self, state) -> None:
        if state == QScroller.State.Dragging:
            self._touchScrollGuard.scrollStarted(self)

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
