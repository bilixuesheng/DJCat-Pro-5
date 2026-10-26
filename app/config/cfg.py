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
from app.platform.background_effect import BACKGROUND_EFFECTS, defaultBackgroundEffect

THEME_COLOR_PRESETS = (
    ("树人绿", (49, 101, 49)),
    ("系统蓝", (76, 194, 255)),
    ("罗小黑", (0, 0, 0)),
)
CUSTOM_THEME_COLOR = "自定义"
APP_FONT_MODES = ("统一", "中西文分开")
DEFAULT_FONT = "默认"
SYSTEM_FONT = "跟随系统"
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
TIME_SERVERS = (
    ("阿里云", "ntp.aliyun.com"),
    ("腾讯云", "ntp.tencent.com"),
    ("国家授时中心", "ntp.ntsc.ac.cn"),
    ("微软", "time.windows.com"),
)
CUSTOM_TIME_SERVER = "自定义"
TIME_SERVER_OPTIONS = [name for name, _ in TIME_SERVERS] + [CUSTOM_TIME_SERVER]
# 可以设为不偏移的 Scheduled Task 种类：调度循环里的种类名 → 设置页上的名字。
TIME_OFFSET_KINDS = {
    "broadcast": "定时播报",
    "home-card": "自动任务",
    "shutdown": "定时关机",
}
# 偏移不设范围；数值框总得有个边，这里取一个用不到的大数。
TIME_OFFSET_LIMIT = 999999.9
TIME_OFFSET_DECIMALS = 3
DAILY_DRIFT_DECIMALS = 1


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


class FontValidator(ConfigValidator):
    def validate(self, value) -> bool:
        return isinstance(value, str) and bool(value)

    def correct(self, value) -> str:
        return value if self.validate(value) else DEFAULT_FONT


class SecondsValidator(ConfigValidator):
    """Time Offset 和 Daily Drift 的秒数，保留 `decimals` 位小数。"""

    def __init__(self, decimals: int):
        self.decimals = decimals

    def validate(self, value) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and abs(value) <= TIME_OFFSET_LIMIT
            and round(value, self.decimals) == value
        )

    def correct(self, value) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return 0.0
        if seconds != seconds:
            return 0.0
        seconds = max(-TIME_OFFSET_LIMIT, min(TIME_OFFSET_LIMIT, seconds))
        return round(seconds, self.decimals)


class TimeOffsetKindsValidator(ConfigValidator):
    def validate(self, value) -> bool:
        return isinstance(value, list) and all(kind in TIME_OFFSET_KINDS for kind in value)

    def correct(self, value) -> list:
        if not isinstance(value, (list, tuple)):
            return []
        return [kind for kind in TIME_OFFSET_KINDS if kind in value]


