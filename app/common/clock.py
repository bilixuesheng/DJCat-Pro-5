"""Calibrated Time 与 Bell Time：电教猫里"现在几点"的唯一来源。

Time Sync 成功后，Calibrated Time 从同步那一刻起跟着 `perf_counter` 走，而不是跟着系统时钟：
有人改了 Windows 时间，电教猫的时间不跳（Time Sync 再去重新同步）。Windows 上 Python 3.12 的
`perf_counter` 是 QueryPerformanceCounter，睡眠和休眠期间照样计数，不受改时间影响。

Time Offset 存的是 TimeOffsetDate 那一天的值，开着 Daily Drift 时按日历天数往后累加，读的时候现算，
不每天回写配置。规则一改（开关、每日量）就按改之前的规则把今天的值折算出来、以今天为新起点：
关掉开关时数值冻结，关着的日子不累计，改每日量不回头重算；用户改偏移也以今天为起点。理由见 docs/adr/0012-djcat-time.md。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from typing import NamedTuple

from app.config.cfg import TIME_OFFSET_DECIMALS, cfg


class Clock:
    """Calibrated Time：同步过就是"同步时的标准时间 + 此后经过的时间"，否则是系统时间。"""

    def __init__(self, systemTime=time.time, counter=time.perf_counter):
        self._systemTime = systemTime
        self._counter = counter
        self._anchor: tuple[float, float] | None = None

    def synchronize(self, epoch: float, counter: float) -> None:
        """记下计数器读数为 `counter` 的那一刻，标准时间是 `epoch`。"""
        self._anchor = (epoch, counter)

    def forget(self) -> None:
        self._anchor = None

    def synchronized(self) -> bool:
        return self._anchor is not None

    def epoch(self) -> float:
        anchor = self._anchor
        if anchor is None:
            return self._systemTime()
        epoch, counter = anchor
        return epoch + (self._counter() - counter)

    def deviation(self) -> float | None:
        """Calibrated Time 比系统时间快多少秒；没同步过是 None。"""
        if self._anchor is None:
            return None
        return self.epoch() - self._systemTime()

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.epoch()).astimezone()


calibratedClock = Clock()


def calibratedNow() -> datetime:
    return calibratedClock.now()


def millisecondsToNextSecond(*moments: datetime) -> int:
    """到这几个时间里最近的那个整秒还有多少毫秒，多留一点余量。"""
    wait = min(1_000_000 - moment.microsecond for moment in moments)
    # 定时器偶尔早到一两毫秒；落在整秒之后一点，才不会把这一秒当成上一秒。
    return -(-wait // 1000) + 2


class _OffsetRules(NamedTuple):
    enabled: bool
    driftEnabled: bool
    drift: float


def _anchorDate(day: date) -> date:
    try:
        return date.fromisoformat(cfg.timeOffsetDate.value)
    except (TypeError, ValueError):
        return day


def _currentRules() -> _OffsetRules:
    return _OffsetRules(
        bool(cfg.timeOffsetEnabled.value),
        bool(cfg.dailyDriftEnabled.value),
        cfg.dailyDrift.value,
    )


def _offsetUnder(rules: _OffsetRules, day: date) -> float:
    value = cfg.timeOffset.value
    if rules.enabled and rules.driftEnabled:
        days = (day - _anchorDate(day)).days
        if days > 0:
            value += rules.drift * days
    return round(value, TIME_OFFSET_DECIMALS)


def configuredTimeOffset(day: date) -> float:
    """这一天的 Time Offset 数值，开关关着时是冻结的那个值；设置页显示它。"""
    return _offsetUnder(_currentRules(), day)


def timeOffset(day: date) -> float:
    """这一天实际生效的 Time Offset，开关关着是 0。"""
    if not cfg.timeOffsetEnabled.value:
        return 0.0
    return configuredTimeOffset(day)


def setTimeOffset(seconds: float) -> None:
    """用户填的偏移是今天的值：连同今天这个起点一起存，填回原数也要从今天重新算。"""
    cfg.set(cfg.timeOffset, seconds)
    cfg.set(cfg.timeOffsetDate, calibratedNow().date().isoformat())


def bellTime(calibrated: datetime) -> datetime:
    return calibrated + timedelta(seconds=timeOffset(calibrated.date()))


def scheduledTaskNow(kind: str) -> datetime:
    return scheduledTaskTime(kind, calibratedNow())


def scheduledTaskTime(kind: str, calibrated: datetime) -> datetime:
    """这一种 Scheduled Task 按哪个时间匹配：Bell Time，设为不偏移的种类用 Calibrated Time。"""
    if kind in cfg.timeOffsetExemptions.value:
        return calibrated
    return bellTime(calibrated)


_boundRules: _OffsetRules | None = None


def bindTimeOffset() -> None:
    """开关或每日量改动时按改之前的规则折算到今天、以今天为新起点；重复调用无害。"""
    global _boundRules
    if _boundRules is not None:
        return
    _boundRules = _currentRules()
    for item in (cfg.timeOffsetEnabled, cfg.dailyDriftEnabled, cfg.dailyDrift):
        item.valueChanged.connect(_onRulesChanged)


def _onRulesChanged(_value=None) -> None:
    global _boundRules
    value = _offsetUnder(_boundRules, calibratedNow().date())
    _boundRules = _currentRules()
    setTimeOffset(value)
