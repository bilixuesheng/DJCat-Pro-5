"""「设置 › 时间」里的卡片：当前时间、同步状态、偏移秒数和不偏移的种类。

规则在 app/common/clock.py 和 app/common/time_sync.py；这里只显示和改 cfg。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CheckBox,
    DoubleSpinBox,
    FluentIcon,
    PushButton,
    SettingCard,
)

from app.common import clock
from app.common.time_sync import TimeSyncState, timeSyncState
from app.config.cfg import (
    DAILY_DRIFT_DECIMALS,
    TIME_OFFSET_DECIMALS,
    TIME_OFFSET_KINDS,
    TIME_OFFSET_LIMIT,
    cfg,
)
from app.signal_bus import signalBus

# 定时器偶尔早到一两毫秒，落在整秒之后一点才不会显示成上一秒。
TICK_MARGIN_MS = 2


def _seconds(value: float) -> str:
    return f"{abs(value):.3f}".rstrip("0").rstrip(".")


def _clockTime(moment: datetime) -> str:
    if moment.date() == clock.calibratedNow().date():
        return f"{moment:%H:%M:%S}"
    return f"{moment.month}月{moment.day}日 {moment:%H:%M}"


def describeTimeSync(state: TimeSyncState) -> str:
    if state.syncing:
        return "正在同步…"
    if state.error:
        if state.syncedAt is None:
            return f"同步失败：{state.error}，正在使用系统时间"
        return f"同步失败：{state.error}，继续使用 {_clockTime(state.syncedAt)} 校准的时间"
    if state.syncedAt is None:
        return "未同步，正在使用系统时间"
    synced = f"上次同步 {_clockTime(state.syncedAt)}"
    seconds = _seconds(state.deviation or 0)
    if seconds == "0":
        return f"{synced}，本机时钟是准的"
    slowOrFast = "慢" if state.deviation > 0 else "快"
    return f"{synced}，本机时钟{slowOrFast} {seconds} 秒"


class CurrentTimeCard(SettingCard):
    """系统、校准、铃声三种时间并排，每个整秒刷新；没开的那一层不显示。"""

    NAMES = {"system": "系统时间", "calibrated": "校准时间", "bell": "铃声时间"}

    def __init__(self, parent=None):
        super().__init__(FluentIcon.DATE_TIME, "当前时间", "每秒刷新，对铃时看这里", parent)
        self.blocks = {}
        self._values = {}
        self.timer = QTimer(self)
        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        for key, name in self.NAMES.items():
            block = QWidget(self)
            layout = QVBoxLayout(block)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(CaptionLabel(name, block), 0, Qt.AlignmentFlag.AlignRight)
            value = BodyLabel(block)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(value, 0, Qt.AlignmentFlag.AlignRight)
            self.blocks[key] = block
            self._values[key] = value
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._fitValues()
        self._refreshBlocks()

    def _initLayout(self) -> None:
        for block in self.blocks.values():
            self.hBoxLayout.addWidget(block)
            self.hBoxLayout.addSpacing(20)

    def _bind(self) -> None:
        self.timer.timeout.connect(self._tick)
        cfg.timeSyncEnabled.valueChanged.connect(self._refreshBlocks)
        cfg.timeOffsetEnabled.valueChanged.connect(self._refreshBlocks)
        signalBus.appFontChanged.connect(self._fitValues)

    def _fitValues(self) -> None:
        # 比例字体里各数字宽窄不一，按最宽的数字留位，走秒时旁边的时间不跟着挪。
        for value in self._values.values():
            metrics = value.fontMetrics()
            digit = max(metrics.horizontalAdvance(d) for d in "0123456789")
            value.setMinimumWidth(digit * 6 + metrics.horizontalAdvance("::") + 2)

    def _refreshBlocks(self, _value=None) -> None:
        self.blocks["calibrated"].setHidden(not cfg.timeSyncEnabled.value)
        self.blocks["bell"].setHidden(not cfg.timeOffsetEnabled.value)
        if self.isVisible():
            self._tick()

    def _tick(self) -> None:
        calibrated = clock.calibratedNow()
        times = {
            "system": datetime.now().astimezone(),
            "calibrated": calibrated,
            "bell": clock.bellTime(calibrated),
        }
        for key, moment in times.items():
            self._values[key].setText(f"{moment:%H:%M:%S}")
        wait = min(
            1_000_000 - moment.microsecond
            for key, moment in times.items()
            if not self.blocks[key].isHidden()
        )
        self.timer.start(-(-wait // 1000) + TICK_MARGIN_MS)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._tick()

    def hideEvent(self, event) -> None:
        self.timer.stop()
        super().hideEvent(event)


class TimeSyncStatusCard(SettingCard):
    def __init__(self, parent=None):
        super().__init__(FluentIcon.SYNC, "同步状态", "", parent)
        self.button = PushButton("立即同步", self)
        self.hBoxLayout.addWidget(self.button)
        self.hBoxLayout.addSpacing(16)
        self.button.clicked.connect(signalBus.timeSyncRequested)
        signalBus.timeSyncStateChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        state = timeSyncState()
        self.setContent(describeTimeSync(state))
        self.button.setEnabled(not state.syncing)


class SecondsSettingCard(SettingCard):
    """以秒为单位的数值：输完（回车、离开输入框、点上下箭头）才存。"""

    def __init__(self, icon, title: str, content: str, decimals: int, parent=None):
        super().__init__(icon, title, content, parent)
        self.decimals = decimals
        self.spinBox = DoubleSpinBox(self)
        self.spinBox.setRange(-TIME_OFFSET_LIMIT, TIME_OFFSET_LIMIT)
        self.spinBox.setDecimals(decimals)
        self.spinBox.setSingleStep(0.1)
        self.spinBox.setSuffix(" 秒")
        self.spinBox.setMinimumWidth(210)
        # 边打字边存的话，打到一半的数会让 Bell Time 来回跳，跳过去的任务会被补执行。
        self.spinBox.setKeyboardTracking(False)
        self.hBoxLayout.addWidget(self.spinBox)
        self.hBoxLayout.addSpacing(16)
        self.spinBox.valueChanged.connect(self._onValueChanged)

    def refresh(self, _value=None) -> None:
        with QSignalBlocker(self.spinBox):
            self.spinBox.setValue(self.value())

    def value(self) -> float:
        raise NotImplementedError

    def save(self, value: float) -> None:
        raise NotImplementedError

    def _onValueChanged(self, value: float) -> None:
        self.save(round(value, self.decimals))

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)


class TimeOffsetSettingCard(SecondsSettingCard):
    """显示今天实际生效的偏移（含每天自动偏移累计的部分）；改它就以今天为新起点。"""

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.HISTORY,
            "偏移",
            "铃声比标准时间晚几秒就填负几，早几秒就填几",
            TIME_OFFSET_DECIMALS,
            parent,
        )
        for item in (
            cfg.timeOffset,
            cfg.timeOffsetDate,
            cfg.timeOffsetEnabled,
            cfg.dailyDriftEnabled,
            cfg.dailyDrift,
        ):
            item.valueChanged.connect(self.refresh)
        self.refresh()

    def value(self) -> float:
        return clock.offsetValue(clock.calibratedNow().date())

    def save(self, value: float) -> None:
        cfg.set(cfg.timeOffset, value)


class DailyDriftSettingCard(SecondsSettingCard):
    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.CALENDAR,
            "每天偏移",
            "每过一天，偏移自动加上这个数，负数就往负的方向走",
            DAILY_DRIFT_DECIMALS,
            parent,
        )
        cfg.dailyDrift.valueChanged.connect(self.refresh)
        self.refresh()

    def value(self) -> float:
        return cfg.dailyDrift.value

    def save(self, value: float) -> None:
        cfg.set(cfg.dailyDrift, value)


class TimeOffsetExemptionCard(SettingCard):
    def __init__(self, parent=None):
        super().__init__(FluentIcon.REMOVE_FROM, "不偏移", "勾上的仍按校准时间执行", parent)
        self.checkBoxes = {
            kind: CheckBox(label, self) for kind, label in TIME_OFFSET_KINDS.items()
        }
        for checkBox in self.checkBoxes.values():
            self.hBoxLayout.addWidget(checkBox)
            self.hBoxLayout.addSpacing(12)
            checkBox.toggled.connect(self._save)
        self.hBoxLayout.addSpacing(4)
        cfg.timeOffsetExemptions.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, _value=None) -> None:
        exemptions = cfg.timeOffsetExemptions.value
        for kind, checkBox in self.checkBoxes.items():
            with QSignalBlocker(checkBox):
                checkBox.setChecked(kind in exemptions)

    def _save(self, _checked=None) -> None:
        cfg.set(
            cfg.timeOffsetExemptions,
            [kind for kind, checkBox in self.checkBoxes.items() if checkBox.isChecked()],
        )
