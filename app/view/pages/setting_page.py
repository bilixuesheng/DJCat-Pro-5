import threading

from loguru import logger
from PySide6.QtCore import QUrl, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ColorDialog,
    ColorSettingCard as FluentColorSettingCard,
    ComboBoxSettingCard,
    FluentIcon,
    HyperlinkCard,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PrimaryPushSettingCard,
    PushSettingCard,
    RadioButton,
    RangeSettingCard,
    SettingCard,
    SwitchButton,
    SwitchSettingCard,
    TextEdit,
    TitleLabel,
    ToolButton,
    setThemeColor,
)

from app.common.ai_markdown import PEAK_HOURS_TEXT, fetchQuota
from app.common.application_store import (
    ApplicationStoreError,
    appStoreImageCache,
    clearAppStoreCache,
)
from app.config.cfg import (
    BANNER_IMAGE_PRESETS,
    BANNER_PRESET_SCALE_MODES,
    THEME_COLOR_PRESETS,
    WINDOW_BACKGROUND_MODES,
    WINDOW_BACKGROUND_SCALE_MODES,
    cfg,
)
from app.config.constants import APP_NAME, AUTHOR, AUTHOR_URL, VERSION, YEAR
from app.config.paths import LOG_DIR
from app.signal_bus import signalBus
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import (
    CollapsibleSettingCard,
    CollapsibleSettingCardGroup,
)

CUSTOM_STYLE_PLACEHOLDER = (
    "所有关于值日的消息全部使用---与前面的任务分割开，然后使用"
    "**⚠️请值日人员到卫生区打扫⚠️**来写入之日内容。"
)
CUSTOM_STYLE_MAX_LENGTH = 4000


class LineEditSettingCard(SettingCard):
    def __init__(
        self,
        icon,
        title: str,
        content: str = "",
        configItem=None,
        parent=None,
        placeholder: str = "",
    ):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.lineEdit = LineEdit(self)

        self._initWidget(placeholder)
        self._initLayout()
        self._bind()

    def _initWidget(self, placeholder: str) -> None:
        self.lineEdit.setMinimumWidth(180)
        self.lineEdit.setClearButtonEnabled(True)
        self.lineEdit.setPlaceholderText(placeholder)
        self.lineEdit.setText(self.configItem.value)

    def _initLayout(self) -> None:
        self.hBoxLayout.addWidget(self.lineEdit)
        self.hBoxLayout.addSpacing(16)

    def _bind(self) -> None:
        self.lineEdit.editingFinished.connect(
            lambda: cfg.set(self.configItem, self.lineEdit.text())
        )


class CacheSettingCard(SettingCard):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.FOLDER,
            "缓存",
            "缓存应用图片和临时安装包，清理后会在需要时重新下载",
            parent,
        )
        self.sizeLabel = BodyLabel("0 B", self)
        self.clearButton = ToolButton(FluentIcon.DELETE, self)
        self.clearButton.setAccessibleName("清除缓存")
        self.clearButton.clicked.connect(self.clicked)
        self.hBoxLayout.addWidget(self.sizeLabel)
        self.hBoxLayout.addWidget(self.clearButton)
        self.hBoxLayout.addSpacing(16)
        self.setCacheSize(0)

    def setCacheSize(self, size: int) -> None:
        size = max(0, int(size))
        units = ("B", "KB", "MB", "GB")
        value = float(size)
        unit = units[0]
        for unit in units:
            if value < 1024 or unit == units[-1]:
                break
            value /= 1024
        text = f"{value:.1f} {unit}" if unit != "B" else f"{size} B"
        self.sizeLabel.setText(text)
        self.clearButton.setEnabled(size > 0)


class LocalizedColorSettingCard(FluentColorSettingCard):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.colorPicker.clicked.disconnect()
        self.colorPicker.clicked.connect(self._showColorDialog)

    def _showColorDialog(self) -> None:
        dialog = ColorDialog(
            self.colorPicker.color,
            f"选择{self.titleLabel.text()}",
            self.window(),
            self.colorPicker.enableAlpha,
        )
        dialog.colorChanged.connect(self.colorPicker.setColor)
        dialog.colorChanged.connect(self.colorPicker.colorChanged)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()


