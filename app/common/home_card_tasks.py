from __future__ import annotations

import ntpath
from datetime import datetime

from app.common.home_cards import newId, normalizeActions
from app.config.cfg import cfg

EXISTING_HOME_CARD_TASK = "existing"
CUSTOM_HOME_CARD_TASK = "custom"
WALLPAPER_HOME_CARD_TASK = "wallpaper"
HOME_CARD_TASK_KEY = "自动任务"
HOME_CARD_TASK_MODES = (
    EXISTING_HOME_CARD_TASK,
    CUSTOM_HOME_CARD_TASK,
    WALLPAPER_HOME_CARD_TASK,
)
SCHEDULED_HOME_CARD_TRIGGER = "time"
APPLICATION_HOME_CARD_TRIGGER = "application"
PROCESS_GUARD_TRIGGER = "guard"
INTERVAL_HOME_CARD_TRIGGER = "interval"
HOME_CARD_TASK_TRIGGERS = (
    SCHEDULED_HOME_CARD_TRIGGER,
    APPLICATION_HOME_CARD_TRIGGER,
    PROCESS_GUARD_TRIGGER,
    INTERVAL_HOME_CARD_TRIGGER,
)
INTERVAL_UNIT_SECONDS = {"minute": 60, "hour": 3600, "day": 86400}
DEFAULT_INTERVAL = {"value": 1, "unit": "day"}
# 起点缺失时的兜底：取一个固定的零点，规范化的结果才不随日子变。
DEFAULT_INTERVAL_START = "2000-01-01 00:00:00"
INTERVAL_START_FORMAT = "%Y-%m-%d %H:%M:%S"
FIXED_WALLPAPER = "fixed"
ROTATION_WALLPAPER = "rotation"
WALLPAPER_MODES = (FIXED_WALLPAPER, ROTATION_WALLPAPER)
APPLICATION_STARTUP_EVENT = "startup"
SILENT_STARTUP_EVENT = "silent-startup"
APPLICATION_QUIT_EVENT = "quit"
HOME_CARD_TASK_EVENTS = (
    APPLICATION_STARTUP_EVENT,
    SILENT_STARTUP_EVENT,
    APPLICATION_QUIT_EVENT,
)
OPEN_HOME_CARD_ACTION = "open"
CLOSE_HOME_CARD_ACTION = "close"
HOME_CARD_TASK_ACTIONS = (OPEN_HOME_CARD_ACTION, CLOSE_HOME_CARD_ACTION)


def _text(value, default="") -> str:
    return str(value).strip() if value is not None else default


def _time(value) -> str:
    try:
        return datetime.strptime(_text(value), "%H:%M:%S").strftime("%H:%M:%S")
    except ValueError:
        return "00:00:00"


def _enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
    return True


def _weeks(value) -> list[int]:
    weeks = []
    for day in value if isinstance(value, (list, tuple, set)) else []:
        if isinstance(day, bool):
            continue
        try:
            day = int(day)
        except (OverflowError, TypeError, ValueError):
            continue
        if 0 <= day <= 6 and day not in weeks:
            weeks.append(day)
    return weeks


def _interval(value) -> dict:
    value = value if isinstance(value, dict) else {}
    unit = _text(value.get("unit")).lower()
    if unit not in INTERVAL_UNIT_SECONDS:
        unit = DEFAULT_INTERVAL["unit"]
    count = value.get("value")
    if isinstance(count, bool):
        count = None
    try:
        count = max(1, int(count))
    except (OverflowError, TypeError, ValueError):
        count = DEFAULT_INTERVAL["value"]
    return {"value": count, "unit": unit}


def _start(value) -> str:
    try:
        return datetime.strptime(_text(value), INTERVAL_START_FORMAT).strftime(
            INTERVAL_START_FORMAT
        )
    except ValueError:
        return DEFAULT_INTERVAL_START


def wallpaperKey(path: str) -> str:
    """同一张图的比较键：Windows 路径不分大小写，正反斜杠也是同一个。"""
    return ntpath.normcase(ntpath.normpath(path)) if path else ""


def _wallpaper(value) -> dict:
    value = value if isinstance(value, dict) else {}
    mode = _text(value.get("mode")).lower()
    if mode not in WALLPAPER_MODES:
        mode = FIXED_WALLPAPER
    rotation = []
    keys = set()
    raw = value.get("rotation")
    for item in raw if isinstance(raw, list) else []:
        path = _text(item) if isinstance(item, str) else ""
        key = wallpaperKey(path)
        if not path or key in keys:
            continue
        keys.add(key)
        rotation.append(path)
    fixed = value.get("fixed")
    return {
        "mode": mode,
        "fixed": _text(fixed) if isinstance(fixed, str) else "",
        "rotation": rotation,
    }


def _program(value) -> dict:
    value = value if isinstance(value, dict) else {}
    return {
        "target": _text(value.get("target")),
        "arguments": _text(value.get("arguments")),
        "working_dir": _text(value.get("working_dir")),
    }


def normalizeHomeCardTasks(value) -> list[dict]:
    tasks = []
    taskIds = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        taskId = _text(raw.get("id")) or newId()
        if taskId in taskIds:
            taskId = newId()
        taskIds.add(taskId)
        mode = _text(raw.get("mode")).lower()
        if mode not in HOME_CARD_TASK_MODES:
            mode = EXISTING_HOME_CARD_TASK
        trigger = _text(raw.get("trigger")).lower()
        if trigger not in HOME_CARD_TASK_TRIGGERS:
            trigger = SCHEDULED_HOME_CARD_TRIGGER
        event = _text(raw.get("event")).lower()
        if event not in HOME_CARD_TASK_EVENTS:
            event = APPLICATION_STARTUP_EVENT
        operation = _text(raw.get("operation")).lower()
        if operation not in HOME_CARD_TASK_ACTIONS:
            operation = OPEN_HOME_CARD_ACTION
        tasks.append(
            {
                "id": taskId,
                "name": (_text(raw.get("name")) or "未命名任务")[:40],
                "time": _time(raw.get("time")),
                "weeks": _weeks(raw.get("weeks")),
                "trigger": trigger,
                "event": event,
                "mode": mode,
                "operation": operation,
                "targetKey": _text(raw.get("targetKey")),
                "targetTitle": _text(raw.get("targetTitle"))[:40],
                "actions": normalizeActions(raw.get("actions", [])),
                "program": _program(raw.get("program")),
                "interval": _interval(raw.get("interval")),
                "start": _start(raw.get("start")),
                "wallpaper": _wallpaper(raw.get("wallpaper")),
                "enabled": _enabled(raw.get("enabled", True)),
            }
        )
    return tasks


def homeCardTaskStates() -> dict[str, dict]:
    """`cfg.homeCardTaskState` 的一份副本，坏掉的条目丢掉。"""
    value = cfg.homeCardTaskState.value
    return {
        str(taskId): dict(state)
        for taskId, state in (value.items() if isinstance(value, dict) else ())
        if isinstance(state, dict)
    }


def homeCardTaskState(taskId: str) -> dict:
    return homeCardTaskStates().get(taskId, {})


def updateHomeCardTaskState(taskId: str, **changes) -> None:
    """改一条任务的运行状态；值为 None 的键删掉。"""
    states = homeCardTaskStates()
    state = dict(states.get(taskId, {}))
    for key, value in changes.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value
    if state == states.get(taskId, {}):
        return
    if state:
        states[taskId] = state
    else:
        states.pop(taskId, None)
    cfg.set(cfg.homeCardTaskState, states)
