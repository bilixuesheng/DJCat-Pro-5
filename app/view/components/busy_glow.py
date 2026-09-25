"""Busy Glow：AI Markdown Conversion 期间环绕输入框的彩色光带。

为什么是自绘而不是 QSS，以及下面那些看着可以删、其实不能删的约束，见
`docs/adr/0002-busy-glow-custom-paint.md`。
"""

from __future__ import annotations

import math
from typing import NamedTuple

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
)
from PySide6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme

from app.platform.dialog_animation import fadeDialogShadow

CORNER_RADIUS = 5  # 与 QFluentWidgets TextEdit 的边框圆角一致
PERIMETER_SAMPLES = 720
GRADIENT_STOP_STRIDE = 4
ENTRANCE_STOP_STRIDE = 2  # 入场时色标还要描出弧的两端渐隐，需要更密

# 全局 Animation Tick 是 1 ms，但这里一帧要画几十圈抗锯齿环和一次锥形渐变填充，属于
# 必须自己限流的回调。相位仍按真实经过时间算，所以限流只让它少画几帧，不让动画变慢。
FRAME_INTERVAL_MS = 16

ENTRANCE_MS = 700
FLOW_PERIOD_MS = 4000
BREATH_PERIOD_MS = 2600
BREATH_AMPLITUDE = 0.12
FADE_OUT_MS = 320
TAPER_FRACTION = 0.10  # 每个生长端渐隐段占已长出弧长的比例

# 光晕是到边线距离的平滑函数：两个高斯（峰值 alpha，标准差 px）相加，近处一个撑亮度、
# 远处一个撑范围。
_HALO_LOBES = ((0.30, 5.0), (0.11, 15.0))
_HALO_GAIN = 1.6
# 框内的距离按这个倍数计：光晕向框内渗得比向外少，正文贴边的字不会被染色。
_INNER_FALLOFF = 1.6
# 边线本身仍用画笔按设备像素描两遍，光晕再软，轮廓也是锐利的。
_CORE_PASSES = ((5.5, 70), (2.4, 120))
# 光晕缓冲一个像素对应的逻辑像素数。光晕的标准差有 5–15 px，按设备像素画只是在高缩放
# 下把开销放大 DPR² 倍，放大贴回时的双线性插值看不出区别。
HALO_PIXEL = 2.0

# 光晕亮度沿周长起伏，两组波以不同周期反向流动，与颜色的流动互不同步，光带看着像液体
# 而不是一圈转动的彩虹。下限保证光带任何时候都是连续的一圈。
_SHIMMER_PERIODS_MS = (2900, 4700)
_SHIMMER_FLOOR = 0.35

# 光晕在 overlay 边界前一像素衰减到 0；overlay 向外让出的空间就是光晕的全部范围。
GLOW_MARGIN = 34
_HALO_REACH = GLOW_MARGIN - 1

# 蓝 → 靛 → 紫 → 粉 → 橙 → 回蓝。不走满 360° 色相：绕整圈必然经过纯绿纯黄，
# 那两段感知亮度最高，放在光带里只会刺眼。
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

    深色配方靠加性合成"发光"；浅色背景上没有比接近白更亮的余地，
    所以浅色配方提饱和、降明度，靠比背景更暗更浓的颜色显形。
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


def _haloAlpha(distance: float, breath: float) -> float:
    """距边线 `distance`（框外为正）处的光晕 alpha。

    呼吸同时拉宽光晕和提高不透明度；只改其中一项，光带看着像在缩放或在闪，而不是在呼吸。
    """
    if distance < 0:
        distance *= _INNER_FALLOFF
    if abs(distance) >= _HALO_REACH:
        return 0.0
    x = distance / breath
    value = sum(
        peak * math.exp(-x * x / (2 * sigma * sigma)) for peak, sigma in _HALO_LOBES
    )
    # 在 overlay 边界前平滑收到 0，否则最外圈会被 overlay 自身的几何裁成一条直边。
    window = 1 - (distance / _HALO_REACH) ** 2
    return min(1.0, value * window * window * _HALO_GAIN * breath)


