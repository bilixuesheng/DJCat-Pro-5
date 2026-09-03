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
BANNER_IMAGE_PRESETS = {
    "预设: 树人门": "home.png",
    "预设: 罗小黑": "luoxiaoheimiao.jpg",
    "预设: 罗小黑（2）": "luoxiaoheimiao2.jpg",
    "预设: 罗小黑（3）": "luoxiaoheimiao3.jpg",
}
DEFAULT_BANNER_IMAGE_SOURCE = "预设: 罗小黑"
BANNER_PRESET_SCALE_MODES = {
    "预设: 树人门": "缩放(中)",
    "预设: 罗小黑": "缩放(中)",
    "预设: 罗小黑（2）": "缩放(下)",
    "预设: 罗小黑（3）": "缩放(中)",
}
WINDOW_BACKGROUND_MODES = ("主题色", "纯色", "图片")
WINDOW_BACKGROUND_SCALE_MODES = ("拉伸", "缩放(上)", "缩放(中)", "缩放(下)")
DEFAULT_HOME_CARDS = (
    "全屏投送",
    "考试倒计时",
    "全屏时钟",
    "定时播报",
    "自动任务",
    "定时关机",
)
HOME_CARD_SCHEMA_VERSION = 3


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
    applicationIconSource = OptionsConfigItem(
        "Personalization",
        "ApplicationIconSource",
        "默认",
        OptionsValidator(["默认", "自定义"]),
    )
    applicationIconPath = ConfigItem("Personalization", "ApplicationIconPath", "")
    windowTitle = ConfigItem("Personalization", "WindowTitle", "")
    trayTooltip = ConfigItem("Personalization", "TrayTooltip", "")
    showCreditsPage = ConfigItem(
        "Personalization", "ShowCreditsPage", True, BoolValidator()
    )

    trayLeftClickAction = OptionsConfigItem(
        "Tray",
        "LeftClickAction",
        "ShowWindow",
        OptionsValidator(["ShowWindow", "ShowMenu"]),
    )
    showBroadcastTrayAction = ConfigItem(
        "Tray", "ShowBroadcastAction", True, BoolValidator()
    )
    showHomeCardTaskTrayAction = ConfigItem(
        "Tray", "ShowHomeCardTaskAction", True, BoolValidator()
    )
    showShutdownTrayAction = ConfigItem(
        "Tray", "ShowShutdownAction", True, BoolValidator()
    )
    trayHomeCardKeys = ConfigItem("Tray", "HomeCardKeys", [])
    trayHomeCardsInSubmenu = ConfigItem(
        "Tray", "HomeCardsInSubmenu", False, BoolValidator()
    )

    showBanner = ConfigItem("Banner", "ShowBanner", True, BoolValidator())
    bannerImageSource = OptionsConfigItem(
        "Banner",
        "BannerImageSource",
        DEFAULT_BANNER_IMAGE_SOURCE,
        OptionsValidator([*BANNER_IMAGE_PRESETS, "自定义"]),
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
    broadcastActionButtonPosition = OptionsConfigItem(
        "Broadcast",
        "ActionButtonPosition",
        "右下角",
        OptionsValidator(["左下角", "右下角"]),
    )
    showMainWindowAfterBroadcast = ConfigItem(
        "Broadcast", "ShowMainWindowAfterClose", True, BoolValidator()
    )
    confirmBeforeCloseBroadcast = ConfigItem(
        "Broadcast", "ConfirmBeforeClose", True, BoolValidator()
    )
    restoreBroadcastAtStartup = ConfigItem(
        "Broadcast", "RestoreAtStartup", False, BoolValidator()
    )
    broadcastMarkdownEnabled = ConfigItem(
        "Broadcast", "MarkdownEnabled", False, BoolValidator()
    )
    organizeMarkdownBeforeBroadcast = ConfigItem(
        "Broadcast", "OrganizeMarkdownBeforeBroadcast", False, BoolValidator()
    )
    lastBroadcast = ConfigItem("Broadcast", "LastBroadcast", {})
    broadcastBackgroundMode = OptionsConfigItem(
        "Broadcast",
        "BackgroundMode",
        "主题色",
        OptionsValidator(WINDOW_BACKGROUND_MODES),
    )
    broadcastBackgroundColor = ColorConfigItem(
        "Broadcast", "BackgroundColor", QColor(*THEME_COLOR_PRESETS[0][1])
    )
    broadcastBackgroundImagePath = ConfigItem("Broadcast", "BackgroundImagePath", "")
    broadcastBackgroundScaleMode = OptionsConfigItem(
        "Broadcast",
        "BackgroundScaleMode",
        "缩放(中)",
        OptionsValidator(WINDOW_BACKGROUND_SCALE_MODES),
    )

    aiMarkdownCustomStyleEnabled = ConfigItem(
        "AIMarkdown", "CustomStyleEnabled", False, BoolValidator()
    )
    aiMarkdownCustomStyle = ConfigItem("AIMarkdown", "CustomStyle", "")
    aiMarkdownMachineCode = ConfigItem("AIMarkdown", "MachineCode", "")

    showTaskbarInCountdown = ConfigItem(
        "Countdown", "ShowTaskbar", True, BoolValidator()
    )
    countdownTopmostInFullscreen = ConfigItem(
        "Countdown", "TopmostInFullscreen", False, BoolValidator()
    )
    countdownTopmostInWindowed = ConfigItem(
        "Countdown", "TopmostInWindowed", True, BoolValidator()
    )
    countdownActionButtonPosition = OptionsConfigItem(
        "Countdown",
        "ActionButtonPosition",
        "右下角",
        OptionsValidator(["左下角", "右下角"]),
    )
    showMainWindowAfterCountdown = ConfigItem(
        "Countdown", "ShowMainWindowAfterClose", True, BoolValidator()
    )
    confirmBeforeCloseCountdown = ConfigItem(
        "Countdown", "ConfirmBeforeClose", True, BoolValidator()
    )
    confirmBeforeResetCountdown = ConfigItem(
        "Countdown", "ConfirmBeforeReset", True, BoolValidator()
    )
    countdownBackgroundMode = OptionsConfigItem(
        "Countdown",
        "BackgroundMode",
        "主题色",
        OptionsValidator(WINDOW_BACKGROUND_MODES),
    )
    countdownBackgroundColor = ColorConfigItem(
        "Countdown", "BackgroundColor", QColor(*THEME_COLOR_PRESETS[0][1])
    )
    countdownBackgroundImagePath = ConfigItem("Countdown", "BackgroundImagePath", "")
    countdownBackgroundScaleMode = OptionsConfigItem(
        "Countdown",
        "BackgroundScaleMode",
        "缩放(中)",
        OptionsValidator(WINDOW_BACKGROUND_SCALE_MODES),
    )

    showTaskbarInFullscreenClock = ConfigItem(
        "FullscreenClock", "ShowTaskbar", True, BoolValidator()
    )
    fullscreenClockStartWindowed = ConfigItem(
        "FullscreenClock", "StartWindowed", False, BoolValidator()
    )
    fullscreenClockTopmostInFullscreen = ConfigItem(
        "FullscreenClock", "TopmostInFullscreen", False, BoolValidator()
    )
    fullscreenClockTopmostInWindowed = ConfigItem(
        "FullscreenClock", "TopmostInWindowed", True, BoolValidator()
    )
    fullscreenClockActionButtonPosition = OptionsConfigItem(
        "FullscreenClock",
        "ActionButtonPosition",
        "右下角",
        OptionsValidator(["左下角", "右下角"]),
    )
    showMainWindowAfterFullscreenClock = ConfigItem(
        "FullscreenClock", "ShowMainWindowAfterClose", True, BoolValidator()
    )
    confirmBeforeCloseFullscreenClock = ConfigItem(
        "FullscreenClock", "ConfirmBeforeClose", True, BoolValidator()
    )
    fullscreenClockBackgroundMode = OptionsConfigItem(
        "FullscreenClock",
        "BackgroundMode",
        "主题色",
        OptionsValidator(WINDOW_BACKGROUND_MODES),
    )
    fullscreenClockBackgroundColor = ColorConfigItem(
        "FullscreenClock", "BackgroundColor", QColor(*THEME_COLOR_PRESETS[0][1])
    )
    fullscreenClockBackgroundImagePath = ConfigItem(
        "FullscreenClock", "BackgroundImagePath", ""
    )
    fullscreenClockBackgroundScaleMode = OptionsConfigItem(
        "FullscreenClock",
        "BackgroundScaleMode",
        "缩放(中)",
        OptionsValidator(WINDOW_BACKGROUND_SCALE_MODES),
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
        "HomePage", "CardOrder", list(DEFAULT_HOME_CARDS)
    )

    visibleDefaultHomeCards = ConfigItem(
        "HomePage", "VisibleDefaultCards", list(DEFAULT_HOME_CARDS)
    )
    homeCardSchemaVersion = ConfigItem("HomePage", "SchemaVersion", 0)
    customHomeCards = ConfigItem("HomePage", "CustomCards", [])

    pinnedHomeCards = ConfigItem("HomePage", "PinnedApplicationCards", [])

    broadcastTasks = ConfigItem("Schedule", "Tasks", [])
    homeCardTasks = ConfigItem("Schedule", "HomeCardTasks", [])
    shutdownTasks = ConfigItem("Schedule", "ShutdownTasks", [])
    broadcastTasksEnabled = ConfigItem(
        "Schedule", "BroadcastTasksEnabled", True, BoolValidator()
    )
    homeCardTasksEnabled = ConfigItem(
        "Schedule", "HomeCardTasksEnabled", True, BoolValidator()
    )
    shutdownTasksEnabled = ConfigItem(
        "Schedule", "ShutdownTasksEnabled", True, BoolValidator()
    )

    expandedSettingGroups = ConfigItem("UI", "ExpandedSettingGroups", [])


cfg = Config()
cfg.file = CONFIG_PATH


def migrateConfig() -> None:
    try:
        version = int(cfg.homeCardSchemaVersion.value)
    except (TypeError, ValueError):
        version = 0
    if version >= HOME_CARD_SCHEMA_VERSION:
        return

    migrations = (
        (1, "全屏时钟", "考试倒计时"),
        (2, "定时任务", "定时播报"),
    )
    for targetVersion, cardName, previousCard in migrations:
        if version >= targetVersion:
            continue
        for item in (cfg.homeCardOrder, cfg.visibleDefaultHomeCards):
            cards = (
                list(item.value)
                if isinstance(item.value, list)
                else list(DEFAULT_HOME_CARDS)
            )
            if cardName in cards or (
                cardName == "定时任务" and "自动任务" in cards
            ):
                continue
            try:
                index = cards.index(previousCard) + 1
            except ValueError:
                index = len(cards)
            cards.insert(index, cardName)
            cfg.set(item, cards, save=False)
    if version < 3:
        for item in (
            cfg.homeCardOrder,
            cfg.visibleDefaultHomeCards,
            cfg.trayHomeCardKeys,
        ):
            if not isinstance(item.value, list):
                continue
            cards = [
                "自动任务" if card == "定时任务" else card
                for card in item.value
            ]
            if cards != item.value:
                cfg.set(item, cards, save=False)
    cfg.set(cfg.homeCardSchemaVersion, HOME_CARD_SCHEMA_VERSION)
