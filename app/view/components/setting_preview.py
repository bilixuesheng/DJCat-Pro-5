from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    IconWidget,
    StrongBodyLabel,
    isDarkTheme,
    qconfig,
    themeColor,
)

from app.common.application_icon import applicationIcon, trayHomeIcon
from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.components.banner_widget import BannerWidget
from app.view.components.setting_card_group import SettingMaterialCard
from app.view.components.window_background import WindowBackground

PREVIEW_RADIUS = 8

# 投送、倒计时和时钟三种窗口的正文形状不同，预览按各自真实的排布画。
PROJECTION_CONTENT = "projection"
COUNTDOWN_CONTENT = "countdown"
CLOCK_CONTENT = "clock"


class SettingPreviewCard(SettingMaterialCard):
    """Previews that draw loose parts sit on the same material as the cards,
    otherwise they read as unfinished page content rather than a preview."""


def _mutedColor(dark: bool) -> QColor:
    return QColor(255, 255, 255, 46) if dark else QColor(0, 0, 0, 38)


def _surfaceColor(dark: bool) -> QColor:
    return QColor("#2d2d2d") if dark else QColor("#ffffff")


def _strokeColor(dark: bool) -> QColor:
    return QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 18)


def _textColor(dark: bool) -> QColor:
    return QColor(255, 255, 255, 222) if dark else QColor(0, 0, 0, 222)


class WindowBackgroundPreview(WindowBackground):
    """A Projection / Countdown / Clock window rendered inside the page.

    It paints the real window's furniture over the background so the choice of
    colour or image can be judged against the title, body and corner buttons
    that will actually sit on top of it.
    """

    def __init__(
        self,
        modeItem,
        colorItem,
        imagePathItem,
        scaleModeItem,
        contentKind: str,
        actionPositionItem=None,
        parent=None,
    ):
        super().__init__(
            modeItem,
            colorItem,
            imagePathItem,
            scaleModeItem,
            parent=parent,
        )
        self._contentKind = contentKind
        self._actionPositionItem = actionPositionItem
        self.setFixedHeight(190)
        self.setRoundedWindow(True, shadow=False)
        if actionPositionItem is not None:
            actionPositionItem.valueChanged.connect(self._onActionPositionChanged)

    def _onActionPositionChanged(self, *_args) -> None:
        self.update()

    def _actionButtonCount(self) -> int:
        if self._contentKind == PROJECTION_CONTENT:
            return 4  # 编辑 / 最小化 / 窗口化 / 关闭
        if self._contentKind == COUNTDOWN_CONTENT:
            return 3  # 重置 / 窗口化 / 关闭
        return 2  # 窗口化 / 关闭

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        rect = QRectF(self.rect()).adjusted(18, 16, -18, -14)
        if self._contentKind == PROJECTION_CONTENT:
            self._paintProjection(painter, rect)
        else:
            self._paintTimer(painter, rect)
        self._paintActionButtons(painter, QRectF(self.rect()))
        painter.end()

    def _paintProjection(self, painter: QPainter, rect: QRectF) -> None:
        font = QFont(self.font())
        font.setPixelSize(20)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(themeColor())
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width(), 26),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "投送标题",
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 132))
        widths = (0.92, 0.86, 0.94, 0.58)
        for index, ratio in enumerate(widths):
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top() + 40 + index * 18, rect.width() * ratio, 7),
                3,
                3,
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)

    def _paintTimer(self, painter: QPainter, rect: QRectF) -> None:
        title = "考试倒计时" if self._contentKind == COUNTDOWN_CONTENT else "当前时间"
        font = QFont(self.font())
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 190))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 12, rect.width(), 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            title,
        )
        font.setPixelSize(46)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 36, rect.width(), 60),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            "00 : 45 : 00" if self._contentKind == COUNTDOWN_CONTENT else "09 : 24 : 30",
        )

    def _paintActionButtons(self, painter: QPainter, rect: QRectF) -> None:
        count = self._actionButtonCount()
        width, height, spacing, margin = 30, 38, 8, 14
        total = count * width + (count - 1) * spacing
        onLeft = (
            self._actionPositionItem is not None
            and self._actionPositionItem.value == "左下角"
        )
        left = rect.left() + margin if onLeft else rect.right() - margin - total
        top = rect.bottom() - margin - height

        for index in range(count):
            button = QRectF(left + index * (width + spacing), top, width, height)
            # 主色的关闭按钮落在主题色背景上会糊成一片，描一道细边让它始终可辨。
            painter.setPen(QPen(QColor(255, 255, 255, 110), 1))
            painter.setBrush(
                themeColor() if index == count - 1 else QColor(0, 0, 0, 92)
            )
            painter.drawRoundedRect(button, 5, 5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 170))
            painter.drawRoundedRect(
                QRectF(button.center().x() - 5, button.top() + 9, 10, 10), 2, 2
            )
            painter.drawRoundedRect(
                QRectF(button.left() + 6, button.bottom() - 12, width - 12, 4), 2, 2
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)


