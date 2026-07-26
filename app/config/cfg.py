from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from qfluentwidgets import (
    BoolValidator,
    ColorConfigItem,
    ConfigItem,
    ConfigSerializer,
    ConfigValidator,
    OptionsConfigItem,
    OptionsValidator,
    QConfig,
    RangeConfigItem,
    RangeValidator,
)

from app.config.paths import CONFIG_PATH

THEME_COLOR_PRESETS = (
    ("树人绿", (49, 101, 49)),
    ("系统蓝", (76, 194, 255)),
)


class GeometryValidator(ConfigValidator):
    def validate(self, value: QRect) -> bool:
        return isinstance(value, QRect)

    def correct(self, value) -> QRect:
        return value if isinstance(value, QRect) else QRect()


class GeometrySerializer(ConfigSerializer):
    def serialize(self, value: QRect) -> str:
        return f"{value.x()},{value.y()},{value.width()},{value.height()}"

    def deserialize(self, value: str) -> QRect:
        try:
            x, y, w, h = map(int, value.split(","))
            return QRect(x, y, w, h)
        except (TypeError, ValueError):
            return QRect()


class Config(QConfig):
    customThemeMode = OptionsConfigItem(
        "Personalization",
        "ThemeMode",
        "System",
        OptionsValidator(["Light", "Dark", "System"]),
    )
    themeColorPreset = OptionsConfigItem(
        "Personalization",
        "ThemeColorPreset",
        "树人绿",
        OptionsValidator([name for name, _ in THEME_COLOR_PRESETS] + ["自定义"]),
    )
    customThemeColor = ColorConfigItem(
        "Personalization",
        "CustomThemeColor",
        QColor(*THEME_COLOR_PRESETS[0][1]),
    )
    trayTooltip = ConfigItem("Personalization", "TrayTooltip", "电教猫 Pro 5")
    actionButtonPosition = OptionsConfigItem(
        "Personalization",
        "ActionButtonPosition",
        "右下角",
        OptionsValidator(["左下角", "右下角"]),
    )

    showBanner = ConfigItem("Banner", "ShowBanner", True, BoolValidator())
    bannerImageSource = OptionsConfigItem(
        "Banner",
        "BannerImageSource",
        "预设: 学校门口",
        OptionsValidator(["预设: 学校门口", "自定义"]),
    )
    bannerImagePath = ConfigItem("Banner", "BannerImagePath", "")
    bannerBrightness = RangeConfigItem(
        "Banner", "BannerBrightness", 100, RangeValidator(0, 100)
    )
    bannerScaleMode = OptionsConfigItem(
        "Banner",
        "BannerScaleMode",
        "缩放(中)",
        OptionsValidator(["拉伸", "缩放(上)", "缩放(中)", "缩放(下)"]),
    )

    showTaskbarInBroadcast = ConfigItem(
        "Broadcast", "ShowTaskbar", True, BoolValidator()
    )
    topmostInFullscreen = ConfigItem(
        "Broadcast", "TopmostInFullscreen", False, BoolValidator()
    )
    topmostInWindowed = ConfigItem(
        "Broadcast", "TopmostInWindowed", True, BoolValidator()
    )

    autoRun = ConfigItem("Software", "AutoRun", False, BoolValidator())
    checkUpdateAtStartUp = ConfigItem(
        "Software", "CheckUpdateAtStartUp", True, BoolValidator()
    )
    geometry = ConfigItem(
        "Software",
        "Geometry",
        QRect(0, 0, 0, 0),
        GeometryValidator(),
        GeometrySerializer(),
    )

    homeCardOrder = ConfigItem(
        "HomePage", "CardOrder", ["全屏投送", "考试倒计时", "定时播报", "定时关机"]
    )

    broadcastTasks = ConfigItem("Schedule", "Tasks", [])
    shutdownTasks = ConfigItem("Schedule", "ShutdownTasks", [])

    expandedSettingGroups = ConfigItem("UI", "ExpandedSettingGroups", [])
    settingGroupOrder = ConfigItem("UI", "SettingGroupOrder", [])


cfg = Config()
cfg.file = CONFIG_PATH
