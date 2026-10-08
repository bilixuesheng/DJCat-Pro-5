"""Window Transition：Display Window 在全屏、窗口化和 Floating Button 之间切换的快照形变。

为什么用快照而不是逐帧改窗口尺寸，见 docs/adr/0005-window-transition-snapshot.md。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import (
    QCoreApplication,
    QElapsedTimer,
    QEasingCurve,
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from app.config.cfg import cfg
from app.platform.screens import screenFor
from app.platform.shadow_effect import paintSilhouetteShadow
from app.view.components.window_background import (
    WINDOW_SHADOW_ALPHA,
    WINDOW_SHADOW_MARGIN,
    WindowBackground,
)

TRANSITION_DURATION_MS = 250
# 动画层显示后要等系统真正把它摆上屏幕，之后的重画才是同步刷到屏幕的；等不到就照常继续。
_COVER_TIMEOUT_MS = 100
# 真全屏由系统异步改尺寸，等窗口尺寸落定再截终点快照；等不到就按当时的样子截。
_SETTLE_TIMEOUT_MS = 200
_FALLBACK_REFRESH_RATE = 60.0

_IDLE, _COVERING, _SETTLING, _ANIMATING = range(4)


class TransitionSurface(NamedTuple):
    """What one end of a Window Transition looks like on screen.

    ``rect`` is the visible shape inside ``window``; ``snapshot()`` grabs it as it
    is on screen. A shape with ``fill`` is painted as ``fill`` with ``icon``
    centred at its own size while it morphs, and as its snapshot at the ends.
    ``opacity`` is the window opacity the window rests at once the transition
    hands the screen back.
    """

    window: QWidget
    rect: QRect
    radius: float
    shadow: bool = False
    opacity: float = 1.0
    snapshot: Callable[[], QPixmap] | None = None
    fill: QColor | None = None
    icon: QPixmap | None = None


def backgroundSurface(background: WindowBackground) -> TransitionSurface:
    """The card a Display Window shows: its background and everything drawn over it."""
    return TransitionSurface(
        background.window(),
        background.geometry(),
        background.cornerRadius(),
        shadow=background.castsShadow(),
        snapshot=background.grabCard,
    )


class _Look(NamedTuple):
    rect: QRectF
    radius: float
    shadow: float
    opacity: float
    image: QPixmap | None
    fill: QColor | None
    icon: QPixmap | None


def _capture(surface: TransitionSurface) -> _Look:
    window = surface.window
    image = surface.snapshot() if surface.snapshot is not None else None
    return _Look(
        QRectF(QRect(window.mapToGlobal(surface.rect.topLeft()), surface.rect.size())),
        surface.radius,
        1.0 if surface.shadow else 0.0,
        surface.opacity,
        image,
        surface.fill,
        surface.icon,
    )


def _lerp(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


class _TransitionOverlay(QWidget):
    """Transparent topmost layer the shape morphs on while the real windows wait."""

    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.source: _Look | None = None
        self.target: _Look | None = None
        self.progress = 0.0
        self.painted = False

    def setFrame(self, source: _Look, target: _Look, progress: float) -> None:
        dirty = self._bounds()
        self.source, self.target, self.progress = source, target, progress
        # 只重画形状经过的地方：透明层整屏大，每次整屏提交给系统合成太贵。
        self.update(dirty.united(self._bounds()).toAlignedRect())

    def frame(self) -> tuple[QRectF, float, float, float]:
        source, target, progress = self.source, self.target, self.progress
        rect = QRectF(
            _lerp(source.rect.x(), target.rect.x(), progress),
            _lerp(source.rect.y(), target.rect.y(), progress),
            _lerp(source.rect.width(), target.rect.width(), progress),
            _lerp(source.rect.height(), target.rect.height(), progress),
        ).translated(-QPointF(self.pos()))
        radius = min(
            _lerp(source.radius, target.radius, progress),
            rect.width() / 2,
            rect.height() / 2,
        )
        shadow = _lerp(source.shadow, target.shadow, progress)
        opacity = _lerp(source.opacity, target.opacity, progress)
        return rect, radius, shadow, opacity

    def _bounds(self) -> QRectF:
        if self.source is None:
            return QRectF()
        rect = self.frame()[0]
        margin = WINDOW_SHADOW_MARGIN + 1
        return rect.adjusted(-margin, -margin, margin, margin)

    def paintEvent(self, event) -> None:
        if self.source is None:
            self.painted = True
            return
        rect, radius, shadow, opacity = self.frame()
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        shape = QPainterPath()
        shape.addRoundedRect(rect, radius, radius)
        progress = self.progress
        # 两端的快照与真窗口一一对应：自带圆角的抗锯齿，阴影也像真窗口那样整片垫在
        # 不透明的卡片底下。再按圆角裁一次，角上的像素会多抗锯齿一遍，交还真窗口时
        # 四个角跳一下。途中的卡片可能半透明，阴影只画在形状外面。
        ends = progress <= 0 or progress >= 1
        if shadow > 0:
            painter.save()
            if not ends:
                outside = QPainterPath()
                outside.addRect(QRectF(self.rect()))
                painter.setClipPath(outside.subtracted(shape))
            paintSilhouetteShadow(
                painter,
                rect,
                radius,
                WINDOW_SHADOW_MARGIN * self.devicePixelRatioF(),
                WINDOW_SHADOW_ALPHA / 255 * shadow * opacity,
            )
            painter.restore()

        # 两张不透明的画面交叉淡入淡出，合起来的不透明度要恰好是 opacity：先画的
        # 那张按 a、后画的按 b 叠上去，b + a(1 − b) = opacity，后画的权重为 progress。
        above = opacity * progress
        below = 0.0 if above >= 1 else opacity * (1 - progress) / (1 - above)
        self._paintLook(painter, self.source, rect, shape, below, ends)
        self._paintLook(painter, self.target, rect, shape, above, ends)
        painter.end()
        self.painted = True

    @staticmethod
    def _paintLook(
        painter: QPainter,
        look: _Look,
        rect: QRectF,
        shape: QPainterPath,
        opacity: float,
        exact: bool,
    ) -> None:
        if opacity <= 0:
            return
        painter.save()
        painter.setOpacity(opacity)
        if exact and look.image is not None:
            # 两端的快照与真窗口一一对应，自带圆角的抗锯齿：只按矩形裁。
            painter.setClipRect(rect)
            painter.drawPixmap(rect, look.image, QRectF(look.image.rect()))
        elif look.fill is not None:
            # 有底色的形状（Floating Button）途中按底色和图标画：它的快照是圆的，
            # 铺满途中的大矩形会变成一个巨大的圆。
            painter.setClipPath(shape)
            painter.fillRect(rect, look.fill)
            if look.icon is not None:
                target = QRectF(QPointF(), look.icon.deviceIndependentSize())
                target.moveCenter(rect.center())
                painter.drawPixmap(target, look.icon, QRectF(look.icon.rect()))
        elif look.image is not None:
            # 按比例铺满再居中裁切：倒计时从 16:9 变到 600 × 190，拉伸会把字压扁。
            painter.setClipPath(shape)
            size = look.image.deviceIndependentSize()
            scale = max(rect.width() / size.width(), rect.height() / size.height())
            target = QRectF(0, 0, size.width() * scale, size.height() * scale)
            target.moveCenter(rect.center())
            painter.drawPixmap(target, look.image, QRectF(look.image.rect()))
        painter.restore()


class WindowTransition(QObject):
    """Runs Window Transitions for one Display Window, one at a time.

    ``run()`` covers the screen with a snapshot of the source first, applies the
    change underneath once that cover is on screen, keeps the target window
    transparent while the shape morphs, then hands the screen back to it. Input
    during a run is the caller's to ignore: check ``isRunning()``.
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._phase = _IDLE
        self._change: Callable[[], None] | None = None
        self._target: Callable[[], TransitionSurface] | None = None
        self._source: _Look | None = None
        self._overlay: _TransitionOverlay | None = None
        self._easing = QEasingCurve(QEasingCurve.Type.OutCubic)
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._onTick)

    def isRunning(self) -> bool:
        return self._phase != _IDLE

    def run(
        self,
        source: Callable[[], TransitionSurface],
        change: Callable[[], None],
        target: Callable[[], TransitionSurface],
    ) -> None:
        self.finish()
        start = source()
        if not cfg.windowTransitionEnabled.value or not start.window.isVisible():
            change()
            self._rest(target)
            return

        self._source = _capture(start)
        self._change = change
        self._target = target
        overlay = self._ensureOverlay()
        overlay.setGeometry(self._area(start.window, target().window))
        # 先以全透明的样子摆上屏幕：此时真窗口还在，动画层若已画着起点画面，两者的阴影和
        # 抗锯齿边缘会叠深一层。
        overlay.painted = False
        overlay.show()
        overlay.raise_()
        self._phase = _COVERING
        self._clock.restart()
        self._timer.start(1)

    def finish(self) -> None:
        """Jump to the end: apply a change still waiting and hand the screen back."""
        if self._phase == _COVERING:
            self._swap()
        self._stop()

    def cancel(self) -> None:
        """Stop now; a change not applied yet is dropped (the window is closing)."""
        self._change = None
        self._stop()

    def _stop(self) -> None:
        if self._phase == _IDLE:
            return
        self._rest(self._target)
        self._end()

    def _onTick(self) -> None:
        if self._phase == _COVERING:
            if self._overlay.painted or self._clock.elapsed() >= _COVER_TIMEOUT_MS:
                self._swap()
        elif self._phase == _SETTLING:
            if self._settled() or self._clock.elapsed() >= _SETTLE_TIMEOUT_MS:
                self._begin()
        elif self._phase == _ANIMATING:
            elapsed = min(1.0, self._clock.elapsed() / TRANSITION_DURATION_MS)
            if elapsed >= 1.0:
                self._reveal()
                self._end()
            else:
                self._overlay.setFrame(
                    self._overlay.source,
                    self._overlay.target,
                    self._easing.valueForProgress(elapsed),
                )

    def _swap(self) -> None:
        # 动画层已经在屏幕上，重画是同步刷上去的：先画出起点画面，紧接着才让真窗口变透明。
        # 两步之间隔不了几微秒，系统合成刚好落在中间也只是叠深一层，不会露出桌面。
        overlay = self._overlay
        overlay.setFrame(self._source, self._source, 0.0)
        overlay.repaint()
        self._target().window.setWindowOpacity(0.0)
        change, self._change = self._change, None
        self._phase = _SETTLING
        self._clock.restart()
        try:
            change()
        except Exception:
            self._stop()
            raise
        overlay.raise_()
        if self._settled():
            self._begin()

    def _settled(self) -> bool:
        window = self._target().window
        handle = window.windowHandle()
        return window.isVisible() and (handle is None or handle.geometry() == window.geometry())

    def _begin(self) -> None:
        # 切换引起的排版请求还排在事件队列里，先处理掉，终点快照才与真窗口一致。
        QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        target = _capture(self._target())
        self._phase = _ANIMATING
        self._clock.restart()
        self._timer.setInterval(self._frameInterval())
        self._overlay.setFrame(self._source, target, 0.0)

    def _reveal(self) -> None:
        overlay = self._overlay
        overlay.setFrame(overlay.source, overlay.target, 1.0)
        # 末帧先画到屏幕上，真窗口再现身，紧接着 _end() 清空动画层：与开头同理，
        # 合成落在中间只会叠深一层，不会露出桌面。
        overlay.repaint()
        self._rest(self._target)

    def _end(self) -> None:
        self._timer.stop()
        self._phase = _IDLE
        self._change = None
        self._target = None
        self._source = None
        overlay = self._overlay
        if overlay is not None:
            overlay.source = overlay.target = None
            # 透明窗口藏起来后仍留着最后一帧，下次一显示、还没重画就先亮出来，窗口就在
            # 上一次的位置闪一下。藏之前先刷成全透明。
            if overlay.isVisible():
                overlay.repaint()
            overlay.hide()

    @staticmethod
    def _rest(target: Callable[[], TransitionSurface] | None) -> None:
        if target is None:
            return
        surface = target()
        surface.window.setWindowOpacity(surface.opacity)

    def _ensureOverlay(self) -> _TransitionOverlay:
        if self._overlay is None:
            self._overlay = _TransitionOverlay()
            self.destroyed.connect(self._overlay.deleteLater)
        return self._overlay

    @staticmethod
    def _area(*windows: QWidget) -> QRect:
        area = QRect()
        for screen in QGuiApplication.screens():
            geometry = screen.geometry()
            if any(geometry.intersects(window.frameGeometry()) for window in windows):
                area = area.united(geometry)
        return area if area.isValid() else QGuiApplication.primaryScreen().geometry()

    def _frameInterval(self) -> int:
        # 1 ms 的 Animation Tick 下每帧都把透明层交给系统合成太贵，按屏幕刷新率重画。
        rate = screenFor(self._overlay).refreshRate()
        return max(1, int(1000 / (rate if rate > 0 else _FALLBACK_REFRESH_RATE)))