class ThemeColorSettingCard(CollapsibleSettingCard):
    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.PALETTE,
            "应用主题色",
            "设置软件的全局主题色",
            parent,
        )
        self._initWidget()
        self._initLayout()
        self._loadSelection()
        self._bind()

    def _initWidget(self) -> None:
        self.choiceLabel = BodyLabel(self)
        self.radioWidget = QWidget(self.view)
        self.radioLayout = QVBoxLayout(self.radioWidget)
        self.buttonGroup = QButtonGroup(self)
        self.presetButtons = {
            name: RadioButton(
                f"预设: {name} ({rgb[0]}, {rgb[1]}, {rgb[2]})",
                self.radioWidget,
            )
            for name, rgb in THEME_COLOR_PRESETS
        }
        self.customButton = RadioButton("自定义颜色", self.radioWidget)

    def _initLayout(self) -> None:
        self.addWidget(self.choiceLabel)
        self.radioLayout.setSpacing(19)
        self.radioLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.radioLayout.setContentsMargins(48, 18, 0, 18)
        for button in [*self.presetButtons.values(), self.customButton]:
            self.buttonGroup.addButton(button)
            self.radioLayout.addWidget(button)
        self.addGroupWidget(self.radioWidget)

    def _bind(self) -> None:
        self.buttonGroup.buttonClicked.connect(self._onButtonClicked)

    def _loadSelection(self) -> None:
        preset = cfg.themeColorPreset.value
        button = self.customButton if preset == "自定义" else self.presetButtons[preset]
        button.setChecked(True)
        self.choiceLabel.setText(button.text())

    def _onButtonClicked(self, button) -> None:
        self.choiceLabel.setText(button.text())
        preset = next(
            (
                name
                for name, presetButton in self.presetButtons.items()
                if button is presetButton
            ),
            None,
        )
        if preset is None:
            cfg.set(cfg.themeColorPreset, "自定义")
            dialog = ColorDialog(
                cfg.customThemeColor.value,
                "选择主题色",
                self.window(),
            )
            dialog.colorChanged.connect(self._setThemeColor)
            try:
                dialog.exec()
            finally:
                dialog.deleteLater()
            return
        cfg.set(cfg.themeColorPreset, preset)
        rgb = next(rgb for name, rgb in THEME_COLOR_PRESETS if name == preset)
        self._setThemeColor(QColor(*rgb))

    @staticmethod
    def _setThemeColor(color: QColor) -> None:
        cfg.set(cfg.customThemeColor, color)
        setThemeColor(color)


class AIMarkdownStyleSettingCard(CollapsibleSettingCard):
    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.EDIT,
            "自定义微调Markdown风格",
            "根据偏好调整 AI 输出的 Markdown 格式，最多 4000 个字符",
            parent,
        )
        self.switchButton = SwitchButton(self)
        self.editorWidget = QWidget(self.view)
        self.editorLayout = QVBoxLayout(self.editorWidget)
        self.textEdit = TextEdit(self.editorWidget)
        self.limitLabel = BodyLabel(self.editorWidget)
        self.saveTimer = QTimer(self)

        self.card.expandButton.hide()
        self.addWidget(self.switchButton)
        self.textEdit.setMinimumHeight(150)
        self.textEdit.setPlaceholderText(CUSTOM_STYLE_PLACEHOLDER)
        initialText = cfg.aiMarkdownCustomStyle.value
        initialTrimmed = len(initialText) > CUSTOM_STYLE_MAX_LENGTH
        if initialTrimmed:
            initialText = initialText[:CUSTOM_STYLE_MAX_LENGTH]
            cfg.set(cfg.aiMarkdownCustomStyle, initialText)
        self.textEdit.setPlainText(initialText)
        self.editorLayout.setContentsMargins(48, 16, 24, 20)
        self.editorLayout.addWidget(self.textEdit)
        self.editorLayout.addWidget(
            self.limitLabel,
            alignment=Qt.AlignmentFlag.AlignRight,
        )
        self.addGroupWidget(self.editorWidget)
        self._updateLimitLabel(initialTrimmed)

        enabled = cfg.aiMarkdownCustomStyleEnabled.value
        self.switchButton.setChecked(enabled)
        self.switchButton.setText("开启" if enabled else "关闭")
        self.setExpandedImmediately(enabled)

        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(400)
        self.saveTimer.timeout.connect(self.flushPendingSave)
        self.switchButton.checkedChanged.connect(self._onCheckedChanged)
        self.textEdit.textChanged.connect(self._onTextChanged)

    def _onCheckedChanged(self, enabled: bool) -> None:
        cfg.set(cfg.aiMarkdownCustomStyleEnabled, enabled)
        self.switchButton.setText("开启" if enabled else "关闭")
        self.setExpand(enabled)

    def flushPendingSave(self) -> None:
        self.saveTimer.stop()
        cfg.set(
            cfg.aiMarkdownCustomStyle,
            self.textEdit.toPlainText()[:CUSTOM_STYLE_MAX_LENGTH],
        )

    def _onTextChanged(self) -> None:
        text = self.textEdit.toPlainText()
        trimmed = len(text) > CUSTOM_STYLE_MAX_LENGTH
        if trimmed:
            cursor = self.textEdit.textCursor()
            position = min(cursor.position(), CUSTOM_STYLE_MAX_LENGTH)
            self.textEdit.blockSignals(True)
            self.textEdit.setPlainText(text[:CUSTOM_STYLE_MAX_LENGTH])
            cursor = self.textEdit.textCursor()
            cursor.setPosition(position)
            self.textEdit.setTextCursor(cursor)
            self.textEdit.blockSignals(False)
        self._updateLimitLabel(trimmed)
        self.saveTimer.start()

    def _updateLimitLabel(self, trimmed=False) -> None:
        length = len(self.textEdit.toPlainText())
        suffix = " · 已截去超出内容" if trimmed else ""
        self.limitLabel.setText(
            f"{length} / {CUSTOM_STYLE_MAX_LENGTH}{suffix}"
        )
        self.limitLabel.setStyleSheet(
            "color: #d13438;" if trimmed else "color: rgba(128, 128, 128, 0.9);"
        )


