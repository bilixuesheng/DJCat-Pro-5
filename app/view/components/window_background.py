from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QWidget
from qfluentwidgets import qconfig


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

    def _baseColor(self) -> QColor:
        color = QColor(self._themeColor())
        return color if color.isValid() else QColor("#202020")

    def _image(self) -> QPixmap | None:
        path = str(self._imagePathItem.value or "")
        width, height = self.width(), self.height()
        if not path or width <= 0 or height <= 0:
            return None
        key = (path, width, height, self._scaleModeItem.value)
        if key == self._cachedKey:
            return self._cachedPixmap

        source = QPixmap(path)
        if source.isNull():
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

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._baseColor())
        if self._modeItem.value == "纯色":
            painter.fillRect(self.rect(), QColor(self._colorItem.value))
        elif self._modeItem.value == "图片":
            image = self._image()
            if image is not None:
                painter.drawPixmap(0, 0, image)
        painter.end()
