"""Interval Task 的到点与 Catch-up Run。

到点时刻是"起点 + k × 间隔"，与上次实际何时执行无关；错过多少个到点都只补一次。只补这条规则
存在、开着、起点和间隔没改过期间的到点：每条任务从哪一刻起算（since）、最近执行到哪个到点
（lastDue）记在 `cfg.homeCardTaskState`，规则一变就从这一刻重新起算。理由见
docs/adr/0013-interval-and-wallpaper-tasks.md。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.common.home_card_tasks import (
    INTERVAL_HOME_CARD_TRIGGER,
    INTERVAL_START_FORMAT,
    INTERVAL_UNIT_SECONDS,
    homeCardTaskStates,
    normalizeHomeCardTasks,
)
from app.config.cfg import cfg

# 记下的时刻比现在晚这么多，当作时钟出过错（主板电池没电后又校正），从现在重新起算。
CLOCK_ERROR_LIMIT = timedelta(days=1)
INTERVAL_UNIT_LABELS = {"minute": "分钟", "hour": "小时", "day": "天"}


def intervalStep(task: dict) -> timedelta:
    interval = task["interval"]
    return timedelta(seconds=interval["value"] * INTERVAL_UNIT_SECONDS[interval["unit"]])


def intervalStart(task: dict, tzinfo) -> datetime:
    return datetime.strptime(task["start"], INTERVAL_START_FORMAT).replace(tzinfo=tzinfo)


def latestDue(task: dict, after: datetime, now: datetime) -> datetime | None:
    """`after` 之后、`now` 及以前最近的那个到点；没有就是 None。"""
    start = intervalStart(task, now.tzinfo)
    if now < start:
        return None
    step = intervalStep(task)
    point = start + (now - start) // step * step
    return point if point > after else None


def nextDue(task: dict, now: datetime) -> datetime:
    """`now` 之后的第一个到点。"""
    start = intervalStart(task, now.tzinfo)
    if now < start:
        return start
    step = intervalStep(task)
    return start + ((now - start) // step + 1) * step


def intervalLabel(task: dict) -> str:
    interval = task["interval"]
    return f"每 {interval['value']} {INTERVAL_UNIT_LABELS[interval['unit']]}"


def _ruleKey(task: dict, masterEnabled: bool) -> str:
    interval = task["interval"]
    return "|".join(
        (
            task["start"],
            str(interval["value"]),
            interval["unit"],
            "on" if task["enabled"] and masterEnabled else "off",
        )
    )


def _moment(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def dueIntervalTasks(tasks, masterEnabled: bool, now: datetime) -> list[dict]:
    """到点（包括错过了要补的）的 Interval Task，并记下它们执行到的到点。

    先核对规则、后判断到点，两步在同一次调用里：改了起点或间隔、打开开关的那一刻就重新起算，
    所以不会接着补执行改之前的到点。
    """
    if not isinstance(tasks, (list, tuple)):
        return []
    states = homeCardTaskStates()
    updated = {}
    due = []
    for raw in tasks:
        # 没有 ID 的任务每次规范化都换一个新 ID，记不住状态；启动时 MainWindow 已经补齐。
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
            continue
        state = dict(states.get(raw["id"], {}))
        updated[raw["id"]] = state
        # 每秒都要过一遍：其他任务不必规范化（轮换列表可能有几百个路径）。
        if raw.get("trigger") != INTERVAL_HOME_CARD_TRIGGER:
            continue
        task = normalizeHomeCardTasks([raw])[0]
        rule = _ruleKey(task, masterEnabled)
        since = _moment(state.get("since"))
        lastDue = _moment(state.get("lastDue"))
        if (
            state.get("rule") != rule
            or since is None
            or since - now > CLOCK_ERROR_LIMIT
            or (lastDue is not None and lastDue - now > CLOCK_ERROR_LIMIT)
        ):
            state.update({"rule": rule, "since": now.isoformat()})
            state.pop("lastDue", None)
            continue
        if not (masterEnabled and task["enabled"]):
            continue
        point = latestDue(task, max(since, lastDue) if lastDue else since, now)
        if point is None:
            continue
        state["lastDue"] = point.isoformat()
        due.append(task)
    # 删掉的任务不再留状态。
    updated = {taskId: state for taskId, state in updated.items() if state}
    if updated != states:
        cfg.set(cfg.homeCardTaskState, updated)
    return due
