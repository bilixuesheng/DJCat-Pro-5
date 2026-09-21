from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, IconWidget, isDarkTheme, qconfig, themeColor

from app.common.application_icon import applicationIcon, trayHomeIcon
from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.components.banner_widget import BannerWidget
from app.view.components.window_background import WindowBackground

PREVIEW_RADIUS = 8


class BannerPreview(BannerWidget):
    """The home banner drawn at a fraction of its real height."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(140)
        self.galleryLabel.hide()


class WindowBackgroundPreview(WindowBackground):
    """A Projection / Countdown / Clock background rendered inside the page."""

    def __init__(self, modeItem, colorItem, imagePathItem, scaleModeItem, parent=None):
        super().__init__(
            modeItem,
            colorItem,
            imagePathItem,
            scaleModeItem,
            parent=parent,
        )
        self.setFixedHeight(180)
        self.setRoundedWindow(True, shadow=False)


class ApplicationIconPreview(QWidget):
    """The same icon as it appears in every place that shares it."""

    SLOTS = ("主窗口", "启动页", "系统托盘", "托盘“主页”")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hBoxLayout = QHBoxLayout(self)
        self.iconWidgets = {}

        self._initLayout()
        self._bind()
        self.refresh()

    def _initLayout(self) -> None:
        self.hBoxLayout.setContentsMargins(16, 18, 16, 18)
        self.hBoxLayout.setSpacing(28)
        self.hBoxLayout.addStretch(1)
        for name in self.SLOTS:
            slot = QWidget(self)
            slotLayout = QVBoxLayout(slot)
            slotLayout.setContentsMargins(0, 0, 0, 0)
            slotLayout.setSpacing(8)
            iconWidget = IconWidget(slot)
            iconWidget.setFixedSize(40, 40)
            label = CaptionLabel(name, slot)
            slotLayout.addWidget(iconWidget, 0, Qt.AlignmentFlag.AlignHCenter)
            slotLayout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
            self.hBoxLayout.addWidget(slot)
            self.iconWidgets[name] = iconWidget
        self.hBoxLayout.addStretch(1)

    def _bind(self) -> None:
        cfg.applicationIconSource.valueChanged.connect(self.refresh)
        cfg.applicationIconPath.valueChanged.connect(self.refresh)

    def refresh(self, _value=None) -> None:
        icon = applicationIcon()
        for name, iconWidget in self.iconWidgets.items():
            iconWidget.setIcon(trayHomeIcon() if name == self.SLOTS[3] else icon)


class ThemePreview(QWidget):
    """A miniature window showing the current theme and theme colour."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(160)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        qconfig.themeColor.valueChanged.connect(self._refresh)
        qconfig.themeChanged.connect(self._refresh)

    def _refresh(self, *_args) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        dark = isDarkTheme()
        window = QColor("#272727") if dark else QColor("#f3f3f3")
        surface = QColor("#2d2d2d") if dark else QColor("#ffffff")
        stroke = QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 18)
        muted = QColor(255, 255, 255, 46) if dark else QColor(0, 0, 0, 38)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, PREVIEW_RADIUS, PREVIEW_RADIUS)
        painter.fillPath(path, window)
        painter.setClipPath(path)

        # 标题栏
        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 26), surface)
        painter.fillRect(QRectF(rect.right() - 54, rect.top() + 11, 42, 4), muted)

        # 侧边导航
        sidebar = QRectF(rect.left(), rect.top() + 26, 44, rect.height() - 26)
        painter.fillRect(sidebar, surface)
        for index in range(3):
            top = sidebar.top() + 14 + index * 22
            if index == 0:
                painter.fillRect(
                    QRectF(sidebar.left() + 4, top - 3, 3, 16), themeColor()
                )
            painter.fillRect(QRectF(sidebar.left() + 14, top, 16, 10), muted)

        # 内容卡片与主色按钮
        content = QRectF(
            rect.left() + 56,
            rect.top() + 40,
            rect.width() - 68,
            rect.height() - 56,
        )
        card = QPainterPath()
        card.addRoundedRect(content, 6, 6)
        painter.fillPath(card, surface)
        painter.setPen(QPen(stroke, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(card)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(
            QRectF(content.left() + 12, content.top() + 14, content.width() - 70, 6),
            muted,
        )
        painter.fillRect(
            QRectF(content.left() + 12, content.top() + 28, content.width() - 110, 6),
            muted,
        )
        button = QPainterPath()
        button.addRoundedRect(
            QRectF(content.left() + 12, content.bottom() - 32, 78, 24), 4, 4
        )
        painter.fillPath(button, themeColor())
        painter.end()


class WindowTextPreview(QWidget):
    """The custom window title and tray tooltip as the user will read them."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(128)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cfg.windowTitle.valueChanged.connect(self._refresh)
        cfg.trayTooltip.valueChanged.connect(self._refresh)
        qconfig.themeChanged.connect(self._refresh)

    def _refresh(self, *_args) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        dark = isDarkTheme()
        surface = QColor("#2d2d2d") if dark else QColor("#ffffff")
        stroke = QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 18)
        text = QColor(255, 255, 255, 222) if dark else QColor(0, 0, 0, 222)
        muted = QColor(255, 255, 255, 46) if dark else QColor(0, 0, 0, 38)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        titleBar = QRectF(rect.left(), rect.top(), rect.width(), 40)
        path = QPainterPath()
        path.addRoundedRect(titleBar, PREVIEW_RADIUS, PREVIEW_RADIUS)
        painter.fillPath(path, surface)
        painter.setPen(QPen(stroke, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        painter.setPen(text)
        painter.drawText(
            titleBar.adjusted(16, 0, -70, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            cfg.windowTitle.value.strip() or APP_NAME,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(3):
            painter.fillRect(
                QRectF(titleBar.right() - 58 + index * 18, titleBar.center().y() - 1, 10, 2),
                muted,
            )

        tooltip = QRectF(rect.left() + 40, rect.top() + 68, rect.width() - 120, 34)
        bubble = QPainterPath()
        bubble.addRoundedRect(tooltip, 4, 4)
        painter.fillPath(bubble, surface)
        painter.setPen(QPen(stroke, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(bubble)
        painter.setPen(text)
        painter.drawText(
            tooltip.adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            cfg.trayTooltip.value.strip() or APP_NAME,
        )
        painter.end()