class Config(QConfig):
    customThemeMode = OptionsConfigItem(
        "Personalization",
        "ThemeMode",
        "System",
        OptionsValidator(["Light", "Dark", "System"]),
    )
    backgroundEffect = OptionsConfigItem(
        "Personalization",
        "BackgroundEffect",
        defaultBackgroundEffect(),
        OptionsValidator(list(BACKGROUND_EFFECTS)),
    )
    themeColorPreset = OptionsConfigItem(
        "Personalization",
        "ThemeColorPreset",
        "树人绿",
        OptionsValidator(
            [name for name, _ in THEME_COLOR_PRESETS] + [CUSTOM_THEME_COLOR]
        ),
    )
    # 只存 Custom Theme Color，选预设时不动它；正在用的颜色见 currentThemeColor()。
    customThemeColor = ColorConfigItem(
        "Personalization",
        "CustomThemeColor",
        QColor(*THEME_COLOR_PRESETS[0][1]),
    )
    # None 表示旧版配置尚未迁移，见 migrateConfig()。
    hasCustomThemeColor = ConfigItem("Personalization", "HasCustomThemeColor", None)
    windowTransitionEnabled = ConfigItem(
        "Personalization", "WindowTransition", True, BoolValidator()
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
    appFontMode = OptionsConfigItem(
        "Personalization",
        "AppFontMode",
        APP_FONT_MODES[0],
        OptionsValidator(list(APP_FONT_MODES)),
    )
    # 三个字体各存各的，切换字体模式不改写任何一个。值是字体名，或 DEFAULT_FONT、SYSTEM_FONT。
    appFont = ConfigItem("Personalization", "AppFont", DEFAULT_FONT, FontValidator())
    latinFont = ConfigItem("Personalization", "LatinFont", DEFAULT_FONT, FontValidator())
    cjkFont = ConfigItem("Personalization", "CjkFont", DEFAULT_FONT, FontValidator())

    # 开发人员选项，只供开发人员调试，默认全关。分组名 Experimental 是改名前留下的，
    # 照旧沿用，停用页面懒加载已存的值才不会丢。
    disableTouchPressFeedback = ConfigItem(
        "Experimental", "DisableTouchPressFeedback", False, BoolValidator()
    )
    disableTunedTouchScroll = ConfigItem(
        "Experimental", "DisableTunedTouchScroll", False, BoolValidator()
    )
    disableSuperFrameRate = ConfigItem(
        "Experimental", "DisableSuperFrameRate", False, BoolValidator()
    )
    eagerPageLoading = ConfigItem(
        "Experimental", "EagerPageLoading", False, BoolValidator()
    )
    showFrameRate = ConfigItem(
        "Experimental", "ShowFrameRate", False, BoolValidator()
    )

    trayIconSource = OptionsConfigItem(
        "Tray",
        "IconSource",
        "跟随软件图标",
        OptionsValidator(["跟随软件图标", "自定义"]),
    )
    trayIconPath = ConfigItem("Tray", "IconPath", "")
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
    broadcastTitle = ConfigItem("Broadcast", "Title", "")
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

    # 空值表示默认的 Application Install Location，随 App Data Directory 走。
    appInstallLocation = ConfigItem("AppStore", "InstallLocation", "")
    # 进行中的 Application Relocation；中途退出或断电时，下次启动按它收尾。
    appRelocation = ConfigItem("AppStore", "Relocation", {})

    broadcastTasks = ConfigItem("Schedule", "Tasks", [])
    homeCardTasks = ConfigItem("Schedule", "HomeCardTasks", [])
    # 按任务 ID 记的运行状态：Interval Task 从何时起算、执行到哪个到点，以及 Current Wallpaper。
    # 与 HomeCardTasks 分开存，执行一次不必改写任务列表。
    homeCardTaskState = ConfigItem("Schedule", "HomeCardTaskState", {})
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
    timeSyncEnabled = ConfigItem("Time", "SyncEnabled", True, BoolValidator())
    timeServer = OptionsConfigItem(
        "Time",
        "Server",
        TIME_SERVERS[0][0],
        OptionsValidator(TIME_SERVER_OPTIONS),
    )
    customTimeServer = ConfigItem("Time", "CustomServer", "")
    timeOffsetEnabled = ConfigItem("Time", "OffsetEnabled", False, BoolValidator())
    # TimeOffsetDate 那一天的 Time Offset；开着 Daily Drift 时，之后每过一天再加一次 DailyDrift。
    timeOffset = ConfigItem(
        "Time", "Offset", 0.0, SecondsValidator(TIME_OFFSET_DECIMALS)
    )
    timeOffsetDate = ConfigItem("Time", "OffsetDate", "")
    dailyDriftEnabled = ConfigItem("Time", "DailyDriftEnabled", False, BoolValidator())
    dailyDrift = ConfigItem(
        "Time", "DailyDrift", 0.0, SecondsValidator(DAILY_DRIFT_DECIMALS)
    )
    timeOffsetExemptions = ConfigItem(
        "Time", "OffsetExemptions", [], TimeOffsetKindsValidator()
    )


cfg = Config()
cfg.file = CONFIG_PATH


def currentThemeColor() -> QColor:
    preset = cfg.themeColorPreset.value
    for name, rgb in THEME_COLOR_PRESETS:
        if name == preset:
            return QColor(*rgb)
    return QColor(cfg.customThemeColor.value)


def _migrateThemeColor() -> None:
    # 旧版选预设时会把预设色写进 CustomThemeColor，那时选着预设的用户没有可找回的自定义颜色。
    if not isinstance(cfg.hasCustomThemeColor.value, bool):
        cfg.set(
            cfg.hasCustomThemeColor,
            cfg.themeColorPreset.value == CUSTOM_THEME_COLOR,
        )


def migrateConfig() -> None:
    _migrateThemeColor()
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
