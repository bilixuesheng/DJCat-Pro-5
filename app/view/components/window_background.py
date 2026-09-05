from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget
from qfluentwidgets import qconfig


WINDOW_SHADOW_MARGIN = 12


class WindowBackground(QWidget):
    def __init__(
        self,
        modeItem,
        colorItem,
        imagePathItem,
        scaleModeItem,
        themeColor: Callable[[], QColor] | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._modeItem = modeItem
        self._colorItem = colorItem
        self._imagePathItem = imagePathItem
        self._scaleModeItem = scaleModeItem
        self._themeColor = themeColor or (lambda: qconfig.themeColor.value)
        self._cachedKey = None
        self._cachedPixmap = None
        self._sourceKey = None
        self._sourcePixmap = None
        self._borderVisible = False
        self._cornerRadius = 0
        self.setObjectName("window-background")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        for item in (modeItem, colorItem, imagePathItem, scaleModeItem):
            item.valueChanged.connect(self._invalidate)
        qconfig.themeColor.valueChanged.connect(self._invalidate)

    def _invalidate(self, *_args) -> None:
        self._cachedKey = None
        self._cachedPixmap = None
        self.update()

    def refresh(self, *_args) -> None:
        self._invalidate()

    def setBorderVisible(self, visible: bool) -> None:
        if self._borderVisible == visible:
            return
        self._borderVisible = visible
        self.update()

    def setRoundedWindow(self, enabled: bool) -> None:
        self._cornerRadius = 8 if enabled else 0
        self.setBorderVisible(enabled)
        shadow = self.graphicsEffect()
        if enabled and shadow is None:
            # 阴影只作用于背景，避免时间每秒更新时重新处理全部子控件。
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(WINDOW_SHADOW_MARGIN * self.devicePixelRatioF())
            shadow.setOffset(0, 0)
            shadow.setColor(QColor(0, 0, 0, 100))
            self.setGraphicsEffect(shadow)
        if shadow is not None:
            shadow.setEnabled(enabled)
        self.update()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.DevicePixelRatioChange:
            shadow = self.graphicsEffect()
            if shadow is not None:
                shadow.setBlurRadius(WINDOW_SHADOW_MARGIN * self.devicePixelRatioF())
        return super().event(event)

    def _baseColor(self) -> QColor:
        color = QColor(self._themeColor())
        return color if color.isValid() else QColor("#202020")

    def _image(self) -> QPixmap | None:
        path = str(self._imagePathItem.value or "")
        width, height = self.width(), self.height()
        if not path or width <= 0 or height <= 0:
            return None
        source = self._sourceImage(path)
        key = (self._sourceKey, width, height, self._scaleModeItem.value)
        if key == self._cachedKey:
            return self._cachedPixmap
        if source is None:
            self._cachedKey = key
            self._cachedPixmap = None
            return None

        target = QPixmap(width, height)
        target.fill(Qt.GlobalColor.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        mode = self._scaleModeItem.value
        if mode == "拉伸":
            scaled = source.scaled(
                width,
                height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, scaled)
        else:
            scaled = source.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (width - scaled.width()) // 2
            if mode == "缩放(上)":
                y = 0
            elif mode == "缩放(下)":
                y = height - scaled.height()
            else:
                y = (height - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        painter.end()

        self._cachedKey = key
        self._cachedPixmap = target
        return target

    def _sourceImage(self, path: str) -> QPixmap | None:
        try:
            stamp = Path(path).stat().st_mtime_ns
        except OSError:
            stamp = None
        key = (path, stamp)
        if key != self._sourceKey:
            source = QPixmap(path)
            self._sourceKey = key
            self._sourcePixmap = None if source.isNull() else source
        return self._sourcePixmap

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if self._cornerRadius:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), self._cornerRadius, self._cornerRadius)
            painter.setClipPath(path)
        painter.fillRect(self.rect(), self._baseColor())
        if self._modeItem.value == "纯色":
            painter.fillRect(self.rect(), QColor(self._colorItem.value))
        elif self._modeItem.value == "图片":
            image = self._image()
            if image is not None:
                painter.drawPixmap(0, 0, image)
        if self._borderVisible:
            painter.setClipping(False)
            painter.setPen(QPen(QColor("#808080"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self._cornerRadius:
                painter.drawRoundedRect(
                    QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                    self._cornerRadius - 0.5,
                    self._cornerRadius - 0.5,
                )
            else:
                painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()