def _shimmer(fraction: float, ms: float) -> float:
    fast, slow = _SHIMMER_PERIODS_MS
    a = 0.5 + 0.5 * math.sin(2 * math.pi * (2 * fraction + ms / fast))
    b = 0.5 + 0.5 * math.sin(2 * math.pi * (3 * fraction - ms / slow) + 1.3)
    return _SHIMMER_FLOOR + (1 - _SHIMMER_FLOOR) * (0.55 * a + 0.45 * b)


def _arcWindow(fraction: float, progress: float) -> float:
    """已长出部分的可见度：以底边中点（0）为中心的一段连续圆弧，两端渐隐。

    把它描述成从底边中点升起的两条臂，两条臂会在起笔点和会合点重叠，alpha 叠加成
    两个亮疙瘩。这里只有一段弧，不存在重叠。

    弧的实心部分伸到一半周长时，两端的渐隐段还在顶部留着一段缺口；所以弧要多伸出
    一截渐隐的长度，让两端渐隐在顶部逐渐补满，进度到 1 时恰好是完整一圈。只伸到
    一半周长的话，最后一帧会把那段缺口一下子补上，看着像"啪"地合拢。
    """
    if progress >= 1.0:
        return 1.0
    if progress <= 0.0:
        return 0.0
    taper = max(1e-3, TAPER_FRACTION * progress)
    reach = progress * (0.5 + TAPER_FRACTION)
    distance = min(fraction, 1.0 - fraction)
    return max(0.0, min(1.0, (reach - distance) / taper))


