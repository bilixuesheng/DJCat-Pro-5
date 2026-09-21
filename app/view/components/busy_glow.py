"""Busy Glow：AI Markdown Conversion 期间环绕输入框的彩色光带。

为什么是自绘而不是 QSS，以及下面那些看着可以删、其实不能删的约束，见
`docs/adr/0002-busy-glow-custom-paint.md`。
"""

from __future__ import annotations

import math
from typing import NamedTuple

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme

from app.platform.dialog_animation import fadeDialogShadow

CORNER_RADIUS = 5  # 与 QFluentWidgets TextEdit 的边框圆角一致
PERIMETER_SAMPLES = 720
GRADIENT_STOP_STRIDE = 12

# 全局 Animation Tick 是 1 ms，但这里一帧是若干次抗锯齿描边，属于必须自己限流的回调。
# 相位仍按真实经过时间算，所以限流只让它少画几帧，不让动画变慢。
FRAME_INTERVAL_MS = 16

ENTRANCE_MS = 700
FLOW_PERIOD_MS = 4000
BREATH_PERIOD_MS = 2600
BREATH_AMPLITUDE = 0.22
FADE_OUT_MS = 320
TAPER_SEGMENTS = 10
TAPER_FRACTION = 0.10  # 每个生长端渐隐段占整条弧的比例

# （笔宽，alpha），从最外最淡的一遍往内。光感来自面积而不是亮度，所以宽的几遍几乎不带 alpha。
_PASSES = ((38, 9), (27, 15), (18, 24), (10, 40), (5.5, 70), (2.4, 120))

# 呼吸同时作用于笔宽和不透明度，合成强度摆幅因此是幅度的平方（约 ±49%）而不是 ±22%。
# 这是刻意的：只改其中一项，光带看着像在缩放或在闪，而不是在呼吸。
_BREATH_PEAK = 1 + BREATH_AMPLITUDE

# 最外一遍在呼吸峰值时的半宽，决定 overlay 要向外让出多少空间。留不够，最外圈晕会被
# overlay 自身的几何裁成直边。
GLOW_MARGIN = math.ceil(max(width for width, _ in _PASSES) * _BREATH_PEAK / 2) + 2

# 蓝 → 靛 → 紫 → 粉 → 橙 → 回蓝。不走满 360° 色相：绕整圈必然经过纯绿纯黄，
# 那两段感知亮度最高，正是"太亮"的来源。
_BAND_STOPS = (
    (0.00, "#0A84FF"),
    (0.22, "#5E5CE6"),
    (0.44, "#BF5AF2"),
    (0.62, "#FF2D92"),
    (0.82, "#FF9F0A"),
    (1.00, "#0A84FF"),
)

_LIGHT_SATURATION = 1.30
_LIGHT_VALUE = 0.68

_COLOR_TABLE_SIZE = 720
_colorTables: dict[bool, list[QColor]] = {}


class _GlowFrame(NamedTuple):
    progress: float
    phase: float
    breath: float
    fade: float


def _bandColor(position: float, dark: bool) -> QColor:
    """光带上 `position` 处的颜色，0 是底边中点。

    浅色配方不是深色配方调暗：光感来自比背景更亮，在接近白的底上做不到，
    所以浅色改为靠比背景更暗来显形。
    """
    position %= 1.0
    for (lo, loName), (hi, hiName) in zip(_BAND_STOPS, _BAND_STOPS[1:]):
        if lo <= position <= hi:
            ratio = (position - lo) / (hi - lo)
            start, end = QColor(loName), QColor(hiName)
            color = QColor(
                round(start.red() + (end.red() - start.red()) * ratio),
                round(start.green() + (end.green() - start.green()) * ratio),
                round(start.blue() + (end.blue() - start.blue()) * ratio),
            )
            break
    else:
        color = QColor(_BAND_STOPS[-1][1])

    if dark:
        return color
    hue, saturation, value, _ = color.getHsv()
    return QColor.fromHsv(
        hue,
        min(255, round(saturation * _LIGHT_SATURATION)),
        round(value * _LIGHT_VALUE),
    )


def _colorTable(dark: bool) -> list[QColor]:
    table = _colorTables.get(dark)
    if table is None:
        table = [
            _bandColor(index / _COLOR_TABLE_SIZE, dark)
            for index in range(_COLOR_TABLE_SIZE)
        ]
        _colorTables[dark] = table
    return table


