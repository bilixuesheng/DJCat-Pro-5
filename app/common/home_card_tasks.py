from __future__ import annotations

from datetime import datetime

from app.common.home_cards import new_id, normalize_action

EXISTING_HOME_CARD_TASK = "existing"
CUSTOM_HOME_CARD_TASK = "custom"
HOME_CARD_TASK_KEY = "自动任务"
HOME_CARD_TASK_MODES = (EXISTING_HOME_CARD_TASK, CUSTOM_HOME_CARD_TASK)
SCHEDULED_HOME_CARD_TRIGGER = "time"
APPLICATION_HOME_CARD_TRIGGER = "application"
HOME_CARD_TASK_TRIGGERS = (
    SCHEDULED_HOME_CARD_TRIGGER,
    APPLICATION_HOME_CARD_TRIGGER,
)
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


def _actions(value) -> list[dict]:
    actions = [
        action
        for action in (
            normalize_action(item)
            for item in (value if isinstance(value, list) else [])
        )
        if action is not None
    ]
    actionIds = set()
    for action in actions:
        if action["id"] in actionIds:
            action["id"] = new_id()
        actionIds.add(action["id"])
    return actions


def normalize_home_card_tasks(value) -> list[dict]:
    tasks = []
    taskIds = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        taskId = _text(raw.get("id")) or new_id()
        if taskId in taskIds:
            taskId = new_id()
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
                "actions": _actions(raw.get("actions", [])),
                "enabled": _enabled(raw.get("enabled", True)),
            }
        )
    return tasks


__all__ = [
    "APPLICATION_HOME_CARD_TRIGGER",
    "APPLICATION_QUIT_EVENT",
    "APPLICATION_STARTUP_EVENT",
    "CLOSE_HOME_CARD_ACTION",
    "CUSTOM_HOME_CARD_TASK",
    "EXISTING_HOME_CARD_TASK",
    "HOME_CARD_TASK_ACTIONS",
    "HOME_CARD_TASK_EVENTS",
    "HOME_CARD_TASK_KEY",
    "HOME_CARD_TASK_MODES",
    "HOME_CARD_TASK_TRIGGERS",
    "OPEN_HOME_CARD_ACTION",
    "SCHEDULED_HOME_CARD_TRIGGER",
    "SILENT_STARTUP_EVENT",
    "normalize_home_card_tasks",
]