class _HomeCardRowPreview(QWidget):
    """The row of Home Cards that sits under the banner on the home page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(_strokeColor(isDarkTheme()), 1))
        painter.setBrush(_surfaceColor(isDarkTheme()))
        muted = _mutedColor(isDarkTheme())
        cardWidth = (self.width() - 2 * 10) / 3
        for index in range(3):
            card = QRectF(index * (cardWidth + 10), 0.5, cardWidth, self.height() - 1)
            painter.drawRoundedRect(card, 6, 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(muted)
            painter.drawRoundedRect(
                QRectF(card.left() + 10, card.center().y() - 8, 16, 16), 4, 4
            )
            painter.drawRoundedRect(
                QRectF(card.left() + 34, card.center().y() - 6, cardWidth * 0.45, 5), 2, 2
            )
            painter.drawRoundedRect(
                QRectF(card.left() + 34, card.center().y() + 2, cardWidth * 0.3, 4), 2, 2
            )
            painter.setPen(QPen(_strokeColor(isDarkTheme()), 1))
            painter.setBrush(_surfaceColor(isDarkTheme()))
        painter.end()


class HomeBannerPreview(SettingPreviewCard):
    """The home page as the banner settings shape it: title, banner, cards."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = StrongBodyLabel("主页", self)
        self.banner = BannerWidget(self)
        self.subTitleLabel = CaptionLabel("常用功能", self)
        self.cardRow = _HomeCardRowPreview(self)
        self.vBoxLayout = QVBoxLayout(self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.banner.setFixedHeight(120)
        self.banner.galleryLabel.hide()
        self.banner.setVisible(cfg.showBanner.value)

    def _initLayout(self) -> None:
        self.vBoxLayout.setContentsMargins(18, 14, 18, 16)
        self.vBoxLayout.setSpacing(10)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addWidget(self.banner)
        self.vBoxLayout.addWidget(self.subTitleLabel)
        self.vBoxLayout.addWidget(self.cardRow)

    def _bind(self) -> None:
        cfg.showBanner.valueChanged.connect(self.banner.setVisible)


class ApplicationIconPreview(SettingPreviewCard):
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
        surface = _surfaceColor(dark)
        stroke = _strokeColor(dark)
        muted = _mutedColor(dark)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, PREVIEW_RADIUS, PREVIEW_RADIUS)
        painter.fillPath(path, window)
        painter.setClipPath(path)

        painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 26), surface)
        painter.fillRect(QRectF(rect.right() - 54, rect.top() + 11, 42, 4), muted)

        sidebar = QRectF(rect.left(), rect.top() + 26, 44, rect.height() - 26)
        painter.fillRect(sidebar, surface)
        for index in range(3):
            top = sidebar.top() + 14 + index * 22
            if index == 0:
                painter.fillRect(
                    QRectF(sidebar.left() + 4, top - 3, 3, 16), themeColor()
                )
            painter.fillRect(QRectF(sidebar.left() + 14, top, 16, 10), muted)

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