def _roundedPath(box: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(box, radius, radius)
    return path


def _perimeter(box: QRectF, radius: float):
    """自底边中点起的周长采样点，以及各点归一化的弧长位置。

    按弧长而不是按角度：锥形渐变按角度分配颜色，在扁矩形上会让颜色沿短边飞掠、
    沿长边爬行。
    """
    path = _roundedPath(box, radius)
    points = [
        path.pointAtPercent(index / PERIMETER_SAMPLES)
        for index in range(PERIMETER_SAMPLES + 1)
    ]
    points.pop()  # 100% 处的采样点与 0% 重复

    bottom = QPointF(box.center().x(), box.bottom())
    start = min(
        range(len(points)),
        key=lambda i: (points[i].x() - bottom.x()) ** 2
        + (points[i].y() - bottom.y()) ** 2,
    )
    ordered = points[start:] + points[:start]
    if ordered[1].x() < ordered[0].x():
        # 统一成屏幕坐标下的顺时针，右边中点才落在四分之一处；Qt 自身的绕向不保证跨版本一致。
        ordered = [ordered[0]] + ordered[:0:-1]
    ordered.append(ordered[0])

    lengths, total = [0.0], 0.0
    for previous, current in zip(ordered, ordered[1:]):
        total += math.hypot(current.x() - previous.x(), current.y() - previous.y())
        lengths.append(total)
    return ordered, [length / total for length in lengths]


def _polyline(points, indices) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(points[indices[0]])
    for index in indices[1:]:
        path.lineTo(points[index])
    return path


def _splitTaper(points, indices, segments=TAPER_SEGMENTS):
    """把圆弧拆成满强度的主体，加上两端逐级变淡的短段。

    短段必须从主体里挖掉，不能叠在主体上画：描边是叠加的，盖上去只会让那一端更亮。
    """
    span = max(1, round(len(indices) * TAPER_FRACTION / segments))
    edge = segments * span
    if len(indices) < 2 * edge + 2:
        return _polyline(points, indices), []

    core = _polyline(points, indices[edge : len(indices) - edge])
    stubs = []
    for step in range(segments):
        strength = (step + 1) / (segments + 1)
        head = indices[step * span : (step + 1) * span + 1]
        tail = indices[len(indices) - (step + 1) * span - 1 : len(indices) - step * span]
        stubs.append((_polyline(points, head), strength))
        stubs.append((_polyline(points, tail), strength))
    return core, stubs


def _grownPath(points, fractions, progress: float, box: QRectF, radius: float):
    """已长出的部分：以底边中点为中心的一段连续圆弧。

    把它描述成从底边中点升起的两条臂，两条臂会在起笔点和会合点重叠，alpha 叠加成
    两个亮疙瘩。不要退回两条臂再去调笔帽。
    """
    if progress >= 1.0:
        return _roundedPath(box, radius), []
    if progress <= 0.0 or not points:
        return None, []

    half = progress * 0.5
    indices = [i for i, f in enumerate(fractions) if f >= 1.0 - half]
    indices += [i for i, f in enumerate(fractions) if f <= half]
    if len(indices) < 2:
        return None, []
    return _splitTaper(points, indices)


class BusyGlowOverlay(QWidget):
    """盖在 `target` 上的透明层，用光带环绕它。

    它是 target 的兄弟层而不是子控件，光带因此能同时向框内和框外渗开；它从不接收输入。
    """

    def __init__(self, target: QWidget):
        super().__init__(target.parentWidget())
        self._target = target
        self._box = QRectF()
        self._points: list[QPointF] = []
        self._fractions: list[float] = []
        self._stops: list[tuple[float, float]] = []
        self._ring: QRegion | None = None
        self._cachedSize = None
        self._running = False
        self._stopAtMs: int | None = None
        self._elapsed = QElapsedTimer()
        self._timer = QTimer(self)
        self._bind()
        self._syncGeometry()
        self._rebuild()

    def _bind(self) -> None:
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._onTick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()
        self._target.installEventFilter(self)

    def isRunning(self) -> bool:
        return self._running

    def start(self) -> None:
        # 正在淡出时重新开始（失败后立刻重试）必须取消淡出，否则 _onTick 会把新一轮藏掉。
        if self._running and self._stopAtMs is None:
            return
        self._running = True
        self._stopAtMs = None
        self._elapsed.restart()
        self._syncGeometry()
        self._rebuild()
        self.show()
        self.raise_()
        self._timer.start()
        # 卡片级阴影会因任意子控件重绘而整卡重新模糊，不能在光带重绘期间亮着。
        fadeDialogShadow(self, visible=False)

    def stop(self, immediate: bool = False) -> None:
        if not self._running:
            return
        if immediate:
            self._finish()
        elif self._stopAtMs is None:
            self._stopAtMs = self._elapsed.elapsed()

    def _finish(self) -> None:
        self._running = False
        self._stopAtMs = None
        self._timer.stop()
        self.hide()
        fadeDialogShadow(self, visible=True)

    def eventFilter(self, obj, event):
        if obj is self._target:
            kind = event.type()
            if kind in (QEvent.Type.Resize, QEvent.Type.Move):
                self._syncGeometry()
            elif kind == QEvent.Type.ParentChange:
                # 布局接管控件时 Qt 会重设父对象，兄弟层必须跟着换父对象才不会掉队。
                self.setParent(self._target.parentWidget())
                self._syncGeometry()
                if self._running:
                    self.show()
                    self.raise_()
            elif kind == QEvent.Type.Hide and self._running:
                self.hide()
            elif kind == QEvent.Type.Show and self._running:
                self.show()
                self.raise_()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paintGlow(painter, self._elapsed.elapsed() if self._elapsed.isValid() else 0)
        painter.end()

    def _syncGeometry(self) -> None:
        if self.parentWidget() is None:
            return
        self.setGeometry(
            self._target.geometry().adjusted(
                -GLOW_MARGIN, -GLOW_MARGIN, GLOW_MARGIN, GLOW_MARGIN
            )
        )

    def _ensureCache(self) -> None:
        # 隐藏控件的 resize 事件会被延后，所以缓存不能只靠 resizeEvent 先跑过。
        if self._cachedSize != self.size():
            self._rebuild()

    def _rebuild(self) -> None:
        """所有随几何变化的数据都缓存在这里，一帧只需要转相位。"""
        self._cachedSize = self.size()
        box = QRectF(self.rect()).adjusted(
            GLOW_MARGIN, GLOW_MARGIN, -GLOW_MARGIN, -GLOW_MARGIN
        )
        if box.width() <= 2 * CORNER_RADIUS or box.height() <= 2 * CORNER_RADIUS:
            self._points, self._fractions, self._stops, self._ring = [], [], [], None
            return

        self._box = box
        self._points, self._fractions = _perimeter(box, CORNER_RADIUS)
        center = box.center()
        self._stops = []
        for index in range(0, len(self._points), GRADIENT_STOP_STRIDE):
            point = self._points[index]
            angle = (
                math.degrees(
                    math.atan2(-(point.y() - center.y()), point.x() - center.x())
                )
                % 360
            )
            self._stops.append((min(0.9999, angle / 360.0), self._fractions[index]))

        reach = max(width for width, _ in _PASSES) * _BREATH_PEAK / 2
        outer = box.adjusted(-reach, -reach, reach, reach).toAlignedRect()
        inner = box.adjusted(reach, reach, -reach, -reach).toAlignedRect()
        region = QRegion(outer)
        if inner.width() > 0 and inner.height() > 0:
            region -= QRegion(inner)
        self._ring = region

    def _gradient(self, phase: float) -> QConicalGradient:
        self._ensureCache()
        gradient = QConicalGradient(self._box.center(), 0)
        table = _colorTable(isDarkTheme())
        size = len(table)
        for position, fraction in self._stops:
            gradient.setColorAt(position, table[int((fraction + phase) * size) % size])
        return gradient

    def _state(self, ms: int) -> _GlowFrame:
        progress = 1 - (1 - min(1.0, ms / ENTRANCE_MS)) ** 3
        fade = 1.0
        if self._stopAtMs is not None:
            ratio = (ms - self._stopAtMs) / FADE_OUT_MS
            fade = max(0.0, 1 - ratio * ratio)
        breath = 1 + BREATH_AMPLITUDE * math.sin(2 * math.pi * ms / BREATH_PERIOD_MS)
        return _GlowFrame(progress, (ms / FLOW_PERIOD_MS) % 1.0, breath, fade)

    def _paintGlow(self, painter: QPainter, ms: int) -> None:
        self._ensureCache()
        if not self._points:
            return
        frame = self._state(ms)
        if frame.fade <= 0:
            return

        path, tapers = _grownPath(
            self._points, self._fractions, frame.progress, self._box, CORNER_RADIUS
        )
        if path is None:
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = self._gradient(frame.phase)
        for width, alpha in _PASSES:
            pen = QPen(gradient, width * frame.breath)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            base = min(1.0, alpha / 255 * frame.breath * frame.fade)
            painter.setOpacity(base)
            painter.drawPath(path)
            for stub, strength in tapers:
                painter.setOpacity(base * strength)
                painter.drawPath(stub)

    def _onTick(self) -> None:
        ms = self._elapsed.elapsed()
        if self._stopAtMs is not None and ms - self._stopAtMs >= FADE_OUT_MS:
            self._finish()
            return
        if self._ring is not None:
            self.update(self._ring)
        else:
            self.update()
