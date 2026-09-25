from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsPathItem,
    QGraphicsScene,
)


# 下拉菜单每次打开都新建一个菜单和一份效果；同尺寸的模糊结果跨实例共用。按字节限额：
# 拖动缩放窗口化投送会产生一连串整窗大小的结果，只按条数限会攒下上百 MB。
_BLUR_CACHE_BYTES = 16 * 1024 * 1024
_blurCache: OrderedDict = OrderedDict()


class SilhouetteShadowEffect(QGraphicsDropShadowEffect):
    """A drop shadow blurred once from the widget's rounded-rect outline.

    ``QGraphicsDropShadowEffect`` re-renders its whole subtree offscreen and runs
    the blur again on every repaint that touches the widget: a hovered menu item,
    a caret blink, or anything repainted under a translucent dialog stacked above.
    Dialog cards and menu panels are opaque rounded rectangles, so their shadow
    depends only on size and radius. It is blurred once per geometry, tinted once
    per colour, and the widget itself is drawn straight through without an
    offscreen copy. Like Qt's own effect the blur radius is in device pixels and
    the offset in logical pixels, so the look matches at every scale factor.
    Colour changes (the dialog's shadow fade-in) only re-tint the cached blur.
    """

    def __init__(self, cornerRadius: float, parent=None):
        super().__init__(parent)
        self._cornerRadius = cornerRadius
        self._blurKey = None
        self._blurred = None
        self._tintKey = None
        self._tinted = None

    def draw(self, painter: QPainter) -> None:
        color = self.color()
        if color.alpha() > 0:
            source = self.sourceBoundingRect(Qt.CoordinateSystem.LogicalCoordinates)
            device = painter.device()
            ratio = device.devicePixelRatioF() if device is not None else 1.0
            shadow = self._shadow(source.size(), ratio, color)
            if shadow is not None:
                margin = math.ceil(self.blurRadius()) / ratio
                target = QRectF(
                    source.topLeft() + self.offset() - QPointF(margin, margin),
                    source.size() + QRectF(0, 0, 2 * margin, 2 * margin).size(),
                )
                painter.save()
                painter.setOpacity(painter.opacity() * color.alphaF())
                painter.drawImage(target, shadow)
                painter.restore()
        self.drawSource(painter)

    def _shadow(self, size, ratio: float, color: QColor) -> QImage | None:
        width = round(size.width() * ratio)
        height = round(size.height() * ratio)
        if width <= 0 or height <= 0:
            return None
        blurKey = (width, height, self.blurRadius(), ratio, self._cornerRadius)
        if blurKey != self._blurKey:
            self._blurKey = blurKey
            self._blurred = _cachedSilhouette(
                width,
                height,
                self._cornerRadius * ratio,
                self.blurRadius(),
            )
            self._tintKey = None
        tintKey = (color.rgb() & 0xFFFFFF, blurKey)
        if tintKey != self._tintKey:
            self._tintKey = tintKey
            tinted = QImage(self._blurred)
            painter = QPainter(tinted)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QColor(color.red(), color.green(), color.blue()))
            painter.end()
            self._tinted = tinted
        return self._tinted


def _cachedSilhouette(width: int, height: int, cornerRadius: float, blur: float) -> QImage:
    key = (width, height, cornerRadius, blur)
    image = _blurCache.get(key)
    if image is not None:
        _blurCache.move_to_end(key)
        return image
    image = _blurredSilhouette(width, height, cornerRadius, blur)
    if image.sizeInBytes() <= _BLUR_CACHE_BYTES // 4:
        _blurCache[key] = image
        while sum(item.sizeInBytes() for item in _blurCache.values()) > _BLUR_CACHE_BYTES:
            _blurCache.popitem(last=False)
    return image


def _blurredSilhouette(width: int, height: int, cornerRadius: float, blur: float) -> QImage:
    # 让 Qt 自己的 QGraphicsDropShadowEffect 生成阴影，衰减曲线才与原版一致。把阴影偏移到
    # 轮廓下方足够远，只截取阴影那一块，轮廓本身不入画。
    margin = math.ceil(blur)
    shift = height + 2 * margin + 2
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), cornerRadius, cornerRadius)
    item = QGraphicsPathItem(path)
    item.setPen(Qt.PenStyle.NoPen)
    item.setBrush(QColor(0, 0, 0))
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur)
    effect.setOffset(0, shift)
    effect.setColor(QColor(0, 0, 0))
    item.setGraphicsEffect(effect)
    scene = QGraphicsScene()
    scene.addItem(item)

    # 效果只在能画到的设备区域里取源，轮廓必须留在画布内，最后再裁出阴影那一块。
    canvas = QImage(
        width + 2 * margin,
        shift + height + 2 * margin,
        QImage.Format.Format_ARGB32_Premultiplied,
    )
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    scene.render(
        painter,
        QRectF(canvas.rect()),
        QRectF(-margin, -margin, canvas.width(), canvas.height()),
    )
    painter.end()
    return canvas.copy(0, shift, width + 2 * margin, height + 2 * margin)
