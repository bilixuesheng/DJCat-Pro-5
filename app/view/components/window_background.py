from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme, qconfig

from app.config.cfg import cfg
from app.platform.shadow_effect import SilhouetteShadowEffect

WINDOW_SHADOW_MARGIN = 12
WINDOW_CORNER_RADIUS = 8
# 倒计时和全屏时钟的默认背景（配置值"主题色"，设置页显示为"默认黑色"）不论主题都是黑底。
TIMER_THEME_BACKGROUND = QColor("black")


def followsDarkTheme() -> bool:
    """投送窗口的深浅跟随软件主题设置，"跟随系统"时再看系统。"""
    mode = cfg.customThemeMode.value
    return isDarkTheme() if mode == "System" else mode == "Dark"


def projectionTitleColor() -> QColor:
    """投送标题的主题色。深色底上原始主题色往往太暗，按 QFluentWidgets 深色主题的
    主色规则提亮（饱和度 ×0.84、明度拉满），与软件里其他深色控件的强调色一致。"""
    color = QColor(qconfig.themeColor.value)
    if not followsDarkTheme():
        return color
    hue, saturation, _value, alpha = color.getHsvF()
    return QColor.fromHsvF(hue, saturation * 0.84, 1.0, alpha)


def projectionThemeBackground() -> QColor:
    """投送的默认背景（配置值"主题色"，设置页显示为"跟随主题"）：跟随深浅主题，不是强调色。"""
    return QColor("#202020" if followsDarkTheme() else "#FFFFFF")


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

    def setRoundedWindow(self, enabled: bool, shadow: bool = True) -> None:
        """``shadow=False`` keeps the rounded corners for in-page previews,
        which sit inside a scroll area and must not cast a window shadow."""
        self._cornerRadius = WINDOW_CORNER_RADIUS if enabled else 0
        self.setBorderVisible(enabled)
        if not shadow:
            self.setGraphicsEffect(None)
            self.update()
            return
        shadow = self.graphicsEffect()
        if enabled and shadow is None:
            # 阴影只作用于背景，避免时间每秒更新时重新处理全部子控件。轮廓阴影只在
            # 窗口尺寸变化时模糊一次：原版效果在窗口化投送滚动正文时每帧都要重新模糊整窗。
            shadow = SilhouetteShadowEffect(WINDOW_CORNER_RADIUS, self)
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

    def resizeEdges(self, position: QPointF, borderWidth: int) -> Qt.Edge:
        """按可见圆角边框命中缩放区域，外侧仅保留 2 px 抓取余量。"""
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        outer = QPainterPath()
        outer.addRoundedRect(
            rect.adjusted(-2, -2, 2, 2),
            self._cornerRadius + 1.5,
            self._cornerRadius + 1.5,
        )
        inner = QPainterPath()
        radius = max(0, self._cornerRadius - borderWidth)
        inner.addRoundedRect(
            rect.adjusted(borderWidth, borderWidth, -borderWidth, -borderWidth),
            radius, radius,
        )
        edges = Qt.Edge(0)
        if not outer.contains(position) or inner.contains(position):
            return edges
        if position.x() < borderWidth:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - borderWidth:
            edges |= Qt.Edge.RightEdge
        if position.y() < borderWidth:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - borderWidth:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _baseColor(self) -> QColor:
        color = QColor(self._themeColor())
        return color if color.isValid() else QColor("#202020")

    def _image(self) -> QPixmap | None:
        path = str(self._imagePathItem.value or "")
        width, height = self.width(), self.height()
        if not path or width <= 0 or height <= 0:
            return None
        source = self._sourceImage(path)
        ratio = self.devicePixelRatioF()
        key = (self._sourceKey, width, height, ratio, self._scaleModeItem.value)
        if key == self._cachedKey:
            return self._cachedPixmap
        if source is None:
            self._cachedKey = key
            self._cachedPixmap = None
            return None

        # 按物理像素缩放，最后标上设备像素比；按逻辑尺寸缩放会在 150%/200% 下被放大发虚。
        # 缓存键带上设备像素比，窗口换到不同缩放的屏幕时才会重建。
        width, height = max(1, round(width * ratio)), max(1, round(height * ratio))
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
        target.setDevicePixelRatio(ratio)

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
