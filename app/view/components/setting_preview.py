from __future__ import annotations

import math
import sys

from PySide6.QtCore import QDateTime, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FlowLayout,
    FluentStyleSheet,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
    getFont,
    isDarkTheme,
    qconfig,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets.components.navigation.navigation_bar import (
    NavigationBarPushButton,
)
from qframelesswindow.titlebar import CloseButton, MaximizeButton, MinimizeButton

from app.common.application_icon import applicationIcon, trayIcon
from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.components.banner_widget import BannerWidget
from app.view.components.setting_card_group import SettingMaterialCard
from app.view.components.window_background import (
    TIMER_THEME_BACKGROUND,
    WindowBackground,
    projectionThemeBackground,
    projectionTitleColor,
)

PREVIEW_RADIUS = 8

# 投送、倒计时和时钟三种窗口的正文形状不同，预览按各自真实的排布画。
PROJECTION_CONTENT = "projection"
COUNTDOWN_CONTENT = "countdown"
CLOCK_CONTENT = "clock"

MAIN_WINDOW_PREVIEW_HEIGHT = 280


class SettingPreviewCard(SettingMaterialCard):
    """Previews that draw loose parts sit on the same material as the cards,
    otherwise they read as unfinished page content rather than a preview."""


def _isWindows10() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build < 22000


def _strokeColor(dark: bool) -> QColor:
    return QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 18)


def _textColor(dark: bool) -> QColor:
    return QColor(255, 255, 255, 222) if dark else QColor(0, 0, 0, 222)


WINDOW_PREVIEW_HEIGHT = 216


def _screenAspectRatio() -> float:
    screen = QGuiApplication.primaryScreen()
    size = screen.geometry().size() if screen is not None else None
    if not size or size.height() <= 0:
        return 16 / 9
    return min(2.4, max(1.25, size.width() / size.height()))


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
        # 默认背景和真实窗口取同一个底色：投送跟随深浅主题，倒计时和时钟是黑底。
        projection = contentKind == PROJECTION_CONTENT
        super().__init__(
            modeItem,
            colorItem,
            imagePathItem,
            scaleModeItem,
            projectionThemeBackground if projection else (lambda: TIMER_THEME_BACKGROUND),
            parent=parent,
        )
        self._contentKind = contentKind
        self._actionPositionItem = actionPositionItem
        # 三种窗口默认全屏：按屏幕比例画，图片背景的裁切位置才和真实窗口一致。
        self.setFixedSize(
            round(WINDOW_PREVIEW_HEIGHT * _screenAspectRatio()), WINDOW_PREVIEW_HEIGHT
        )
        self.setRoundedWindow(True, shadow=False)
        if actionPositionItem is not None:
            actionPositionItem.valueChanged.connect(self._onActionPositionChanged)
        if projection:
            qconfig.themeChanged.connect(self._invalidate)

    def _darkFurniture(self) -> bool:
        """投送窗口的文字和按钮跟随深浅主题；倒计时和时钟始终是黑底上的白字。"""
        return self._contentKind != PROJECTION_CONTENT or isDarkTheme()

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
        painter.setPen(projectionTitleColor())
        painter.drawText(
            QRectF(rect.left(), rect.top(), rect.width(), 26),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "投送标题",
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            QColor(255, 255, 255, 132) if self._darkFurniture() else QColor(0, 0, 0, 110)
        )
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
        text = "00 : 45 : 00" if self._contentKind == COUNTDOWN_CONTENT else "09 : 24 : 30"
        font.setPixelSize(46)
        font.setWeight(QFont.Weight.DemiBold)
        # 预览宽度随屏幕比例变化，4:3 屏上 46 px 的时间会超出两侧。
        width = QFontMetricsF(font).horizontalAdvance(text)
        available = rect.width() * 0.88
        if width > available:
            font.setPixelSize(max(12, int(46 * available / width)))
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 235))
        painter.drawText(
            QRectF(rect.left(), rect.top() + 36, rect.width(), 60),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            text,
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

        dark = self._darkFurniture()
        for index in range(count):
            button = QRectF(left + index * (width + spacing), top, width, height)
            primary = index == count - 1
            # 与真实窗口的按钮同色：关闭是主题色，其余是按深浅主题的半透明底。细边让
            # 主题色的关闭按钮落在同色背景上也能分辨。
            painter.setPen(
                QPen(QColor(255, 255, 255, 110) if dark else QColor(0, 0, 0, 40), 1)
            )
            painter.setBrush(
                qconfig.themeColor.value
                if primary
                else QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 13)
            )
            painter.drawRoundedRect(button, 5, 5)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(
                QColor(255, 255, 255, 200)
                if primary or dark
                else QColor(0, 0, 0, 170)
            )
            painter.drawRoundedRect(
                QRectF(button.center().x() - 5, button.top() + 9, 10, 10), 2, 2
            )
            painter.drawRoundedRect(
                QRectF(button.left() + 6, button.bottom() - 12, width - 12, 4), 2, 2
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)