class WindowTextPreview(SettingPreviewCard):
    """The window title bar, and the tray tooltip as Windows shows it.

    Both texts land somewhere the user cannot see while typing, so the preview
    reproduces the real surroundings: the title bar with its own icon and
    caption buttons, and the notification area at the corner of the taskbar.
    """

    TITLE_BAR_HEIGHT = 38
    TASKBAR_HEIGHT = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(190)
        cfg.windowTitle.valueChanged.connect(self._refresh)
        cfg.trayTooltip.valueChanged.connect(self._refresh)
        cfg.applicationIconSource.valueChanged.connect(self._refresh)
        cfg.applicationIconPath.valueChanged.connect(self._refresh)
        qconfig.themeChanged.connect(self._refresh)

    def _refresh(self, *_args) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        rect = QRectF(self.rect()).adjusted(18, 14, -18, -14)
        self._paintTitleBar(painter, QRectF(rect.left(), rect.top(), rect.width(), self.TITLE_BAR_HEIGHT))
        self._paintTaskbar(
            painter,
            QRectF(
                rect.left(),
                rect.bottom() - self.TASKBAR_HEIGHT,
                rect.width(),
                self.TASKBAR_HEIGHT,
            ),
        )
        painter.end()

    def _paintTitleBar(self, painter: QPainter, rect: QRectF) -> None:
        dark = isDarkTheme()
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.fillPath(path, _surfaceColor(dark))
        painter.setPen(QPen(_strokeColor(dark), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        icon = applicationIcon()
        iconRect = QRectF(rect.left() + 12, rect.center().y() - 8, 16, 16)
        icon.paint(painter, iconRect.toRect())

        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.setPen(_textColor(dark))
        painter.drawText(
            QRectF(iconRect.right() + 10, rect.top(), rect.width() - 150, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            cfg.windowTitle.value.strip() or APP_NAME,
        )

        # 最小化、最大化、关闭：画成真实标题栏上的三个字形而不是三根等长横线。
        glyphPen = QPen(_textColor(dark), 1.2)
        painter.setPen(glyphPen)
        centerY = rect.center().y()
        minimize = rect.right() - 92
        painter.drawLine(minimize - 5, centerY, minimize + 5, centerY)
        maximize = rect.right() - 58
        painter.drawRect(QRectF(maximize - 5, centerY - 5, 10, 10))
        close = rect.right() - 24
        painter.drawLine(close - 5, centerY - 5, close + 5, centerY + 5)
        painter.drawLine(close - 5, centerY + 5, close + 5, centerY - 5)

    def _paintTaskbar(self, painter: QPainter, rect: QRectF) -> None:
        dark = isDarkTheme()
        taskbar = QColor("#202020") if dark else QColor("#f3f3f3")
        taskbarText = QColor(255, 255, 255, 222) if dark else QColor(0, 0, 0, 222)
        path = QPainterPath()
        path.addRoundedRect(rect, 6, 6)
        painter.fillPath(path, taskbar)
        painter.setPen(QPen(_strokeColor(dark), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        font = QFont(self.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.setPen(taskbarText)
        clock = QRectF(rect.right() - 58, rect.top(), 46, rect.height())
        painter.drawText(
            QRectF(clock.left(), clock.top() + 7, clock.width(), 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "9:24",
        )
        painter.drawText(
            QRectF(clock.left(), clock.top() + 21, clock.width(), 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "9月22日",
        )

        muted = QColor(255, 255, 255, 120) if dark else QColor(0, 0, 0, 120)
        trayRect = QRectF(clock.left() - 92, rect.center().y() - 8, 16, 16)
        applicationIcon().paint(painter, trayRect.toRect())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(muted)
        for index in range(2):
            painter.drawRoundedRect(
                QRectF(trayRect.right() + 10 + index * 24, trayRect.top() + 3, 10, 10),
                2,
                2,
            )
        # 展开隐藏图标的箭头
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(muted, 1.2))
        arrow = QRectF(trayRect.left() - 26, rect.center().y() - 3, 10, 6)
        painter.drawLine(arrow.left(), arrow.bottom(), arrow.center().x(), arrow.top())
        painter.drawLine(arrow.center().x(), arrow.top(), arrow.right(), arrow.bottom())

        self._paintTooltip(painter, rect, trayRect)

    def _paintTooltip(self, painter: QPainter, taskbar: QRectF, trayRect: QRectF) -> None:
        dark = isDarkTheme()
        text = cfg.trayTooltip.value.strip() or APP_NAME
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        # 气泡按文字宽度收紧，真实的托盘提示不会铺满一整行。
        textWidth = painter.fontMetrics().horizontalAdvance(text)
        width = min(textWidth + 20, taskbar.width() - 20)
        bubble = QRectF(0, taskbar.top() - 34, width, 26)
        bubble.moveRight(min(trayRect.center().x() + width / 2, taskbar.right()))

        path = QPainterPath()
        path.addRoundedRect(bubble, 4, 4)
        painter.setPen(QPen(_strokeColor(dark), 1))
        painter.setBrush(_surfaceColor(dark))
        painter.drawPath(path)
        painter.setPen(_textColor(dark))
        painter.drawText(
            bubble.adjusted(10, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