class SettingPage(ScrollArea):
    aiQuotaReceived = Signal(int, int, int, object, str)
    appStoreCacheCleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._aiQuotaLoading = False
        self._searchText = ""
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(11, 0, 11, 36)
        self.titleWidget = QWidget(self.container)
        titleLayout = QVBoxLayout(self.titleWidget)
        titleLayout.setContentsMargins(19, 20, 19, 10)
        titleLayout.addWidget(TitleLabel("设置", self.titleWidget))
        self.vBoxLayout.addWidget(self.titleWidget)
        self.vBoxLayout.addStretch(1)

        self.personalGroup = CollapsibleSettingCardGroup(
            "个性化",
            "personalization",
            self.container,
            icon=FluentIcon.BRUSH,
            content="应用主题、颜色和托盘显示",
        )
        self.bannerGroup = CollapsibleSettingCardGroup(
            "横幅设置",
            "banner",
            self.container,
            icon=FluentIcon.PHOTO,
            content="主页横幅的显示与自定义",
        )
        self.broadcastGroup = CollapsibleSettingCardGroup(
            "全屏投送设置",
            "broadcast",
            self.container,
            icon=FluentIcon.FULL_SCREEN,
            content="投送窗口、操作按钮和关闭行为",
        )
        self.aiMarkdownGroup = CollapsibleSettingCardGroup(
            "AI帮改Markdown设置",
            "aiMarkdown",
            self.container,
            icon=FluentIcon.EDIT,
            content="AI 帮改功能和 Markdown 风格",
        )
        self.countdownGroup = CollapsibleSettingCardGroup(
            "考试倒计时设置",
            "countdown",
            self.container,
            icon=FluentIcon.CALENDAR,
            content="倒计时窗口、提醒和重置行为",
        )
        self.fullscreenClockGroup = CollapsibleSettingCardGroup(
            "全屏时钟设置",
            "fullscreenClock",
            self.container,
            icon=FluentIcon.STOP_WATCH,
            content="时钟窗口、操作按钮和关闭行为",
        )
        self.softwareGroup = CollapsibleSettingCardGroup(
            "应用",
            "software",
            self.container,
            icon=FluentIcon.SETTING,
            content="启动、更新和应用行为",
        )
        self.aboutGroup = CollapsibleSettingCardGroup(
            "关于",
            "about",
            self.container,
            icon=FluentIcon.INFO,
            content="版本、支持和项目相关信息",
        )

        self._initWidget()
        self._initCards()
        self._initLayout()
        self._bind()

    def addSettingGroup(self, group: CollapsibleSettingCardGroup) -> None:
        self.vBoxLayout.insertWidget(self.vBoxLayout.count() - 1, group)

    def _initWidget(self) -> None:
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("SettingPage")
        self.enableTransparentBackground()
        self.setProperty("isStackedTransparent", False)

    def _initCards(self) -> None:
        self.applicationIconCard = PushSettingCard(
            "选择图片",
            FluentIcon.FOLDER,
            "自定义软件图标",
            "选择窗口、启动页和系统托盘使用的本地图标",
        )
        self.windowTitleCard = LineEditSettingCard(
            FluentIcon.APPLICATION,
            "自定义窗口标题",
            "设置主窗口标题，留空时使用默认标题",
            configItem=cfg.windowTitle,
            placeholder=APP_NAME,
        )
        self.themeColorCard = ThemeColorSettingCard()
        self.personalGroup.addSettingCards(
            [
                ComboBoxSettingCard(
                    cfg.customThemeMode,
                    FluentIcon.BRUSH,
                    "应用主题",
                    "更改应用程序的外观",
                    texts=["浅色", "深色", "跟随系统设置"],
                ),
                ComboBoxSettingCard(
                    cfg.applicationIconSource,
                    FluentIcon.APPLICATION,
                    "软件图标",
                    "选择默认图标或自定义软件图标",
                    texts=["默认", "自定义"],
                ),
                self.applicationIconCard,
                self.windowTitleCard,
                LineEditSettingCard(
                    FluentIcon.INFO,
                    "自定义托盘文本",
                    "设置鼠标悬停在系统托盘图标上时显示的文字，留空时使用默认文本",
                    configItem=cfg.trayTooltip,
                    placeholder=APP_NAME,
                ),
                SwitchSettingCard(
                    FluentIcon.HEART,
                    "显示特别鸣谢入口",
                    "在侧边栏底部显示特别鸣谢页面入口",
                    cfg.showCreditsPage,
                ),
                self.themeColorCard,
            ]
        )

        self.chooseImageCard = PushSettingCard(
            "选择图片",
            FluentIcon.FOLDER,
            "自定义主页图片",
            "选择本地图片（需将主页图片来源设为“自定义”）",
        )
        self.broadcastBackgroundImageCard = PushSettingCard(
            "选择图片",
            FluentIcon.FOLDER,
            "自定义投送背景",
            "选择全屏投送使用的本地背景图片",
        )
        self.countdownBackgroundImageCard = PushSettingCard(
            "选择图片",
            FluentIcon.FOLDER,
            "自定义倒计时背景",
            "选择考试倒计时使用的本地背景图片",
        )
        self.fullscreenClockBackgroundImageCard = PushSettingCard(
            "选择图片",
            FluentIcon.FOLDER,
            "自定义时钟背景",
            "选择全屏时钟使用的本地背景图片",
        )
        self.bannerGroup.addSettingCards(
            [
                SwitchSettingCard(
                    FluentIcon.PHOTO,
                    "显示主页横幅",
                    "在主页顶部显示海报横幅",
                    cfg.showBanner,
                ),
                ComboBoxSettingCard(
                    cfg.bannerImageSource,
                    FluentIcon.IMAGE_EXPORT,
                    "主页图片来源",
                    "选择使用预设图片还是自定义图片",
                    texts=[*BANNER_IMAGE_PRESETS, "自定义"],
                ),
                self.chooseImageCard,
                RangeSettingCard(
                    cfg.bannerBrightness,
                    FluentIcon.BRIGHTNESS,
                    "主页横幅亮度",
                    "调节横幅背景图片的亮度",
                ),
                ComboBoxSettingCard(
                    cfg.bannerScaleMode,
                    FluentIcon.ZOOM_IN,
                    "横幅缩放模式",
                    "调节背景图片的对齐和铺满方式",
                    texts=["拉伸", "缩放(上)", "缩放(中)", "缩放(下)"],
                ),
            ]
        )

        self.broadcastBackgroundColorCard = LocalizedColorSettingCard(
            cfg.broadcastBackgroundColor,
            FluentIcon.PALETTE,
            "背景颜色",
            "纯色背景使用的颜色",
        )
        self.broadcastBackgroundScaleCard = ComboBoxSettingCard(
            cfg.broadcastBackgroundScaleMode,
            FluentIcon.ZOOM_IN,
            "图片缩放模式",
            "设置背景图片的缩放和对齐方式",
            texts=WINDOW_BACKGROUND_SCALE_MODES,
        )
        self.broadcastGroup.addSettingCards(
            [
                ComboBoxSettingCard(
                    cfg.broadcastBackgroundMode,
                    FluentIcon.PHOTO,
                    "背景类型",
                    "选择主题色、纯色或图片背景",
                    texts=WINDOW_BACKGROUND_MODES,
                ),
                self.broadcastBackgroundColorCard,
                self.broadcastBackgroundImageCard,
                self.broadcastBackgroundScaleCard,
                SwitchSettingCard(
                    FluentIcon.APPLICATION,
                    "显示任务栏",
                    "全屏投送时显示任务栏，方便切换应用并避免 Windows 进入免打扰模式",
                    cfg.showTaskbarInBroadcast,
                ),
                SwitchSettingCard(
                    FluentIcon.PIN,
                    "全屏时置顶",
                    "全屏投送窗口始终显示在最顶层",
                    cfg.topmostInFullscreen,
                ),
                SwitchSettingCard(
                    FluentIcon.PIN,
                    "窗口化时置顶",
                    "投送界面窗口化时始终显示在最顶层",
                    cfg.topmostInWindowed,
                ),
                ComboBoxSettingCard(
                    cfg.broadcastActionButtonPosition,
                    FluentIcon.LAYOUT,
                    "操作按钮位置",
                    "设置全屏投送下方操作按钮的放置位置",
                    texts=["左下角", "右下角"],
                ),
                SwitchSettingCard(
                    FluentIcon.HOME,
                    "关闭后显示主页面",
                    "关闭全屏投送后显示软件主页面",
                    cfg.showMainWindowAfterBroadcast,
                ),
                SwitchSettingCard(
                    FluentIcon.QUESTION,
                    "退出前询问",
                    "关闭全屏投送前询问是否退出",
                    cfg.confirmBeforeCloseBroadcast,
                ),
                SwitchSettingCard(
                    FluentIcon.HISTORY,
                    "启动时恢复上次投送",
                    "程序退出时投送未关闭，下次启动时自动恢复标题、内容和模式",
                    cfg.restoreBroadcastAtStartup,
                ),
            ]
        )

        self.aiStyleCard = AIMarkdownStyleSettingCard()
        self.aiQuotaCard = SettingCard(
            FluentIcon.HISTORY,
            "额度",
            "每天 0 点刷新",
        )
        self.aiQuotaLabel = BodyLabel("正在查询", self.aiQuotaCard)
        self.aiQuotaCard.hBoxLayout.addWidget(
            self.aiQuotaLabel,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        self.aiQuotaCard.hBoxLayout.addSpacing(16)
        self.aiMachineCodeCard = SettingCard(
            FluentIcon.FINGERPRINT,
            "当前注册机器码",
            "首次启动联网后由服务器分配，不包含原始硬件信息",
        )
        self.aiMachineCodeLabel = BodyLabel(
            cfg.aiMarkdownMachineCode.value or "正在注册",
            self.aiMachineCodeCard,
        )
        self.aiMachineCodeCard.hBoxLayout.addWidget(
            self.aiMachineCodeLabel,
            0,
            Qt.AlignmentFlag.AlignRight,
        )
        self.aiMachineCodeCard.hBoxLayout.addSpacing(16)
        self.aiMarkdownGroup.addSettingCards(
            [self.aiStyleCard, self.aiQuotaCard, self.aiMachineCodeCard]
        )

        self.countdownBackgroundColorCard = LocalizedColorSettingCard(
            cfg.countdownBackgroundColor,
            FluentIcon.PALETTE,
            "背景颜色",
            "纯色背景使用的颜色",
        )
        self.countdownBackgroundScaleCard = ComboBoxSettingCard(
            cfg.countdownBackgroundScaleMode,
            FluentIcon.ZOOM_IN,
            "图片缩放模式",
            "设置背景图片的缩放和对齐方式",
            texts=WINDOW_BACKGROUND_SCALE_MODES,
        )
        self.countdownGroup.addSettingCards(
            [
                ComboBoxSettingCard(
                    cfg.countdownBackgroundMode,
                    FluentIcon.PHOTO,
                    "背景类型",
                    "选择主题色、纯色或图片背景",
                    texts=WINDOW_BACKGROUND_MODES,
                ),
                self.countdownBackgroundColorCard,
                self.countdownBackgroundImageCard,
                self.countdownBackgroundScaleCard,
                SwitchSettingCard(
                    FluentIcon.APPLICATION,
                    "显示任务栏",
                    "全屏倒计时时显示任务栏，方便切换应用并避免 Windows 进入免打扰模式",
                    cfg.showTaskbarInCountdown,
                ),
                SwitchSettingCard(
                    FluentIcon.PIN,
                    "全屏时置顶",
                    "全屏倒计时窗口始终显示在最顶层",
                    cfg.countdownTopmostInFullscreen,
                ),
                SwitchSettingCard(
                    FluentIcon.PIN,
                    "窗口化时置顶",
                    "倒计时界面窗口化时始终显示在最顶层",
                    cfg.countdownTopmostInWindowed,
                ),
                ComboBoxSettingCard(
                    cfg.countdownActionButtonPosition,
                    FluentIcon.LAYOUT,
                    "操作按钮位置",
                    "设置考试倒计时下方操作按钮的放置位置",
                    texts=["左下角", "右下角"],
                ),
                SwitchSettingCard(
                    FluentIcon.HOME,
                    "关闭后显示主页面",
                    "关闭考试倒计时后显示软件主页面",
                    cfg.showMainWindowAfterCountdown,
                ),
                SwitchSettingCard(
                    FluentIcon.QUESTION,
                    "退出前询问",
                    "关闭考试倒计时前询问是否退出",
                    cfg.confirmBeforeCloseCountdown,
                ),
                SwitchSettingCard(
                    FluentIcon.SYNC,
                    "重置时间前询问",
                    "重置考试倒计时时询问是否重新开始",
                    cfg.confirmBeforeResetCountdown,
                ),
            ]
        )

        self.fullscreenClockBackgroundColorCard = LocalizedColorSettingCard(
            cfg.fullscreenClockBackgroundColor,
            FluentIcon.PALETTE,
            "背景颜色",
            "纯色背景使用的颜色",
        )
        self.fullscreenClockBackgroundScaleCard = ComboBoxSettingCard(
            cfg.fullscreenClockBackgroundScaleMode,
            FluentIcon.ZOOM_IN,
            "图片缩放模式",
            "设置背景图片的缩放和对齐方式",
            texts=WINDOW_BACKGROUND_SCALE_MODES,
        )
        self.fullscreenClockGroup.addSettingCards(
            [
                ComboBoxSettingCard(
                    cfg.fullscreenClockBackgroundMode,
                    FluentIcon.PHOTO,
                    "背景类型",
                    "选择主题色、纯色或图片背景",
                    texts=WINDOW_BACKGROUND_MODES,
                ),
                self.fullscreenClockBackgroundColorCard,
                self.fullscreenClockBackgroundImageCard,
                self.fullscreenClockBackgroundScaleCard,
                SwitchSettingCard(
                    FluentIcon.APPLICATION,
                    "显示任务栏",
                    "全屏时钟显示时保留任务栏，方便切换应用并避免 Windows 进入免打扰模式",
                    cfg.showTaskbarInFullscreenClock,
                ),
                SwitchSettingCard(
                    FluentIcon.PIN,
                    "全屏时置顶",
                    "全屏时钟窗口始终显示在最顶层",
                    cfg.fullscreenClockTopmostInFullscreen,
                ),
                SwitchSettingCard(
                    FluentIcon.PIN,
                    "窗口化时置顶",
                    "时钟界面窗口化时始终显示在最顶层",
                    cfg.fullscreenClockTopmostInWindowed,
                ),
                ComboBoxSettingCard(
                    cfg.fullscreenClockActionButtonPosition,
                    FluentIcon.LAYOUT,
                    "操作按钮位置",
                    "设置全屏时钟下方操作按钮的放置位置",
                    texts=["左下角", "右下角"],
                ),
                SwitchSettingCard(
                    FluentIcon.HOME,
                    "关闭后显示主页面",
                    "关闭全屏时钟后显示软件主页面",
                    cfg.showMainWindowAfterFullscreenClock,
                ),
                SwitchSettingCard(
                    FluentIcon.QUESTION,
                    "退出前询问",
                    "关闭全屏时钟前询问是否退出",
                    cfg.confirmBeforeCloseFullscreenClock,
                ),
            ]
        )

        self.autoRunCard = SwitchSettingCard(
            FluentIcon.VPN,
            "开机启动",
            "在系统启动时静默运行电教猫 Pro",
            cfg.autoRun,
        )
        self.clearAppStoreCacheCard = CacheSettingCard()
        from app.config.paths import APP_DATA_DIR, isPortable

        portable = isPortable()
        currentMode = "便携版" if portable else "安装版"
        self.storageModeCard = PushSettingCard(
            "切换到安装版" if portable else "切换到便携版",
            FluentIcon.SYNC,
            "配置存储模式",
            "安装版将配置和应用数据保存在用户目录；便携版保存在程序旁，"
            f"适用于系统盘有还原的情况。当前：{currentMode}（{APP_DATA_DIR}）",
        )
        self._refreshAppStoreCacheSize()
        self.softwareGroup.addSettingCards(
            [
                SwitchSettingCard(
                    FluentIcon.UPDATE,
                    "在应用程序启动时检查更新",
                    "新版本将更稳定，并具有更多功能",
                    cfg.checkUpdateAtStartUp,
                ),
                self.autoRunCard,
                self.storageModeCard,
                self.clearAppStoreCacheCard,
            ]
        )

        self.aboutCard = PrimaryPushSettingCard(
            "检查更新",
            FluentIcon.INFO,
            "关于",
            f"© Copyright {YEAR}, {AUTHOR}. Version {VERSION}。Beta 版仅接收 Beta 通道的更新",
        )
        self.errorLogCard = PushSettingCard(
            "查看错误日志",
            FluentIcon.FOLDER,
            "错误日志",
            "打开应用保存错误日志的文件夹。",
        )
        self.aboutGroup.addSettingCards(
            [
                HyperlinkCard(
                    AUTHOR_URL,
                    "打开作者的个人空间",
                    FluentIcon.PROJECTOR,
                    "了解作者",
                    f"发现更多 {AUTHOR} 的作品",
                ),
                self.errorLogCard,
                self.aboutCard,
            ]
        )

    def _initLayout(self) -> None:
        self.addSettingGroup(self.personalGroup)
        self.addSettingGroup(self.bannerGroup)
        self.addSettingGroup(self.broadcastGroup)
        self.addSettingGroup(self.aiMarkdownGroup)
        self.addSettingGroup(self.countdownGroup)
        self.addSettingGroup(self.fullscreenClockGroup)
        self.addSettingGroup(self.softwareGroup)
        self.addSettingGroup(self.aboutGroup)

    def _bind(self) -> None:
        self.applicationIconCard.clicked.connect(self._onChooseApplicationIconClicked)
        self.chooseImageCard.clicked.connect(self._onChooseImageClicked)
        self.broadcastBackgroundImageCard.clicked.connect(
            lambda: self._onChooseBackgroundImageClicked(
                cfg.broadcastBackgroundImagePath,
                cfg.broadcastBackgroundMode,
            )
        )
        self.countdownBackgroundImageCard.clicked.connect(
            lambda: self._onChooseBackgroundImageClicked(
                cfg.countdownBackgroundImagePath,
                cfg.countdownBackgroundMode,
            )
        )
        self.fullscreenClockBackgroundImageCard.clicked.connect(
            lambda: self._onChooseBackgroundImageClicked(
                cfg.fullscreenClockBackgroundImagePath,
                cfg.fullscreenClockBackgroundMode,
            )
        )
        self.autoRunCard.checkedChanged.connect(self._onAutoRunChanged)
        self.aboutCard.clicked.connect(self._onAboutCardClicked)
        self.clearAppStoreCacheCard.clicked.connect(self._onClearAppStoreCache)
        self.storageModeCard.clicked.connect(self._onStorageModeClicked)
        self.errorLogCard.clicked.connect(self._onOpenErrorLogClicked)
        self.aiQuotaReceived.connect(self._onAIQuotaReceived)
        cfg.applicationIconSource.valueChanged.connect(
            self._refreshConditionalCards
        )
        cfg.bannerImageSource.valueChanged.connect(
            self._onBannerImageSourceChanged
        )
        cfg.bannerImageSource.valueChanged.connect(
            self._refreshConditionalCards
        )
        cfg.broadcastBackgroundMode.valueChanged.connect(
            self._refreshConditionalCards
        )
        cfg.countdownBackgroundMode.valueChanged.connect(
            self._refreshConditionalCards
        )
        cfg.fullscreenClockBackgroundMode.valueChanged.connect(
            self._refreshConditionalCards
        )
        cfg.aiMarkdownMachineCode.valueChanged.connect(
            self._onMachineCodeChanged
        )
        self._refreshConditionalCards()

    def _onBannerImageSourceChanged(self, source: str) -> None:
        scaleMode = BANNER_PRESET_SCALE_MODES.get(source)
        if scaleMode is not None:
            cfg.set(cfg.bannerScaleMode, scaleMode)

    def _conditionalCardVisibility(self) -> dict[QWidget, bool]:
        return {
            self.applicationIconCard: cfg.applicationIconSource.value == "自定义",
            self.chooseImageCard: cfg.bannerImageSource.value == "自定义",
            self.broadcastBackgroundColorCard: cfg.broadcastBackgroundMode.value
            == "纯色",
            self.broadcastBackgroundImageCard: cfg.broadcastBackgroundMode.value
            == "图片",
            self.broadcastBackgroundScaleCard: cfg.broadcastBackgroundMode.value
            == "图片",
            self.countdownBackgroundColorCard: cfg.countdownBackgroundMode.value
            == "纯色",
            self.countdownBackgroundImageCard: cfg.countdownBackgroundMode.value
            == "图片",
            self.countdownBackgroundScaleCard: cfg.countdownBackgroundMode.value
            == "图片",
            self.fullscreenClockBackgroundColorCard: cfg.fullscreenClockBackgroundMode.value
            == "纯色",
            self.fullscreenClockBackgroundImageCard: cfg.fullscreenClockBackgroundMode.value
            == "图片",
            self.fullscreenClockBackgroundScaleCard: cfg.fullscreenClockBackgroundMode.value
            == "图片",
        }

    def _refreshConditionalCards(self, _value=None) -> None:
        self.setSearchText(self._searchText)

    def _onChooseApplicationIconClicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择软件图标",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.svg *.ico)",
        )
        if not path:
            return
        cfg.set(cfg.applicationIconPath, path)
        cfg.set(cfg.applicationIconSource, "自定义")

    def _onChooseBackgroundImageClicked(self, pathItem, modeItem) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择背景图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not path:
            return
        cfg.set(pathItem, path)
        cfg.set(modeItem, "图片")

    def _onChooseImageClicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择自定义图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp)",
        )
        if not path:
            return
        cfg.set(cfg.bannerImagePath, path)
        cfg.set(cfg.bannerImageSource, "自定义")

    def _onAboutCardClicked(self) -> None:
        self.window().checkForUpdates(manual=True)

    def _onOpenErrorLogClicked(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))

    def _onClearAppStoreCache(self) -> None:
        try:
            clearAppStoreCache()
        except (ApplicationStoreError, OSError) as error:
            InfoBar.error(
                "清理失败",
                str(error),
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self.window(),
            )
            return
        self.clearAppStoreCacheCard.setCacheSize(0)
        self.appStoreCacheCleared.emit()
        InfoBar.success(
            "缓存已清理",
            "应用市场缓存已删除。",
            duration=3000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self.window(),
        )

    def _onAutoRunChanged(self, enabled: bool) -> None:
        from app.platform.run_at_login import setRunAtLogin

        try:
            setRunAtLogin(enabled)
        except OSError as error:
            logger.exception("修改开机启动设置失败")
            signalBus.catchException.emit(str(error))

    def _onStorageModeClicked(self) -> None:
        from app.config.paths import (
            PORTABLE_DATA_DIR,
            USER_DATA_DIR,
            isPortable,
            migrateAppData,
        )

        portable = isPortable()
        target = USER_DATA_DIR if portable else PORTABLE_DATA_DIR
        mode = "安装版" if portable else "便携版"
        dialog = MessageBox(
            "切换配置存储模式",
            f"确定切换到{mode}吗？\n\n数据会复制到新位置，程序随后退出；重新打开后生效。",
            self.window(),
        )
        try:
            accepted = dialog.exec()
        finally:
            dialog.deleteLater()
        if not accepted:
            return
        application = QApplication.instance()
        application.aboutToQuit.connect(lambda: migrateAppData(target))
        application.quit()

    def setSearchText(self, text: str) -> None:
        self._searchText = text.strip().lower()
        conditionalVisibility = self._conditionalCardVisibility()
        for group in self._settingGroups():
            groupHasMatch = False
            for card in group.settingCards():
                target = card.card if isinstance(card, CollapsibleSettingCard) else card
                labels = (target.titleLabel.text(), target.contentLabel.text())
                matched = not self._searchText or any(
                    self._searchText in label.lower() for label in labels
                )
                visible = conditionalVisibility.get(card, True) and matched
                group.setSettingCardVisible(card, visible)
                groupHasMatch |= visible
            group.setVisible(groupHasMatch)
            group.setSearchExpanded(bool(self._searchText))

    def showEvent(self, event) -> None:
        self._refreshAppStoreCacheSize()
        self._refreshAIQuota()
        super().showEvent(event)

    def _refreshAppStoreCacheSize(self) -> None:
        try:
            size = appStoreImageCache.size()
        except OSError:
            size = 0
        self.clearAppStoreCacheCard.setCacheSize(size)

    def hideEvent(self, event) -> None:
        self.aiStyleCard.flushPendingSave()
        super().hideEvent(event)

    def _refreshAIQuota(self) -> None:
        if self._aiQuotaLoading:
            return
        self._aiQuotaLoading = True
        self.aiQuotaLabel.setText("正在查询")
        self.aiQuotaCard.contentLabel.setText("每天 0 点刷新")
        threading.Thread(target=self._fetchAIQuota, daemon=True).start()

    def _fetchAIQuota(self) -> None:
        quota = fetchQuota()
        try:
            self.aiQuotaReceived.emit(
                *quota if quota else (-1, -1, 1, None, "")
            )
        except RuntimeError:
            # The settings page can be destroyed while the network request is
            # still running during application shutdown.
            pass

    def _onAIQuotaReceived(
        self,
        remaining: int,
        limit: int,
        _cost: int,
        peakEnabled,
        machineCode: str,
    ) -> None:
        self._aiQuotaLoading = False
        self.aiQuotaLabel.setText(
            "暂时无法获取" if remaining < 0 else f"{remaining} / {limit}"
        )
        self.aiQuotaCard.contentLabel.setText(
            f"每天 0 点刷新；{PEAK_HOURS_TEXT} 每次扣 2 次，其余时段扣 1 次"
            if peakEnabled
            else "每天 0 点刷新"
        )
        if machineCode:
            cfg.set(cfg.aiMarkdownMachineCode, machineCode)

    def _onMachineCodeChanged(self, machineCode: str) -> None:
        self.aiMachineCodeLabel.setText(machineCode or "正在注册")

    def _settingGroups(self) -> list[CollapsibleSettingCardGroup]:
        return [
            self.vBoxLayout.itemAt(index).widget()
            for index in range(self.vBoxLayout.count())
            if isinstance(
                self.vBoxLayout.itemAt(index).widget(),
                CollapsibleSettingCardGroup,
            )
        ]