# 主窗口的真实尺寸。MainWindowReplica 的测试逐一核对它们和真实主窗口一致。
TITLE_BAR_HEIGHT = 48
NAVIGATION_WIDTH = 72
CAPTION_BUTTON_SIZE = QSize(46, 32)
NAVIGATION_BUTTON_SIZE = QSize(64, 58)
MAIN_WINDOW_MINIMUM_SIZE = QSize(700, 400)
SPLASH_ICON_SIZE = 96

# NavigationBar 的排布：顶部从 5 起每项占 62，底部从下往上同样每项占 62。
_TOP_NAVIGATION = (
    ("HomePage", FIF.HOME, "主页"),
    ("AppStorePage", FIF.APPLICATION, "应用下载"),
)
_BOTTOM_NAVIGATION = (
    ("CreditsPage", FIF.HEART, "特别鸣谢"),
    ("SettingPage", FIF.SETTING, "设置"),
)


class MainWindowReplica(QWidget):
    """The main window rebuilt from its real components at its real size.

    It is never shown. Previews lay it out at the main window's current size,
    render it and scale the result down, so every proportion, font and colour
    is the real one. The live pages are not grabbed instead: that would force
    Lazy Pages into existence and capture the settings page inside itself
    (see docs/adr/0007-setting-preview-replica.md).
    """

    def __init__(self, splash: bool = False, parent=None):
        super().__init__(parent)
        self.splash = splash
        self._homeCards = []
        self.cards = {}
        self.page = QWidget(self)
        self.banner = BannerWidget(self.page)
        self.pageTitle = TitleLabel("主页", self.page)
        self.subTitle = SubtitleLabel("常用功能", self.page)
        self.sortButton = ToolButton(FIF.EDIT, self.page)
        self.cardsWidget = QWidget(self.page)
        self.flowLayout = FlowLayout(self.cardsWidget, needAni=False)
        self.navigationButtons = {
            key: NavigationBarPushButton(icon, text, True, parent=self)
            for key, icon, text in (*_TOP_NAVIGATION, *_BOTTOM_NAVIGATION)
        }
        self.minBtn = MinimizeButton(self)
        self.maxBtn = MaximizeButton(self)
        self.closeBtn = CloseButton(self)

        self._initWidget()

    def _initWidget(self) -> None:
        # 显式隐藏：作为预览的子控件，父控件显示时它也不能跟着出现。
        self.hide()
        self.flowLayout.setContentsMargins(20, 10, 20, 20)
        self.navigationButtons["HomePage"].setSelected(True)
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            button.setFixedSize(CAPTION_BUTTON_SIZE)
            FluentStyleSheet.FLUENT_WINDOW.apply(button)

    def setHomeCards(self, entries) -> None:
        from app.view.pages.home_page import ActionCard

        for card in self.cards.values():
            self.flowLayout.removeWidget(card)
            card.deleteLater()
        self.cards = {}
        for entry in entries or []:
            key = entry.get("key") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not key or key in self.cards:
                continue
            card = ActionCard(
                entry["icon"],
                entry["title"],
                entry.get("description", ""),
                self.cardsWidget,
            )
            self.cards[key] = card
            self.flowLayout.addWidget(card)

    def windowTitle(self) -> str:
        return cfg.windowTitle.value.strip() or APP_NAME

    def layoutFor(self, size: QSize) -> QSize:
        """Place every part where the real main window of ``size`` has it."""
        size = size.expandedTo(MAIN_WINDOW_MINIMUM_SIZE)
        width, height = size.width(), size.height()
        self.resize(size)

        for index, button in enumerate((self.minBtn, self.maxBtn, self.closeBtn)):
            button.move(width - CAPTION_BUTTON_SIZE.width() * (3 - index), 0)

        for index, (key, _icon, _text) in enumerate(_TOP_NAVIGATION):
            self.navigationButtons[key].setGeometry(
                QRect(QPoint(4, TITLE_BAR_HEIGHT + 5 + 62 * index), NAVIGATION_BUTTON_SIZE)
            )
        credits = self.navigationButtons["CreditsPage"]
        credits.setVisible(bool(cfg.showCreditsPage.value))
        bottom = [key for key, _icon, _text in _BOTTOM_NAVIGATION]
        if credits.isHidden():
            bottom.remove("CreditsPage")
        for index, key in enumerate(reversed(bottom)):
            self.navigationButtons[key].setGeometry(
                QRect(QPoint(4, height - 63 - 62 * index), NAVIGATION_BUTTON_SIZE)
            )

        # 页面在 StackedWidget 1 px 边框之内。
        pageWidth = width - NAVIGATION_WIDTH - 1
        self.page.setGeometry(
            NAVIGATION_WIDTH + 1, TITLE_BAR_HEIGHT + 1, pageWidth, height - TITLE_BAR_HEIGHT - 1
        )
        showBanner = bool(cfg.showBanner.value)
        self.banner.setVisible(showBanner)
        self.pageTitle.setVisible(not showBanner)
        if showBanner:
            self.banner.setGeometry(0, 0, pageWidth, self.banner.height())
            top = self.banner.height()
        else:
            titleHeight = self.pageTitle.sizeHint().height()
            self.pageTitle.setGeometry(30, 20, pageWidth - 60, titleHeight)
            top = 20 + titleHeight + 10

        top += 10
        buttonSize = self.sortButton.sizeHint()
        headerHeight = max(buttonSize.height(), self.subTitle.sizeHint().height())
        self.subTitle.setGeometry(30, top, self.subTitle.sizeHint().width(), headerHeight)
        self.sortButton.setGeometry(
            pageWidth - 30 - buttonSize.width(), top, buttonSize.width(), headerHeight
        )

        top += headerHeight + 10
        self.cardsWidget.setGeometry(
            0, top, pageWidth, self.flowLayout.heightForWidth(pageWidth)
        )
        self.flowLayout.setGeometry(self.cardsWidget.rect())
        # 隐藏的控件不会自己排版：每个带布局的部件手动排一次。
        for widget in (self.banner, *self.cards.values()):
            widget.layout().activate()
        return size

    def renderPixmap(self, size: QSize, scale: float, ratio: float) -> QPixmap:
        """The window at ``size`` scaled by ``scale``, in device pixels."""
        size = self.layoutFor(size)
        # 先画到目标的两倍再平滑缩小：直接按零点几倍画，文字和横幅会起锯齿。
        drawScale = min(1.0, scale * 2) * ratio
        image = QImage(
            math.ceil(size.width() * drawScale),
            math.ceil(size.height() * drawScale),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.scale(drawScale, drawScale)
        if self.splash:
            self._paintSplash(painter, size)
        else:
            self._paintWindow(painter, size)
        painter.end()

        target = QSize(
            max(1, round(size.width() * scale * ratio)),
            max(1, round(size.height() * scale * ratio)),
        )
        pixmap = QPixmap.fromImage(
            image.scaled(
                target,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        pixmap.setDevicePixelRatio(ratio)
        return pixmap

    @staticmethod
    def _renderChild(painter: QPainter, widget: QWidget) -> None:
        if not widget.isHidden():
            widget.render(painter, widget.pos(), renderFlags=QWidget.RenderFlag.DrawChildren)

    def _paintWindow(self, painter: QPainter, size: QSize) -> None:
        dark = isDarkTheme()
        width, height = size.width(), size.height()
        # FluentWindowBase 关掉云母时的底色，以及 StackedWidget 的左上圆角面板。
        painter.fillRect(
            QRectF(0, 0, width, height),
            QColor(32, 32, 32) if dark else QColor(240, 244, 249),
        )
        panel = QPainterPath()
        panel.moveTo(width, TITLE_BAR_HEIGHT + 0.5)
        panel.lineTo(NAVIGATION_WIDTH + 10.5, TITLE_BAR_HEIGHT + 0.5)
        panel.arcTo(
            QRectF(NAVIGATION_WIDTH + 0.5, TITLE_BAR_HEIGHT + 0.5, 20, 20), 90, 90
        )
        panel.lineTo(NAVIGATION_WIDTH + 0.5, height)
        fill = QPainterPath(panel)
        fill.lineTo(width, height)
        fill.closeSubpath()
        painter.fillPath(fill, QColor(255, 255, 255, 8) if dark else QColor(255, 255, 255, 128))
        painter.strokePath(
            panel, QPen(QColor(0, 0, 0, 46) if dark else QColor(0, 0, 0, 17), 1)
        )

        self.page.render(
            painter, self.page.pos(), renderFlags=QWidget.RenderFlag.DrawChildren
        )
        for button in self.navigationButtons.values():
            self._renderChild(painter, button)
        self._paintTitleBar(painter, width, dark)

    def _paintTitleBar(self, painter: QPainter, width: int, dark: bool) -> None:
        # MSFluentTitleBar：左边 20 的留白、18 的图标、2 的间隔，标题文字另有 10 的内边距。
        applicationIcon().paint(painter, QRect(20, 15, 18, 18))
        font = getFont(13)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255) if dark else QColor(0, 0, 0))
        left = 20 + 18 + 2 + 10
        available = width - left - CAPTION_BUTTON_SIZE.width() * 3 - 10
        text = QFontMetricsF(font).elidedText(
            self.windowTitle(), Qt.TextElideMode.ElideRight, available
        )
        painter.drawText(
            QRectF(left, 15, available, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            self._renderChild(painter, button)

    def _paintSplash(self, painter: QPainter, size: QSize) -> None:
        # SplashScreen 铺满窗口，只留标题栏按钮和正中 96 px 的图标。
        shade = 32 if isDarkTheme() else 255
        painter.fillRect(QRectF(0, 0, size.width(), size.height()), QColor(shade, shade, shade))
        applicationIcon().paint(
            painter,
            QRect(
                size.width() // 2 - SPLASH_ICON_SIZE // 2,
                size.height() // 2 - SPLASH_ICON_SIZE // 2,
                SPLASH_ICON_SIZE,
                SPLASH_ICON_SIZE,
            ),
        )
        for button in (self.minBtn, self.maxBtn, self.closeBtn):
            self._renderChild(painter, button)


class MainWindowMiniature(QWidget):
    """A MainWindowReplica fitted into this widget at the main window's aspect.

    The rendered pixmap is cached: scrolling the settings page repaints the
    preview every frame, and rebuilding the replica each time would be costly.
    """

    def __init__(self, splash: bool = False, parent=None):
        super().__init__(parent)
        self._splash = splash
        self._replica = None
        self._homeCards = []
        self._pixmap = None
        self._pixmapKey = None
        self._observedWindow = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        for item in (
            cfg.showBanner,
            cfg.bannerImageSource,
            cfg.bannerImagePath,
            cfg.bannerBrightness,
            cfg.bannerScaleMode,
            cfg.windowTitle,
            cfg.applicationIconSource,
            cfg.applicationIconPath,
            cfg.showCreditsPage,
            qconfig.themeColor,
        ):
            item.valueChanged.connect(self.invalidate)
        qconfig.themeChanged.connect(self.invalidate)

    def invalidate(self, *_args) -> None:
        self._pixmap = None
        self.update()

    @property
    def replica(self) -> MainWindowReplica:
        # 大多数 Section 一次会话里不会打开，第一次画的时候才搭复刻。
        if self._replica is None:
            self._replica = MainWindowReplica(self._splash, self)
            self._replica.setHomeCards(self._homeCards)
        return self._replica

    def setHomeCards(self, entries) -> None:
        self._homeCards = list(entries or [])
        if self._replica is not None:
            self._replica.setHomeCards(self._homeCards)
        self.invalidate()

    def mainWindowSize(self) -> QSize:
        window = self.window()
        size = window.size() if window is not self else QSize()
        return size.expandedTo(MAIN_WINDOW_MINIMUM_SIZE)

    def windowRect(self) -> QRectF:
        size = self.mainWindowSize()
        area = QRectF(self.rect())
        scale = min(area.width() / size.width(), area.height() / size.height())
        width, height = size.width() * scale, size.height() * scale
        return QRectF(
            area.center().x() - width / 2, area.center().y() - height / 2, width, height
        )

    def renderedPixmap(self) -> QPixmap:
        size = self.mainWindowSize()
        rect = self.windowRect()
        ratio = self.devicePixelRatioF()
        key = (size.width(), size.height(), rect.width(), rect.height(), ratio)
        if self._pixmap is None or self._pixmapKey != key:
            scale = rect.width() / size.width()
            self._pixmap = self.replica.renderPixmap(size, scale, ratio)
            self._pixmapKey = key
        return self._pixmap

    def showEvent(self, event) -> None:
        window = self.window()
        if window is not self._observedWindow:
            if self._observedWindow is not None:
                self._observedWindow.removeEventFilter(self)
            self._observedWindow = window
            window.installEventFilter(self)
        super().showEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._observedWindow and event.type() == QEvent.Type.Resize:
            self.update()
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:
        rect = self.windowRect()
        if rect.width() < 2 or rect.height() < 2:
            return
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        # Win11 的窗口有 8 px 圆角，Win10 是直角；缩小后的圆角按同一比例。
        radius = 0 if _isWindows10() else 8 * rect.width() / self.mainWindowSize().width()
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(path)
        painter.drawPixmap(rect.topLeft(), self.renderedPixmap())
        painter.restore()
        painter.setPen(QPen(QColor(255, 255, 255, 40) if isDarkTheme() else QColor(0, 0, 0, 40), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


class MainWindowPreview(SettingPreviewCard):
    """The whole main window, at its current aspect, as the settings shape it."""

    MARGIN = 16

    def __init__(self, parent=None):
        super().__init__(parent)
        self.miniature = MainWindowMiniature(parent=self)
        self.vBoxLayout = QVBoxLayout(self)

        self.setFixedHeight(MAIN_WINDOW_PREVIEW_HEIGHT)
        self.vBoxLayout.setContentsMargins(
            self.MARGIN, self.MARGIN, self.MARGIN, self.MARGIN
        )
        self.vBoxLayout.addWidget(self.miniature)

    def setHomeCards(self, entries) -> None:
        self.miniature.setHomeCards(entries)

    def windowRect(self) -> QRectF:
        return self.miniature.windowRect().translated(self.miniature.pos())

    def renderedPixmap(self) -> QPixmap:
        return self.miniature.renderedPixmap()


def taskbarHeight() -> int:
    return 40 if _isWindows10() else 48


def _paintWindowsLogo(painter: QPainter, center, size: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0078d4"))
    gap = size / 12
    tile = (size - gap) / 2
    left, top = center.x() - size / 2, center.y() - size / 2
    for row in range(2):
        for column in range(2):
            painter.drawRect(
                QRectF(left + column * (tile + gap), top + row * (tile + gap), tile, tile)
            )


def paintTaskbar(painter: QPainter, rect: QRectF, dark: bool) -> QRectF:
    """The Windows taskbar with DJCat running; returns the Tray Icon's rect.

    Win11 centres the buttons and draws a short pill under a running app;
    Win10 keeps them on the left with a line under the whole button.
    """
    win10 = _isWindows10()
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(28, 28, 28) if dark else QColor(238, 238, 238))
    painter.drawRect(rect)
    painter.setPen(QPen(QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 20), 1))
    painter.drawLine(rect.topLeft(), rect.topRight())

    button = rect.height() - 8
    group = button * 2 + 4
    left = rect.left() + 4 if win10 else rect.center().x() - group / 2
    start = QRectF(left, rect.top() + 4, button, button)
    application = start.translated(button + 4, 0)
    _paintWindowsLogo(painter, start.center(), 18 if not win10 else 16)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 18) if dark else QColor(255, 255, 255, 170))
    painter.drawRoundedRect(application, 0 if win10 else 4, 0 if win10 else 4)
    applicationIcon().paint(
        painter,
        QRectF(application.center().x() - 12, application.center().y() - 12, 24, 24).toRect(),
    )
    painter.setBrush(QColor(255, 255, 255, 130) if dark else QColor(0, 0, 0, 110))
    if win10:
        painter.drawRect(QRectF(application.left(), rect.bottom() - 2, application.width(), 2))
    else:
        painter.drawRoundedRect(
            QRectF(application.center().x() - 3, rect.bottom() - 5, 6, 3), 1.5, 1.5
        )

    text = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
    font = getFont(12)
    painter.setFont(font)
    painter.setPen(text)
    now = QDateTime.currentDateTime()
    clock = QRectF(rect.right() - 84, rect.top(), 76, rect.height())
    lineHeight = QFontMetricsF(font).height()
    painter.drawText(
        QRectF(clock.left(), rect.center().y() - lineHeight, clock.width(), lineHeight),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        now.toString("H:mm"),
    )
    painter.drawText(
        QRectF(clock.left(), rect.center().y(), clock.width(), lineHeight),
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        now.toString("yyyy/M/d"),
    )

    tray = QRectF(clock.left() - 30, rect.center().y() - 8, 16, 16)
    trayIcon().paint(painter, tray.toRect())
    chevron = QRectF(tray.left() - 26, rect.center().y() - 2.5, 9, 5)
    painter.setPen(QPen(text, 1.1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(
        [chevron.bottomLeft(), QPointF(chevron.center().x(), chevron.top()), chevron.bottomRight()]
    )
    painter.restore()
    return tray


class TaskbarStrip(QWidget):
    """A strip of the Windows taskbar with DJCat running in it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(taskbarHeight())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 6, 6)
        painter.setClipPath(path)
        paintTaskbar(painter, QRectF(self.rect()), isDarkTheme())


class ApplicationIconPreview(SettingPreviewCard):
    """The Application Icon where it shows: the splash screen while DJCat starts,
    the title bar once it runs, and the taskbar, where the Tray Icon follows it
    unless the tray has its own image."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.splashMiniature = MainWindowMiniature(splash=True, parent=self)
        self.windowMiniature = MainWindowMiniature(parent=self)
        self.taskbar = TaskbarStrip(self)
        self.vBoxLayout = QVBoxLayout(self)
        self.windowsLayout = QHBoxLayout()

        self._initLayout()
        self._bind()

    def _initLayout(self) -> None:
        self.setFixedHeight(MAIN_WINDOW_PREVIEW_HEIGHT)
        self.vBoxLayout.setContentsMargins(16, 16, 16, 16)
        self.vBoxLayout.setSpacing(12)
        self.windowsLayout.setSpacing(16)
        for miniature, caption in (
            (self.splashMiniature, "启动时"),
            (self.windowMiniature, "运行时"),
        ):
            column = QVBoxLayout()
            column.setSpacing(6)
            column.addWidget(miniature, 1)
            column.addWidget(CaptionLabel(caption, self), 0, Qt.AlignmentFlag.AlignHCenter)
            self.windowsLayout.addLayout(column, 1)
        self.vBoxLayout.addLayout(self.windowsLayout, 1)
        self.vBoxLayout.addWidget(self.taskbar)

    def _bind(self) -> None:
        for item in (
            cfg.applicationIconSource,
            cfg.applicationIconPath,
            cfg.trayIconSource,
            cfg.trayIconPath,
        ):
            item.valueChanged.connect(self.taskbar.update)
        qconfig.themeChanged.connect(self.taskbar.update)

    def setHomeCards(self, entries) -> None:
        self.windowMiniature.setHomeCards(entries)