def _roundedPath(box: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(box, radius, radius)
    return path


def _offsetBox(box: QRectF, offset: float) -> tuple[QRectF, float]:
    return (
        box.adjusted(-offset, -offset, offset, offset),
        max(0.0, CORNER_RADIUS + offset),
    )


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


def _angularStops(points, fractions, center: QPointF, stride: int):
    """锥形渐变的色标：（角度位置，弧长位置），按角度排好序，每帧可直接 setStops。"""
    stops = []
    for index in range(0, len(points) - 1, stride):
        point = points[index]
        angle = (
            math.degrees(math.atan2(-(point.y() - center.y()), point.x() - center.x()))
            % 360
        )
        stops.append((min(0.9999, angle / 360.0), fractions[index]))
    stops.sort()
    return stops


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
        self._colorStops: list[tuple[float, float]] = []
        self._entranceStops: list[tuple[float, float]] = []
        self._rings: list[tuple[float, QPainterPath]] = []
        self._ring: QRegion | None = None
        self._buffer: QImage | None = None
        self._cacheKey = None
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
        self._buffer = None
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
        if self._cacheKey != self.size():
            self._rebuild()

    def _rebuild(self) -> None:
        """所有随几何变化的数据都缓存在这里，一帧只需要转相位、改 alpha。"""
        self._cacheKey = self.size()
        self._buffer = None
        box = QRectF(self.rect()).adjusted(
            GLOW_MARGIN, GLOW_MARGIN, -GLOW_MARGIN, -GLOW_MARGIN
        )
        if box.width() <= 2 * CORNER_RADIUS or box.height() <= 2 * CORNER_RADIUS:
            self._points, self._fractions = [], []
            self._colorStops, self._entranceStops, self._rings = [], [], []
            self._ring = None
            return

        self._box = box
        self._points, self._fractions = _perimeter(box, CORNER_RADIUS)
        center = box.center()
        self._colorStops = _angularStops(
            self._points, self._fractions, center, GRADIENT_STOP_STRIDE
        )
        self._entranceStops = _angularStops(
            self._points, self._fractions, center, ENTRANCE_STOP_STRIDE
        )

        # 光晕按缓冲的一个像素一圈画。每圈向内多盖两圈，由外向内以 Source 模式覆盖：
        # 下一圈的抗锯齿外沿恰好在两圈的值之间线性插值，相邻圈之间没有接缝。
        step = HALO_PIXEL
        inner = min(_HALO_REACH / _INNER_FALLOFF + 1, box.height() / 2 - 1)
        self._rings = []
        offset = float(_HALO_REACH)
        while offset > -inner:
            ring = QPainterPath()
            ring.setFillRule(Qt.FillRule.OddEvenFill)
            for edge in (offset, offset - 3 * step):
                rect, radius = _offsetBox(box, edge)
                if rect.width() > 0 and rect.height() > 0:
                    ring.addRoundedRect(rect, radius, radius)
            self._rings.append((offset - step / 2, ring))
            offset -= step

        outer = box.adjusted(-_HALO_REACH, -_HALO_REACH, _HALO_REACH, _HALO_REACH)
        region = QRegion(outer.toAlignedRect())
        hole = box.adjusted(inner, inner, -inner, -inner).toAlignedRect()
        if hole.width() > 0 and hole.height() > 0:
            region -= QRegion(hole)
        self._ring = region

    def _gradients(self, frame: _GlowFrame, ms: int):
        """（光晕渐变，边线渐变）。

        颜色随相位流动；光晕另带沿周长起伏的亮度；入场时两者的 alpha 再乘上弧长窗口，
        已长出的那段弧就直接画出来，不用整块再填一遍遮罩。
        """
        table = _colorTable(isDarkTheme())
        size = len(table)
        growing = frame.progress < 1.0
        stops = self._entranceStops if growing else self._colorStops
        haloStops, coreStops = [], []
        for position, fraction in stops:
            window = _arcWindow(fraction, frame.progress) if growing else 1.0
            color = table[int((fraction + frame.phase) * size) % size]
            core = QColor(color)
            core.setAlphaF(window)
            coreStops.append((position, core))
            halo = QColor(color)
            halo.setAlphaF(_shimmer(fraction, ms) * window)
            haloStops.append((position, halo))
        center = self._box.center()
        halo, core = QConicalGradient(center, 0), QConicalGradient(center, 0)
        halo.setStops(haloStops)
        core.setStops(coreStops)
        return halo, core

    def _state(self, ms: int) -> _GlowFrame:
        progress = 1 - (1 - min(1.0, ms / ENTRANCE_MS)) ** 3
        fade = 1.0
        if self._stopAtMs is not None:
            ratio = (ms - self._stopAtMs) / FADE_OUT_MS
            fade = max(0.0, 1 - ratio * ratio)
        breath = 1 + BREATH_AMPLITUDE * math.sin(2 * math.pi * ms / BREATH_PERIOD_MS)
        return _GlowFrame(progress, (ms / FLOW_PERIOD_MS) % 1.0, breath, fade)

    def _haloBuffer(self) -> QImage:
        size = self.size() / HALO_PIXEL
        if self._buffer is None or self._buffer.size() != size:
            self._buffer = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
            self._buffer.setDevicePixelRatio(1 / HALO_PIXEL)
        return self._buffer

    def _paintGlow(self, painter: QPainter, ms: int) -> None:
        self._ensureCache()
        if not self._points:
            return
        frame = self._state(ms)
        if frame.fade <= 0 or frame.progress <= 0:
            return
        halo, core = self._gradients(frame, ms)

        buffer = self._haloBuffer()
        buffer.fill(0)
        canvas = QPainter(buffer)
        canvas.setRenderHint(QPainter.RenderHint.Antialiasing)
        canvas.setPen(Qt.PenStyle.NoPen)
        canvas.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        for distance, ring in self._rings:
            alpha = round(_haloAlpha(distance, frame.breath) * 255)
            canvas.fillPath(ring, QColor(255, 255, 255, alpha))
        canvas.setClipRegion(self._ring)
        canvas.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        canvas.fillRect(QRectF(self.rect()), halo)
        canvas.end()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if isDarkTheme():
            # 光是加上去的：深色背景上按加性合成，越亮处越接近白热，才像自发光而不是一层
            # 半透明的彩色贴纸。浅色背景上加性合成会直接饱和成白，只能正常叠加。
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        painter.setOpacity(frame.fade)
        painter.drawImage(QRectF(self.rect()), buffer)

        # 边线正常叠加：再加一次会在光晕最亮处饱和成纯白，边线就没有颜色了。
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        edge = _roundedPath(self._box, CORNER_RADIUS)
        for width, alpha in _CORE_PASSES:
            pen = QPen(core, width * frame.breath)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setOpacity(min(1.0, alpha / 255 * frame.breath) * frame.fade)
            painter.drawPath(edge)
        painter.restore()

    def _onTick(self) -> None:
        ms = self._elapsed.elapsed()
        if self._stopAtMs is not None and ms - self._stopAtMs >= FADE_OUT_MS:
            self._finish()
            return
        if self._ring is not None:
            self.update(self._ring)
        else:
            self.update()
