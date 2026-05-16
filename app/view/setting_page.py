import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QButtonGroup, QFileDialog, QScroller
from qfluentwidgets import (SettingCardGroup, ComboBoxSettingCard, SwitchSettingCard, 
                            PrimaryPushSettingCard, HyperlinkCard, RangeSettingCard, PushSettingCard,
                            ExpandSettingCard, BodyLabel, RadioButton, ColorDialog, setThemeColor, 
                            SettingCard, LineEdit)
from qfluentwidgets import FluentIcon as FIF
import winreg
from loguru import logger
from app.common.signal_bus import SignalBus

if sys.platform != "darwin":
    from qfluentwidgets import SmoothScrollArea as ScrollArea
else:
    from qfluentwidgets import ScrollArea

from app.common.config import cfg, AUTHOR_URL, AUTHOR, YEAR, VERSION

class LineEditSettingCard(SettingCard):
    """ 支持输入文字的设置项卡片 """
    def __init__(self, configItem, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.lineEdit = LineEdit(self)
        
        self.lineEdit.setFixedWidth(250)
        self.hBoxLayout.addWidget(self.lineEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        
        self.lineEdit.setText(configItem.value)
        self.lineEdit.setPlaceholderText("请输入内容")
        
        self.lineEdit.textChanged.connect(self._onTextChanged)
        # 修复光标乱跳：不要直接连到 setText，而是连到自定义方法
        configItem.valueChanged.connect(self._onConfigChanged)

    def _onTextChanged(self, text):
        cfg.set(self.configItem, text)

    def _onConfigChanged(self, value):
        # 只有在外部修改配置（如重置默认值）时，才重新setText，避免打字时光标跳到末尾
        if self.lineEdit.text() != value:
            self.lineEdit.setText(value)



class ThemeColorSettingCard(ExpandSettingCard):
    """ 自定义主题色选择卡片 (完美还原下拉展开样式) """
    def __init__(self, parent=None):
        super().__init__(FIF.PALETTE, "应用主题色", "设置软件的全局主题色", parent)
        
        # 将组件添加到 viewLayout 中即可实现在下拉区域显示
        self.radioWidget = QWidget(self.view)
        self.radioLayout = QVBoxLayout(self.radioWidget)
        self.radioLayout.setContentsMargins(48, 15, 0, 15)
        
        self.buttonGroup = QButtonGroup(self)
        self.greenButton = RadioButton("预设: 树人绿 (49, 101, 49)", self.radioWidget)
        self.blueButton = RadioButton("预设: 系统蓝 (76, 194, 255)", self.radioWidget)
        self.customButton = RadioButton("自定义颜色", self.radioWidget)
        
        self.buttonGroup.addButton(self.greenButton)
        self.buttonGroup.addButton(self.blueButton)
        self.buttonGroup.addButton(self.customButton)
        
        self.radioLayout.addWidget(self.greenButton)
        self.radioLayout.addWidget(self.blueButton)
        self.radioLayout.addWidget(self.customButton)
        
        self.viewLayout.addWidget(self.radioWidget)
        
        # 顶部显示的当前选中状态标签
        self.choiceLabel = BodyLabel(self)
        self.addWidget(self.choiceLabel)
        
        preset = cfg.themeColorPreset.value
        if preset == "树人绿": self.greenButton.setChecked(True)
        elif preset == "系统蓝": self.blueButton.setChecked(True)
        else: self.customButton.setChecked(True)
        
        self.choiceLabel.setText(self.buttonGroup.checkedButton().text())
        self.buttonGroup.buttonClicked.connect(self._onButtonClicked)

    def _onButtonClicked(self, button):
        self.choiceLabel.setText(button.text())
        self.choiceLabel.adjustSize()
        
        if button == self.greenButton:
            cfg.set(cfg.themeColorPreset, "树人绿")
            cfg.set(cfg.customThemeColor, QColor(49, 101, 49))
            setThemeColor(QColor(49, 101, 49))
        elif button == self.blueButton:
            cfg.set(cfg.themeColorPreset, "系统蓝")
            cfg.set(cfg.customThemeColor, QColor(76, 194, 255))
            setThemeColor(QColor(76, 194, 255))
        elif button == self.customButton:
            cfg.set(cfg.themeColorPreset, "自定义")
            w = ColorDialog(cfg.customThemeColor.value, "选择主题色", self.window())
            w.colorChanged.connect(lambda c: (cfg.set(cfg.customThemeColor, c), setThemeColor(c)))
            w.exec()

class SettingPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        
        self.personalGroup = SettingCardGroup("个性化", self.container)
        self.bannerGroup = SettingCardGroup("横幅设置", self.container)
        self.broadcastGroup = SettingCardGroup("全屏投送设置", self.container)
        self.softwareGroup = SettingCardGroup("应用", self.container)
        self.aboutGroup = SettingCardGroup("关于", self.container)

        self.initWidget()
        self.initCards()
        self.initLayout()

    def initWidget(self):
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName("SettingPage")
        self.enableTransparentBackground()

        QScroller.grabGesture(self.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture)

    def initCards(self):
        # 1. 应用主题
        self.themeCard = ComboBoxSettingCard(cfg.customThemeMode, FIF.BRUSH, "应用主题", "更改应用程序的外观", texts=["浅色", "深色", "跟随系统设置"], parent=self.personalGroup)
        
        # 2. 自定义托盘文本 (现在可以正常工作了)
        self.trayTooltipCard = LineEditSettingCard(
            cfg.trayTooltip, 
            FIF.INFO, 
            "自定义托盘文本", 
            "设置鼠标悬停在系统托盘图标上时显示的文字", 
            parent=self.personalGroup
        )
        
        self.themeColorCard = ThemeColorSettingCard(self.personalGroup)
        self.btnPosCard = ComboBoxSettingCard(cfg.actionButtonPosition, FIF.LAYOUT, "操作按钮位置", "当全屏投送等全屏任务时下方操作按钮的放置位置", texts=["左下角", "右下角"], parent=self.personalGroup)
        
        self.personalGroup.addSettingCard(self.themeCard)
        self.personalGroup.addSettingCard(self.trayTooltipCard) # 添加进去
        self.personalGroup.addSettingCard(self.themeColorCard)
        self.personalGroup.addSettingCard(self.btnPosCard)
        
        self.showBannerCard = SwitchSettingCard(FIF.PHOTO, "显示主页横幅", "在主页顶部显示海报横幅", configItem=cfg.showBanner, parent=self.bannerGroup)
        self.bannerImageSourceCard = ComboBoxSettingCard(cfg.bannerImageSource, FIF.IMAGE_EXPORT, "主页图片来源", "选择使用预设图片还是自定义图片", texts=["预设: 学校门口", "自定义"], parent=self.bannerGroup)
        self.chooseImageCard = PushSettingCard("选择图片", FIF.FOLDER, "自定义主页图片", "选择本地图片（需在上方选择“自定义”才能生效）", parent=self.bannerGroup)
        self.chooseImageCard.clicked.connect(self._onChooseImageClicked)
        self.bannerBrightnessCard = RangeSettingCard(cfg.bannerBrightness, FIF.BRIGHTNESS, "主页横幅亮度", "调节横幅背景图片的亮度", parent=self.bannerGroup)
        self.bannerScaleModeCard = ComboBoxSettingCard(cfg.bannerScaleMode, FIF.ZOOM_IN, "横幅缩放模式", "调节背景图片的对齐和铺满方式", texts=["拉伸", "缩放(上)", "缩放(中)", "缩放(下)"], parent=self.bannerGroup)
        
        self.bannerGroup.addSettingCard(self.showBannerCard)
        self.bannerGroup.addSettingCard(self.bannerImageSourceCard)
        self.bannerGroup.addSettingCard(self.chooseImageCard)
        self.bannerGroup.addSettingCard(self.bannerBrightnessCard)
        self.bannerGroup.addSettingCard(self.bannerScaleModeCard)

        self.showTaskbarCard = SwitchSettingCard(FIF.APPLICATION, "显示任务栏", "在全屏投送时显示任务栏，可快速切换应用且不让Windows通知进入免打扰模式", configItem=cfg.showTaskbarInBroadcast, parent=self.broadcastGroup)
        self.topmostFullCard = SwitchSettingCard(FIF.PIN, "全屏时置顶", "开启后，全屏投送窗口将强制在最顶层显示", configItem=cfg.topmostInFullscreen, parent=self.broadcastGroup)
        self.topmostWinCard = SwitchSettingCard(FIF.PIN, "窗口化时置顶", "开启后，投送界面在窗口化时将强制固定在最顶层", configItem=cfg.topmostInWindowed, parent=self.broadcastGroup)
        self.broadcastGroup.addSettingCard(self.showTaskbarCard)
        self.broadcastGroup.addSettingCard(self.topmostFullCard)
        self.broadcastGroup.addSettingCard(self.topmostWinCard)

        self.updateOnStartUpCard = SwitchSettingCard(FIF.UPDATE, "在应用程序启动时检查更新", "新版本将更稳定，并具有更多功能", configItem=cfg.checkUpdateAtStartUp, parent=self.softwareGroup)
        self.autoRunCard = SwitchSettingCard(FIF.VPN, "开机启动", "在系统启动时静默运行", configItem=cfg.autoRun, parent=self.softwareGroup)
        self.softwareGroup.addSettingCard(self.updateOnStartUpCard)
        self.softwareGroup.addSettingCard(self.autoRunCard)
        cfg.autoRun.valueChanged.connect(self._onAutoRunChanged)

        self.authorCard = HyperlinkCard(AUTHOR_URL, "打开作者的个人空间", FIF.PROJECTOR, "了解作者", f"发现更多 {AUTHOR} 的作品", self.aboutGroup)
        self.aboutCard = PrimaryPushSettingCard("检查更新", FIF.INFO, "关于", "© " + "Copyright" + f" {YEAR}, {AUTHOR}. " + f"Version {VERSION}" + "。Beta 版仅接收 Beta 通道的更新", self.aboutGroup)
        self.aboutCard.clicked.connect(self._onAboutCardClicked)
        self.aboutGroup.addSettingCard(self.authorCard)
        self.aboutGroup.addSettingCard(self.aboutCard)

    def initLayout(self):
        self.vBoxLayout.addWidget(self.personalGroup)
        self.vBoxLayout.addWidget(self.bannerGroup)
        self.vBoxLayout.addWidget(self.broadcastGroup)
        self.vBoxLayout.addWidget(self.softwareGroup)
        self.vBoxLayout.addWidget(self.aboutGroup)

    def _onChooseImageClicked(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "选择自定义图片", "", "图片文件 (*.png *.jpg *.jpeg *.bmp)")
        if path:
            cfg.set(cfg.bannerImagePath, path)
            cfg.set(cfg.bannerImageSource, "自定义") 

    def _onAboutCardClicked(self):
        self.window().checkForUpdates(manual=True)
    
    def _onAutoRunChanged(self, is_auto_run: bool):
        if sys.platform != "win32":
            return
            
        # 获取当前运行的 exe 路径
        exec_path = sys.executable 
        key_name = "DJCatPro5"
        
        try:
            # 打开 Windows 当前用户的自启注册表目录
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0, winreg.KEY_ALL_ACCESS
            )
            
            if is_auto_run:
                # 写入注册表，路径前后加上双引号防止空格报错
                winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, f'"{exec_path}"')
            else:
                # 删除注册表
                try:
                    winreg.DeleteValue(key, key_name)
                except FileNotFoundError:
                    pass
                    
            winreg.CloseKey(key)
        except Exception as e:
            # 1. 写入本地日志文件，包含完整的报错堆栈
            logger.exception("修改注册表设置开机启动失败")
            # 2. 发送信号给 MainWindow，弹出 InfoBar
            SignalBus.catchException.emit(str(e))

