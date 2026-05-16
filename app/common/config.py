import sys
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from qfluentwidgets import (QConfig, ConfigItem, OptionsConfigItem, 
                            OptionsValidator, BoolValidator, ConfigValidator, 
                            ConfigSerializer, RangeConfigItem, RangeValidator, ColorConfigItem)

class GeometryValidator(ConfigValidator):
    def validate(self, value: QRect) -> bool: return True
    def correct(self, value) -> QRect: return value

class GeometrySerializer(ConfigSerializer):
    def serialize(self, value: QRect) -> str: return f"{value.x()},{value.y()},{value.width()},{value.height()}"
    def deserialize(self, value: str) -> QRect:
        try:
            x, y, w, h = map(int, value.split(","))
            return QRect(x, y, w, h)
        except:
            return QRect(0, 0, 0, 0)

class Config(QConfig):
    # 个性化
    customThemeMode = OptionsConfigItem("Personalization", "ThemeMode", "System", OptionsValidator(["Light", "Dark", "System"]))
    themeColorPreset = OptionsConfigItem("Personalization", "ThemeColorPreset", "树人绿", OptionsValidator(["树人绿", "系统蓝", "自定义"]))
    customThemeColor = ColorConfigItem("Personalization", "CustomThemeColor", QColor(49, 101, 49))
    trayTooltip = ConfigItem("Personalization", "TrayTooltip", "电教猫 Pro 5") 
    actionButtonPosition = OptionsConfigItem("Personalization", "ActionButtonPosition", "右下角", OptionsValidator(["左下角", "右下角"]))
    
    # 横幅设置
    showBanner = ConfigItem("Banner", "ShowBanner", True, BoolValidator())
    bannerImageSource = OptionsConfigItem("Banner", "BannerImageSource", "预设: 学校门口", OptionsValidator(["预设: 学校门口", "自定义"]))
    bannerImagePath = ConfigItem("Banner", "BannerImagePath", "") 
    bannerBrightness = RangeConfigItem("Banner", "BannerBrightness", 100, RangeValidator(0, 100))
    bannerScaleMode = OptionsConfigItem("Banner", "BannerScaleMode", "缩放(中)", OptionsValidator(["拉伸", "缩放(上)", "缩放(中)", "缩放(下)"]))

    # 全屏投送设置
    showTaskbarInBroadcast = ConfigItem("Broadcast", "ShowTaskbar", True, BoolValidator())
    topmostInFullscreen = ConfigItem("Broadcast", "TopmostInFullscreen", False, BoolValidator())
    topmostInWindowed = ConfigItem("Broadcast", "TopmostInWindowed", True, BoolValidator())

    # 应用与软件
    autoRun = ConfigItem("Software", "AutoRun", False, BoolValidator())
    checkUpdateAtStartUp = ConfigItem("Software", "CheckUpdateAtStartUp", True, BoolValidator())
    geometry = ConfigItem("Software", "Geometry", QRect(0, 0, 0, 0), GeometryValidator(), GeometrySerializer())

    # 主页卡片
    homeCardOrder = ConfigItem("HomePage", "CardOrder", ["全屏投送", "考试倒计时", "定时关机"])

APP_NAME = "电教猫 Pro 5 Beta"
YEAR = 2026
AUTHOR = "XUESHENG"
VERSION = "5.0.0-pre.9"
AUTHOR_URL = "https://space.bilibili.com/1956850051"
UPDATE_API = "https://api.djcatpro.top/beta"

cfg = Config()
