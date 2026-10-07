from __future__ import annotations

import math
import sys

from PySide6.QtCore import QDateTime, QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTime
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
from app.platform.shadow_effect import paintSilhouetteShadow
from app.view.components.banner_widget import BannerWidget
from app.view.components.setting_card_group import SettingMaterialCard
from app.view.components.window_background import (
    TIMER_THEME_BACKGROUND,
    WindowBackground,
    projectionThemeBackground,
    projectionTitleColor,
)

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
# 投送、倒计时和时钟的角落按钮整组按这个比例画，图标才认得出。
ACTION_BUTTON_SCALE = 0.5


def _screenSize() -> QSize:
    screen = QGuiApplication.primaryScreen()
    size = screen.geometry().size() if screen is not None else QSize()
    return size if size.height() > 0 else QSize(1920, 1080)


def _screenAspectRatio() -> float:
    size = _screenSize()
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

    def _screenScale(self) -> float:
        """How much smaller than the real full-screen window the preview is."""
        return self.height() / _screenSize().height()

    def contentRect(self) -> QRectF:
        """The real window's layout margins, scaled to the preview."""
        scale = self._screenScale()
        bottom = 0 if self._contentKind == PROJECTION_CONTENT else 20
        return QRectF(self.rect()).adjusted(
            40 * scale, 20 * scale, -40 * scale, -bottom * scale
        )

    def actionButtonIcons(self) -> list:
        # 全屏时“窗口化”按钮画的是 COPY；按钮放左下角时整排顺序反过来。
        icons = {
            PROJECTION_CONTENT: [FIF.EDIT, FIF.MINIMIZE, FIF.COPY, FIF.CLOSE],
            COUNTDOWN_CONTENT: [FIF.SYNC, FIF.COPY, FIF.CLOSE],
            CLOCK_CONTENT: [FIF.COPY, FIF.CLOSE],
        }[self._contentKind]
        return icons[::-1] if self._buttonsAtLeft() else icons

    def _buttonsAtLeft(self) -> bool:
        return (
            self._actionPositionItem is not None
            and self._actionPositionItem.value == "左下角"
        )

    def actionButtonRects(self) -> list[QRectF]:
        # 真实按钮 80 × 65，间距和离边都是 12。整组按比例放大到 ACTION_BUTTON_SCALE，
        # 按屏幕比例缩小的话图标只剩几个像素。
        scale = ACTION_BUTTON_SCALE
        width, height, spacing = 80 * scale, 65 * scale, 12 * scale
        count = len(self.actionButtonIcons())
        total = count * width + (count - 1) * spacing
        left = spacing if self._buttonsAtLeft() else self.width() - spacing - total
        top = self.height() - spacing - height
        return [
            QRectF(left + index * (width + spacing), top, width, height)
            for index in range(count)
        ]

    def projectionTitle(self) -> str:
        return cfg.broadcastTitle.value.strip() or "投送标题"

    def timerText(self) -> str:
        if self._contentKind == COUNTDOWN_CONTENT:
            return "00 : 45 : 00"
        return QTime.currentTime().toString("HH : mm : ss")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
        )
        if self._contentKind == PROJECTION_CONTENT:
            self._paintProjection(painter, self.contentRect())
        else:
            self._paintTimer(painter, self.contentRect())
        self._paintActionButtons(painter)
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
            QFontMetricsF(font).elidedText(
                self.projectionTitle(), Qt.TextElideMode.ElideRight, rect.width()
            ),
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
        # 字号和上下留白照真实窗口：标题高的 1/14，时间 9/40，三段弹性空白 1 : 1 : 2。
        title = "考试倒计时" if self._contentKind == COUNTDOWN_CONTENT else "当前时间"
        text = self.timerText()
        titleFont = QFont(self.font())
        titleFont.setPixelSize(max(1, self.height() // 14))
        titleFont.setBold(True)
        timeFont = QFont(self.font())
        timeFont.setPixelSize(max(1, self.height() * 9 // 40))
        timeFont.setBold(True)
        # 预览宽度随屏幕比例变化，4:3 屏上时间会超出两侧，和真实窗口一样按比例缩小。
        width = QFontMetricsF(timeFont).horizontalAdvance(text)
        if width > rect.width():
            timeFont.setPixelSize(max(1, int(timeFont.pixelSize() * rect.width() / width)))
        titleHeight = QFontMetricsF(titleFont).height()
        timeHeight = QFontMetricsF(timeFont).height()
        free = max(0.0, rect.height() - titleHeight - timeHeight) / 4

        painter.setFont(titleFont)
        painter.setPen(QColor(255, 255, 255))
        titleTop = rect.top() + free
        painter.drawText(
            QRectF(rect.left(), titleTop, rect.width(), titleHeight),
            Qt.AlignmentFlag.AlignCenter,
            title,
        )
        painter.setFont(timeFont)
        painter.drawText(
            QRectF(rect.left(), titleTop + titleHeight + free, rect.width(), timeHeight),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    def _paintActionButtons(self, painter: QPainter) -> None:
        dark = self._darkFurniture()
        foreground = QColor(255, 255, 255) if dark else QColor(0, 0, 0)
        for icon, button in zip(self.actionButtonIcons(), self.actionButtonRects()):
            primary = icon is FIF.CLOSE
            # 与真实按钮同色：关闭是主题色，其余是按深浅主题的半透明底。细边让
            # 主题色的关闭按钮落在同色背景上也能分辨。
            painter.setPen(
                QPen(QColor(255, 255, 255, 110) if dark else QColor(0, 0, 0, 40), 1)
            )
            painter.setBrush(
                qconfig.themeColor.value
                if primary
                else QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 13)
            )
            radius = 8 * ACTION_BUTTON_SCALE
            painter.drawRoundedRect(button, radius, radius)
            # 图标在上、文字在下；文字缩小后认不出，用一道横条代替。
            color = QColor(255, 255, 255) if primary else foreground
            iconSize = 20 * ACTION_BUTTON_SCALE
            icon.icon(color=color).paint(
                painter,
                QRectF(
                    button.center().x() - iconSize / 2,
                    button.top() + 9 * ACTION_BUTTON_SCALE,
                    iconSize,
                    iconSize,
                ).toRect(),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            color.setAlpha(170)
            painter.setBrush(color)
            barTop = button.top() + (9 + 20 + 4 + 11) * ACTION_BUTTON_SCALE - 1.25
            painter.drawRoundedRect(
                QRectF(button.left() + button.width() * 0.3, barTop, button.width() * 0.4, 2.5),
                1.25,
                1.25,
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


def taskbarLayout(rect: QRectF) -> dict[str, QRectF]:
    """Where the Start button, DJCat, the Tray Icon and the clock sit.

    Win11 centres the buttons; Win10 keeps them on the left.
    """
    button = rect.height() - 8
    group = button * 2 + 4
    left = rect.left() + 4 if _isWindows10() else rect.center().x() - group / 2
    start = QRectF(left, rect.top() + 4, button, button)
    clock = QRectF(rect.right() - 84, rect.top(), 76, rect.height())
    tray = QRectF(clock.left() - 30, rect.center().y() - 8, 16, 16)
    return {
        "start": start,
        "application": start.translated(button + 4, 0),
        "clock": clock,
        "tray": tray,
        "chevron": QRectF(tray.left() - 26, rect.center().y() - 2.5, 9, 5),
    }


def paintTaskbar(painter: QPainter, rect: QRectF, dark: bool) -> None:
    """The Windows taskbar with DJCat running and its Tray Icon in the corner.

    Win11 draws a short pill under a running app, Win10 a line under the whole
    button.
    """
    win10 = _isWindows10()
    layout = taskbarLayout(rect)
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(28, 28, 28) if dark else QColor(238, 238, 238))
    painter.drawRect(rect)
    painter.setPen(QPen(QColor(255, 255, 255, 20) if dark else QColor(0, 0, 0, 20), 1))
    painter.drawLine(rect.topLeft(), rect.topRight())

    _paintWindowsLogo(painter, layout["start"].center(), 16 if win10 else 18)
    application = layout["application"]
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 18) if dark else QColor(255, 255, 255, 170))
    corner = 0 if win10 else 4
    painter.drawRoundedRect(application, corner, corner)
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
    clock = layout["clock"]
    lineHeight = QFontMetricsF(font).height()
    for top, value in (
        (rect.center().y() - lineHeight, now.toString("H:mm")),
        (rect.center().y(), now.toString("yyyy/M/d")),
    ):
        painter.drawText(
            QRectF(clock.left(), top, clock.width(), lineHeight),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            value,
        )

    trayIcon().paint(painter, layout["tray"].toRect())
    chevron = layout["chevron"]
    painter.setPen(QPen(text, 1.1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPolyline(
        [chevron.bottomLeft(), QPointF(chevron.center().x(), chevron.top()), chevron.bottomRight()]
    )
    painter.restore()


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


class TrayPreview(SettingPreviewCard):
    """The corner of the screen with the Tray Menu open above the taskbar.

    The menu comes from the tray's own ``buildTrayMenu()`` and keeps its real
    size, so its rows, icons and texts are exactly what a right click shows;
    it is placed by the same rules ``AcrylicMenu`` and ``RoundMenu`` follow.
    The tooltip really only shows while hovering, but sits beside the menu here
    so every tray setting can be read at a glance.
    """

    TOP_MARGIN = 16
    TOOLTIP_GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self._homeCards = []
        self.menuParts = None
        self._layout = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._rebuild()
        self._bind()

    def _bind(self) -> None:
        for item in (
            cfg.showBroadcastTrayAction,
            cfg.showHomeCardTaskTrayAction,
            cfg.showShutdownTrayAction,
            cfg.broadcastTasksEnabled,
            cfg.homeCardTasksEnabled,
            cfg.shutdownTasksEnabled,
            cfg.trayHomeCardKeys,
            cfg.trayHomeCardsInSubmenu,
            cfg.trayIconSource,
            cfg.trayIconPath,
            cfg.applicationIconSource,
            cfg.applicationIconPath,
            qconfig.themeColor,
        ):
            item.valueChanged.connect(self._rebuild)
        qconfig.themeChanged.connect(self._rebuild)
        cfg.trayTooltip.valueChanged.connect(self._relayout)

    def setHomeCards(self, entries) -> None:
        self._homeCards = [dict(entry) for entry in entries or [] if isinstance(entry, dict)]
        self._rebuild()

    def _rebuild(self, *_args) -> None:
        from app.common.application_icon import trayHomeIcon
        from app.view.shell.tray import buildTrayMenu

        if self.menuParts is not None:
            self.menuParts.menu.deleteLater()
        self._menuPixmaps = {}
        self.menuParts = buildTrayMenu(self._homeCards, trayHomeIcon(), self)
        submenu = self._submenu()
        height = self.menuParts.menu.view.height()
        if submenu is not None:
            # 打开二级菜单时，它的条目在菜单里保持选中的样子。
            self.menuParts.menu.view.setCurrentItem(self._submenuItem())
            height = max(height, submenu.view.height())
        self.setFixedHeight(self.TOP_MARGIN + height + taskbarHeight())
        self._relayout()

    def _menuPixmap(self, menu) -> QPixmap:
        # render() 直接画到本控件的 painter 上会被重定向偏移打乱位置，先截成图再贴。
        pixmap = self._menuPixmaps.get(id(menu))
        if pixmap is None or pixmap.devicePixelRatio() != self.devicePixelRatioF():
            pixmap = menu.view.grab()
            self._menuPixmaps[id(menu)] = pixmap
        return pixmap

    def _submenu(self):
        menus = self.menuParts.menu._subMenus
        return menus[0] if menus else None

    def _submenuItem(self):
        view = self.menuParts.menu.view
        submenu = self._submenu()
        for index in range(view.count()):
            if view.item(index).data(Qt.ItemDataRole.UserRole) is submenu:
                return view.item(index)
        return None

    def _relayout(self, *_args) -> None:
        self._layout = None
        self.update()

    def resizeEvent(self, event) -> None:
        self._relayout()
        super().resizeEvent(event)

    def taskbarRect(self) -> QRect:
        height = taskbarHeight()
        return QRect(0, self.height() - height, self.width(), height)

    def _screenRect(self) -> QRect:
        """What Qt calls the available geometry: the screen above the taskbar."""
        return QRect(0, 0, self.width(), self.taskbarRect().top())

    def _computeLayout(self) -> dict:
        if self._layout is not None:
            return self._layout
        screen = self._screenRect()
        tray = taskbarLayout(QRectF(self.taskbarRect()))["tray"]
        view = self.menuParts.menu.view
        # AcrylicMenu.adjustPosition：从光标处展开，右边放不下就贴着可用区域右边，底边贴着任务栏。
        width = view.width() + 5
        x = max(screen.left(), min(round(tray.center().x()), screen.right() - width))
        menu = QRect(x, screen.bottom() - view.height() + 1, view.width(), view.height())

        submenuRect = QRect()
        submenu = self._submenu()
        if submenu is not None:
            # RoundMenu._onShowMenuTimeOut：条目右侧 5 px，放不下就开到左侧。
            item = self._submenuItem()
            itemRect = view.visualItemRect(item).translated(menu.topLeft())
            size = submenu.view.size()
            left = itemRect.right() + 5
            if left + size.width() > screen.right():
                left = max(itemRect.left() - size.width() - 5, screen.left())
            top = itemRect.y() - 5
            if top + size.height() > screen.bottom():
                top = screen.bottom() - size.height()
            submenuRect = QRect(QPoint(left, max(top, screen.top())), size)

        text = self.tooltipText()
        font = getFont(12)
        metrics = QFontMetricsF(font)
        tooltipWidth = min(
            math.ceil(metrics.horizontalAdvance(text)) + 16,
            max(40, menu.left() - self.TOOLTIP_GAP - 8),
        )
        tooltipHeight = math.ceil(metrics.height()) + 12
        left = menu.left() if submenuRect.isNull() else min(menu.left(), submenuRect.left())
        tooltipRight = left - self.TOOLTIP_GAP
        tooltip = QRect(
            tooltipRight - tooltipWidth,
            screen.bottom() - 8 - tooltipHeight,
            tooltipWidth,
            tooltipHeight,
        )
        self._layout = {
            "menu": menu,
            "submenu": submenuRect,
            "tooltip": tooltip,
            "font": font,
        }
        return self._layout

    def menuRect(self) -> QRect:
        return self._computeLayout()["menu"]

    def submenuRect(self) -> QRect:
        return self._computeLayout()["submenu"]

    def tooltipRect(self) -> QRect:
        return self._computeLayout()["tooltip"]

    def tooltipText(self) -> str:
        return cfg.trayTooltip.value.strip() or APP_NAME

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        layout = self._computeLayout()
        dark = isDarkTheme()
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        card = QPainterPath()
        radius = self.borderRadius
        card.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), radius, radius)
        painter.setClipPath(card)
        paintTaskbar(painter, QRectF(self.taskbarRect()), dark)

        # Win10 的托盘菜单是方角，Win11 保留圆角；底色近似亚克力，透出的桌面画不出来。
        cornerRadius = 0 if _isWindows10() else 8
        menus = [(self.menuParts.menu, layout["menu"])]
        if self._submenu() is not None:
            menus.append((self._submenu(), layout["submenu"]))
        for menu, rect in menus:
            paintSilhouetteShadow(painter, QRectF(rect), cornerRadius, 24, 0.22)
            path = QPainterPath()
            path.addRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), cornerRadius, cornerRadius)
            painter.fillPath(path, QColor(44, 44, 44) if dark else QColor(249, 249, 249))
            painter.drawPixmap(rect.topLeft(), self._menuPixmap(menu))

        self._paintTooltip(painter, layout, dark)

    def _paintTooltip(self, painter: QPainter, layout: dict, dark: bool) -> None:
        rect = QRectF(layout["tooltip"])
        if rect.width() <= 0:
            return
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        painter.fillPath(path, QColor(43, 43, 43) if dark else QColor(249, 249, 249))
        painter.setPen(QPen(_strokeColor(dark), 1))
        painter.drawPath(path)
        painter.setFont(layout["font"])
        painter.setPen(_textColor(dark))
        text = QFontMetricsF(layout["font"]).elidedText(
            self.tooltipText(), Qt.TextElideMode.ElideRight, rect.width() - 16
        )
        painter.drawText(
            rect.adjusted(8, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
