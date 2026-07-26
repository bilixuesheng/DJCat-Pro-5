from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ColorDialog,
    ComboBoxSettingCard,
    FluentIcon,
    HyperlinkCard,
    LineEdit,
    PrimaryPushSettingCard,
    PushSettingCard,
    RadioButton,
    RangeSettingCard,
    SettingCard,
    SwitchSettingCard,
    setThemeColor,
)

from app.config.cfg import THEME_COLOR_PRESETS, cfg
from app.config.constants import AUTHOR, AUTHOR_URL, VERSION, YEAR
from app.signal_bus import signalBus
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import (
    CollapsibleSettingCard,
    CollapsibleSettingCardGroup,
)


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
            dialog.exec()
            return
        cfg.set(cfg.themeColorPreset, preset)
        rgb = next(rgb for name, rgb in THEME_COLOR_PRESETS if name == preset)
        self._setThemeColor(QColor(*rgb))

    @staticmethod
    def _setThemeColor(color: QColor) -> None:
        cfg.set(cfg.customThemeColor, color)
        setThemeColor(color)


class SettingPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.addStretch(1)

        self.personalGroup = CollapsibleSettingCardGroup(
            "个性化", "personalization", self.container
        )
        self.bannerGroup = CollapsibleSettingCardGroup(
            "横幅设置", "banner", self.container
        )
        self.broadcastGroup = CollapsibleSettingCardGroup(
            "全屏投送设置", "broadcast", self.container
        )
        self.softwareGroup = CollapsibleSettingCardGroup(
            "应用", "software", self.container
        )
        self.aboutGroup = CollapsibleSettingCardGroup("关于", "about", self.container)

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
        self.personalGroup.addSettingCards(
            [
                ComboBoxSettingCard(
                    cfg.customThemeMode,
                    FluentIcon.BRUSH,
                    "应用主题",
                    "更改应用程序的外观",
                    texts=["浅色", "深色", "跟随系统设置"],
                ),
                LineEditSettingCard(
                    FluentIcon.INFO,
                    "自定义托盘文本",
                    "设置鼠标悬停在系统托盘图标上时显示的文字",
                    configItem=cfg.trayTooltip,
                    placeholder="请输入内容",
                ),
                ThemeColorSettingCard(),
                ComboBoxSettingCard(
                    cfg.actionButtonPosition,
                    FluentIcon.LAYOUT,
                    "操作按钮位置",
                    "设置全屏任务下方操作按钮的放置位置",
                    texts=["左下角", "右下角"],
                ),
            ]
        )

        self.chooseImageCard = PushSettingCard(
            "选择图片",
            FluentIcon.FOLDER,
            "自定义主页图片",
            "选择本地图片（需将主页图片来源设为“自定义”）",
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
                    texts=["预设: 学校门口", "自定义"],
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

        self.broadcastGroup.addSettingCards(
            [
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
            ]
        )

        self.autoRunCard = SwitchSettingCard(
            FluentIcon.VPN,
            "开机启动",
            "在系统启动时静默运行电教猫 Pro",
            cfg.autoRun,
        )
        self.softwareGroup.addSettingCards(
            [
                SwitchSettingCard(
                    FluentIcon.UPDATE,
                    "在应用程序启动时检查更新",
                    "新版本将更稳定，并具有更多功能",
                    cfg.checkUpdateAtStartUp,
                ),
                self.autoRunCard,
            ]
        )

        self.aboutCard = PrimaryPushSettingCard(
            "检查更新",
            FluentIcon.INFO,
            "关于",
            f"© Copyright {YEAR}, {AUTHOR}. Version {VERSION}。Beta 版仅接收 Beta 通道的更新",
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
                self.aboutCard,
            ]
        )

    def _initLayout(self) -> None:
        self.addSettingGroup(self.personalGroup)
        self.addSettingGroup(self.bannerGroup)
        self.addSettingGroup(self.broadcastGroup)
        self.addSettingGroup(self.softwareGroup)
        self.addSettingGroup(self.aboutGroup)

    def _bind(self) -> None:
        self.chooseImageCard.clicked.connect(self._onChooseImageClicked)
        self.autoRunCard.checkedChanged.connect(self._onAutoRunChanged)
        self.aboutCard.clicked.connect(self._onAboutCardClicked)

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

    def _onAutoRunChanged(self, enabled: bool) -> None:
        from app.platform.run_at_login import setRunAtLogin

        try:
            setRunAtLogin(enabled)
        except OSError as error:
            logger.exception("修改开机启动设置失败")
            signalBus.catchException.emit(str(error))

    def showEvent(self, event) -> None:
        self._restoreOrder()
        super().showEvent(event)

    def _restoreOrder(self) -> None:
        groups = [
            self.vBoxLayout.itemAt(index).widget()
            for index in range(self.vBoxLayout.count())
            if isinstance(
                self.vBoxLayout.itemAt(index).widget(),
                CollapsibleSettingCardGroup,
            )
        ]
        groupByKey = {group.objectName(): group for group in groups}
        keys = [key for key in cfg.settingGroupOrder.value if key in groupByKey]
        keys += [key for key in groupByKey if key not in keys]
        for index, key in enumerate(keys):
            self.vBoxLayout.insertWidget(index, groupByKey[key])
        for group in groups:
            group.updateArrows()
