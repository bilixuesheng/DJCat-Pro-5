from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path, PureWindowsPath

from PySide6.QtCore import QDate, QDir, QTime
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PillPushButton,
    PushButton,
    SpinBox,
    StrongBodyLabel,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from app.common import clock
from app.common.home_card_tasks import (
    APPLICATION_HOME_CARD_TRIGGER,
    APPLICATION_QUIT_EVENT,
    APPLICATION_STARTUP_EVENT,
    CLOSE_HOME_CARD_ACTION,
    CUSTOM_HOME_CARD_TASK,
    EXISTING_HOME_CARD_TASK,
    FIXED_WALLPAPER,
    HOME_CARD_TASK_KEY,
    INTERVAL_HOME_CARD_TRIGGER,
    INTERVAL_START_FORMAT,
    OPEN_HOME_CARD_ACTION,
    PROCESS_GUARD_TRIGGER,
    ROTATION_WALLPAPER,
    SCHEDULED_HOME_CARD_TRIGGER,
    SILENT_STARTUP_EVENT,
    WALLPAPER_HOME_CARD_TASK,
    homeCardTaskState,
    normalizeHomeCardTasks,
    wallpaperKey,
)
from app.common.home_cards import newId
from app.common.interval_tasks import INTERVAL_UNIT_LABELS, intervalLabel, nextDue
from app.common.process_guard import guardRules, isSameProgram, stopLabel
from app.common.wallpaper import WALLPAPER_FILE_FILTER, isWallpaperImage
from app.config.cfg import cfg
from app.view.components.home_card_dialog import ActionSequenceEditor
from app.view.components.task_page import (
    ScheduledTaskCard,
    ScheduledTaskDialog,
    ScheduledTaskPage,
)
from app.view.components.task_picker import (
    TaskFormSettingCard,
    TouchDatePicker,
    TouchTimePicker,
)
from app.view.components.wallpaper_rotation import WallpaperRotationField

SOURCE_LABELS = {
    "custom": "自定义",
    "application": "应用",
}
APPLICATION_EVENT_LABELS = {
    APPLICATION_STARTUP_EVENT: "电教猫启动时",
    SILENT_STARTUP_EVENT: "电教猫开机静默启动时",
    APPLICATION_QUIT_EVENT: "电教猫关闭时",
}


class ActionSequenceSettingCard(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        title = StrongBodyLabel("动作列表", self)
        description = CaptionLabel(
            "触摸正文可滚动；从每行动作左侧的手柄拖动排序。",
            self,
        )
        description.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(editor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(
            QColor(0, 0, 0, 50)
            if isDarkTheme()
            else QColor(0, 0, 0, 19)
        )
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


def _availableHomeCards(entries) -> list[dict]:
    cards = []
    keys = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key", "")).strip()
        if not key or key == HOME_CARD_TASK_KEY or key in keys:
            continue
        keys.add(key)
        cards.append(dict(entry))
    return cards


def _homeCardText(entry, occurrence=None):
    title = str(entry.get("title", "")).strip() or str(entry.get("key", ""))
    source = SOURCE_LABELS.get(entry.get("source"), "")
    if occurrence is not None:
        source = f"{source} {occurrence}".strip()
    return f"{title}（{source}）" if source else title


def updateHomeCardOptions(widgets, entries):
    cards = _availableHomeCards(entries)
    combo = widgets["homeCardCombo"]
    selectedKey = combo.currentData() or widgets.get("targetKey", "")
    targetTitle = widgets.get("targetTitle", "")
    combo.blockSignals(True)
    combo.clear()

    labelCounts = {}
    for entry in cards:
        label = (
            str(entry.get("title", "")).strip() or entry["key"],
            SOURCE_LABELS.get(entry.get("source"), ""),
        )
        labelCounts[label] = labelCounts.get(label, 0) + 1
    labelOccurrences = {}
    for entry in cards:
        label = (
            str(entry.get("title", "")).strip() or entry["key"],
            SOURCE_LABELS.get(entry.get("source"), ""),
        )
        labelOccurrences[label] = labelOccurrences.get(label, 0) + 1
        occurrence = labelOccurrences[label] if labelCounts[label] > 1 else None
        combo.addItem(
            _homeCardText(entry, occurrence),
            userData=entry["key"],
        )

    if selectedKey and all(entry["key"] != selectedKey for entry in cards):
        combo.addItem(
            f"{targetTitle or selectedKey}（已失效）",
            userData=selectedKey,
        )
    if combo.count() == 0:
        combo.addItem("暂无可用主页卡片", userData=None)
    index = combo.findData(selectedKey)
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)
    widgets["homeCards"] = {entry["key"]: entry for entry in cards}


def _momentText(moment: datetime, now: datetime) -> str:
    days = (moment.date() - now.date()).days
    day = {0: "今天", 1: "明天"}.get(days, f"{moment.month}月{moment.day}日")
    clock = moment.strftime("%H:%M:%S" if moment.second else "%H:%M")
    return f"{day} {clock}"


def intervalSummary(task: dict, now: datetime) -> str:
    """「每 2 小时 · 下次 今天 10:00」。"""
    return f"{intervalLabel(task)} · 下次 {_momentText(nextDue(task, now), now)}"


def wallpaperSummary(task: dict, state: dict) -> str:
    wallpaper = task["wallpaper"]
    if wallpaper["mode"] == FIXED_WALLPAPER:
        name = PureWindowsPath(wallpaper["fixed"]).name
        return f"固定 · {name or '未选择图片'}"
    rotation = wallpaper["rotation"]
    if not rotation:
        return "轮换 · 列表为空"
    current = state.get("wallpaper", "")
    if not current:
        return "轮换 · 尚未执行"
    name = PureWindowsPath(current).name
    keys = [wallpaperKey(path) for path in rotation]
    if wallpaperKey(current) in keys:
        return f"轮换 {keys.index(wallpaperKey(current)) + 1}/{len(rotation)} · {name}"
    return f"轮换 · {name}"


def _pathInput(parent, placeholder, choose):
    wrapper = QWidget(parent)
    row = QHBoxLayout(wrapper)
    row.setContentsMargins(0, 0, 0, 0)
    line = LineEdit(wrapper)
    line.setPlaceholderText(placeholder)
    line.setFixedWidth(260)
    button = PushButton(FIF.FOLDER, "选择", wrapper)

    def browse():
        path = choose(parent)
        if path:
            line.setText(QDir.toNativeSeparators(path))
            line.editingFinished.emit()

    button.clicked.connect(browse)
    row.addWidget(line)
    row.addWidget(button)
    return wrapper, line


def createHomeCardTaskForm(
    parent,
    homeCards,
    initialData=None,
    scrollArea=None,
):
    now = clock.scheduledTaskNow("home-card")
    data = initialData or {
        "name": "",
        "time": now.strftime("%H:%M:%S"),
        "weeks": list(range(7)),
        "trigger": SCHEDULED_HOME_CARD_TRIGGER,
        "event": APPLICATION_STARTUP_EVENT,
        "mode": EXISTING_HOME_CARD_TASK,
        "operation": OPEN_HOME_CARD_ACTION,
        "targetKey": "",
        "targetTitle": "",
        "actions": [],
        "program": {"target": "", "arguments": "", "working_dir": ""},
        "interval": {"value": 1, "unit": "day"},
        "start": now.strftime("%Y-%m-%d 00:00:00"),
        "wallpaper": {"mode": FIXED_WALLPAPER, "fixed": "", "rotation": []},
    }
    form = QWidget(parent)
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    widgets = {
        "targetKey": data.get("targetKey", ""),
        "targetTitle": data.get("targetTitle", ""),
    }

    nameInput = LineEdit(form)
    nameInput.setMaxLength(40)
    nameInput.setText(data.get("name", ""))
    nameInput.setPlaceholderText("任务名称（例如：打开课程表）")
    layout.addWidget(
        TaskFormSettingCard(
            FIF.EDIT,
            "任务名称",
            "设置该自动任务的标题",
            nameInput,
            form,
        )
    )
    widgets["nameInput"] = nameInput

    triggerCombo = ComboBox(form)
    triggerCombo.addItem("固定时间", userData=SCHEDULED_HOME_CARD_TRIGGER)
    triggerCombo.addItem("软件行为", userData=APPLICATION_HOME_CARD_TRIGGER)
    triggerCombo.addItem("间隔时间", userData=INTERVAL_HOME_CARD_TRIGGER)
    triggerCombo.addItem("进程守护", userData=PROCESS_GUARD_TRIGGER)
    triggerIndex = triggerCombo.findData(data.get("trigger"))
    triggerCombo.setCurrentIndex(triggerIndex if triggerIndex >= 0 else 0)
    triggerCombo.setFixedWidth(180)
    layout.addWidget(
        TaskFormSettingCard(
            FIF.HISTORY,
            "触发时机",
            "选择固定时间、软件行为、间隔时间或进程守护",
            triggerCombo,
            form,
        )
    )
    widgets["triggerCombo"] = triggerCombo

    eventCombo = ComboBox(form)
    for event, label in APPLICATION_EVENT_LABELS.items():
        eventCombo.addItem(label, userData=event)
    eventIndex = eventCombo.findData(data.get("event"))
    eventCombo.setCurrentIndex(eventIndex if eventIndex >= 0 else 0)
    eventCombo.setFixedWidth(220)
    eventCard = TaskFormSettingCard(
        FIF.APPLICATION,
        "软件行为",
        "选择触发任务的软件行为",
        eventCombo,
        form,
    )
    layout.addWidget(eventCard)
    widgets["eventCombo"] = eventCombo
    widgets["eventCard"] = eventCard

    program = data.get("program") if isinstance(data.get("program"), dict) else {}
    programWrapper, programInput = _pathInput(
        form,
        "要一直开着的 .exe",
        lambda owner: QFileDialog.getOpenFileName(
            owner, "选择要守护的程序", "", "程序 (*.exe)"
        )[0],
    )
    programInput.setText(program.get("target", ""))
    programCard = TaskFormSettingCard(
        FIF.APPLICATION,
        "守护程序",
        "电教猫运行期间，它一不在就把它重新打开",
        programWrapper,
        form,
    )
    layout.addWidget(programCard)
    widgets["programInput"] = programInput
    widgets["programCard"] = programCard

    argumentsInput = LineEdit(form)
    argumentsInput.setPlaceholderText("可选，例如 --tray")
    argumentsInput.setFixedWidth(260)
    argumentsInput.setText(program.get("arguments", ""))
    argumentsCard = TaskFormSettingCard(
        FIF.COMMAND_PROMPT,
        "启动参数",
        "重新打开时传给程序的参数",
        argumentsInput,
        form,
    )
    layout.addWidget(argumentsCard)
    widgets["argumentsInput"] = argumentsInput
    widgets["argumentsCard"] = argumentsCard

    workingDirWrapper, workingDirInput = _pathInput(
        form,
        "可选，默认为程序所在的文件夹",
        lambda owner: QFileDialog.getExistingDirectory(owner, "选择工作目录"),
    )
    workingDirInput.setText(program.get("working_dir", ""))
    workingDirCard = TaskFormSettingCard(
        FIF.FOLDER,
        "工作目录",
        "重新打开程序时使用的工作目录",
        workingDirWrapper,
        form,
    )
    layout.addWidget(workingDirCard)
    widgets["workingDirInput"] = workingDirInput
    widgets["workingDirCard"] = workingDirCard

    timePicker = TouchTimePicker(form, showSeconds=True)
    taskTime = QTime.fromString(data.get("time", ""), "HH:mm:ss")
    timePicker.setTime(taskTime if taskTime.isValid() else now)
    timeCard = TaskFormSettingCard(
        FIF.ALBUM,
        "执行时间",
        "设置触发任务的具体时间",
        timePicker,
        form,
    )
    layout.addWidget(timeCard)
    widgets["timePicker"] = timePicker
    widgets["timeCard"] = timeCard

    weekWidget = QWidget(form)
    weekLayout = QHBoxLayout(weekWidget)
    weekLayout.setContentsMargins(0, 0, 0, 0)
    weekButtons = []
    for index, day in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
        button = PillPushButton(day, weekWidget)
        button.setCheckable(True)
        button.setChecked(index in data.get("weeks", []))
        weekButtons.append(button)
        weekLayout.addWidget(button)
    weekCard = TaskFormSettingCard(
        FIF.CALENDAR,
        "重复频率",
        "选择在一周中的哪几天执行",
        weekWidget,
        form,
    )
    layout.addWidget(weekCard)
    widgets["weekButtons"] = weekButtons
    widgets["weekCard"] = weekCard

    interval = data.get("interval") if isinstance(data.get("interval"), dict) else {}
    intervalWidget = QWidget(form)
    intervalLayout = QHBoxLayout(intervalWidget)
    intervalLayout.setContentsMargins(0, 0, 0, 0)
    intervalSpin = SpinBox(intervalWidget)
    intervalSpin.setRange(1, 99999)
    intervalSpin.setValue(int(interval.get("value", 1)))
    intervalSpin.setFixedWidth(150)
    unitCombo = ComboBox(intervalWidget)
    for unit, label in INTERVAL_UNIT_LABELS.items():
        unitCombo.addItem(label, userData=unit)
    unitIndex = unitCombo.findData(interval.get("unit"))
    unitCombo.setCurrentIndex(unitIndex if unitIndex >= 0 else 2)
    unitCombo.setFixedWidth(100)
    intervalLayout.addWidget(intervalSpin)
    intervalLayout.addWidget(unitCombo)
    intervalCard = TaskFormSettingCard(
        FIF.SYNC,
        "间隔",
        "每隔多久执行一次",
        intervalWidget,
        form,
    )
    layout.addWidget(intervalCard)
    widgets["intervalSpin"] = intervalSpin
    widgets["unitCombo"] = unitCombo
    widgets["intervalCard"] = intervalCard

    try:
        start = datetime.strptime(data.get("start", ""), INTERVAL_START_FORMAT)
    except (TypeError, ValueError):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    startDatePicker = TouchDatePicker(form)
    startDatePicker.setDate(QDate(start.year, start.month, start.day))
    startDateCard = TaskFormSettingCard(
        FIF.CALENDAR,
        "起始日期",
        "间隔从这一天开始算",
        startDatePicker,
        form,
    )
    layout.addWidget(startDateCard)
    startTimePicker = TouchTimePicker(form, showSeconds=True)
    startTimePicker.setTime(QTime(start.hour, start.minute, start.second))
    startTimeCard = TaskFormSettingCard(
        FIF.ALBUM,
        "起始时间",
        "没开时错过的，下次打开补一次",
        startTimePicker,
        form,
    )
    layout.addWidget(startTimeCard)
    widgets["startDatePicker"] = startDatePicker
    widgets["startTimePicker"] = startTimePicker
    widgets["startDateCard"] = startDateCard
    widgets["startTimeCard"] = startTimeCard

    modeCombo = ComboBox(form)
    modeCombo.addItem("已有卡片", userData=EXISTING_HOME_CARD_TASK)
    modeCombo.addItem("自定义", userData=CUSTOM_HOME_CARD_TASK)
    modeCombo.addItem("更换壁纸", userData=WALLPAPER_HOME_CARD_TASK)
    modeIndex = modeCombo.findData(data.get("mode"))
    modeCombo.setCurrentIndex(modeIndex if modeIndex >= 0 else 0)
    modeCombo.setFixedWidth(180)
    modeCard = TaskFormSettingCard(
        FIF.APPLICATION,
        "任务类型",
        "执行已有主页卡片、编排自定义动作，或更换桌面壁纸",
        modeCombo,
        form,
    )
    layout.addWidget(modeCard)
    widgets["modeCombo"] = modeCombo
    widgets["modeCard"] = modeCard

    homeCardCombo = ComboBox(form)
    homeCardCombo.setFixedWidth(280)
    widgets["homeCardCombo"] = homeCardCombo
    updateHomeCardOptions(widgets, homeCards)
    homeCardCard = TaskFormSettingCard(
        FIF.HOME,
        "已有卡片",
        "触发后执行所选主页卡片",
        homeCardCombo,
        form,
    )
    layout.addWidget(homeCardCard)
    widgets["homeCardCard"] = homeCardCard

    operationCombo = ComboBox(form)
    operationCombo.addItem("打开", userData=OPEN_HOME_CARD_ACTION)
    operationCombo.addItem("关闭", userData=CLOSE_HOME_CARD_ACTION)
    operationIndex = operationCombo.findData(data.get("operation"))
    operationCombo.setCurrentIndex(operationIndex if operationIndex >= 0 else 0)
    operationCombo.setFixedWidth(180)
    operationCard = TaskFormSettingCard(
        FIF.POWER_BUTTON,
        "执行动作",
        "选择打开或关闭所选默认功能",
        operationCombo,
        form,
    )
    layout.addWidget(operationCard)
    widgets["operationCombo"] = operationCombo
    widgets["operationCard"] = operationCard

    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    if not actions:
        actions = [
            {
                "id": newId(),
                "type": "program",
                "target": "",
                "arguments": "",
                "working_dir": "",
                "wait": False,
            }
        ]
        widgets["placeholderActionId"] = actions[0]["id"]
    actionEditor = ActionSequenceEditor(actions, form)
    widgets["actionsDirty"] = False

    def markActionsDirty():
        widgets["actionsDirty"] = True

    actionEditor.changed.connect(markActionsDirty)
    if scrollArea is not None:
        actionEditor.setScrollArea(scrollArea)
    actionCard = ActionSequenceSettingCard(actionEditor, form)
    layout.addWidget(actionCard)
    widgets["actionEditor"] = actionEditor
    widgets["actionCard"] = actionCard

    wallpaper = data.get("wallpaper") if isinstance(data.get("wallpaper"), dict) else {}
    wallpaperModeCombo = ComboBox(form)
    wallpaperModeCombo.addItem("固定", userData=FIXED_WALLPAPER)
    wallpaperModeCombo.addItem("轮换", userData=ROTATION_WALLPAPER)
    wallpaperModeIndex = wallpaperModeCombo.findData(wallpaper.get("mode"))
    wallpaperModeCombo.setCurrentIndex(max(0, wallpaperModeIndex))
    wallpaperModeCombo.setFixedWidth(180)
    wallpaperModeCard = TaskFormSettingCard(
        FIF.PHOTO,
        "壁纸",
        "每次都设回同一张，或按列表轮换；所有屏幕同一张",
        wallpaperModeCombo,
        form,
    )
    layout.addWidget(wallpaperModeCard)
    widgets["wallpaperModeCombo"] = wallpaperModeCombo
    widgets["wallpaperModeCard"] = wallpaperModeCard

    fixedWrapper, fixedInput = _pathInput(
        form,
        "JPG、PNG 或 BMP 图片",
        lambda owner: QFileDialog.getOpenFileName(
            owner, "选择壁纸图片", "", WALLPAPER_FILE_FILTER
        )[0],
    )
    fixedInput.setText(wallpaper.get("fixed", ""))
    fixedWallpaperCard = TaskFormSettingCard(
        FIF.PHOTO,
        "固定壁纸",
        "每次执行都换成这一张",
        fixedWrapper,
        form,
    )
    layout.addWidget(fixedWallpaperCard)
    widgets["fixedWallpaperInput"] = fixedInput
    widgets["fixedWallpaperCard"] = fixedWallpaperCard

    rotationField = WallpaperRotationField(
        wallpaper.get("rotation", []),
        data.get("id", ""),
        form,
    )
    rotationCard = TaskFormSettingCard(
        FIF.ALBUM,
        "轮换列表",
        "每次换下一张，最后一张之后回到第一张",
        rotationField,
        form,
    )
    layout.addWidget(rotationCard)
    widgets["rotationField"] = rotationField
    widgets["rotationCard"] = rotationCard

    def updateVisibility(*args):
        trigger = triggerCombo.currentData()
        isGuard = trigger == PROCESS_GUARD_TRIGGER
        mode = modeCombo.currentData()
        isExisting = mode == EXISTING_HOME_CARD_TASK
        isWallpaper = not isGuard and mode == WALLPAPER_HOME_CARD_TASK
        isScheduled = trigger == SCHEDULED_HOME_CARD_TRIGGER
        isInterval = trigger == INTERVAL_HOME_CARD_TRIGGER
        isFixed = wallpaperModeCombo.currentData() == FIXED_WALLPAPER
        selected = widgets.get("homeCards", {}).get(homeCardCombo.currentData())
        isDefault = selected is not None and selected.get("source") == "default"
        eventCard.setVisible(trigger == APPLICATION_HOME_CARD_TRIGGER)
        timeCard.setVisible(isScheduled)
        weekCard.setVisible(isScheduled)
        for card in (intervalCard, startDateCard, startTimeCard):
            card.setVisible(isInterval)
        for card in (programCard, argumentsCard, workingDirCard):
            card.setVisible(isGuard)
        modeCard.setVisible(not isGuard)
        homeCardCard.setVisible(not isGuard and isExisting)
        operationCard.setVisible(not isGuard and isExisting and isDefault)
        actionCard.setVisible(not isGuard and mode == CUSTOM_HOME_CARD_TASK)
        wallpaperModeCard.setVisible(isWallpaper)
        fixedWallpaperCard.setVisible(isWallpaper and isFixed)
        rotationCard.setVisible(isWallpaper and not isFixed)

    triggerCombo.currentIndexChanged.connect(updateVisibility)
    modeCombo.currentIndexChanged.connect(updateVisibility)
    homeCardCombo.currentIndexChanged.connect(updateVisibility)
    wallpaperModeCombo.currentIndexChanged.connect(updateVisibility)
    updateVisibility()
    return form, widgets


def homeCardTaskData(widgets):
    targetKey = widgets["homeCardCombo"].currentData() or ""
    entry = widgets.get("homeCards", {}).get(targetKey)
    mode = widgets["modeCombo"].currentData() or EXISTING_HOME_CARD_TASK
    actions = widgets["actionEditor"].actions()
    placeholderActionId = widgets.get("placeholderActionId")
    if (
        not widgets.get("actionsDirty", False)
        and len(actions) == 1
        and actions[0].get("id") == placeholderActionId
    ):
        actions = []
    return {
        "name": widgets["nameInput"].text().strip() or "未命名任务",
        "time": widgets["timePicker"].getTime().toString("HH:mm:ss"),
        "weeks": [
            index
            for index, button in enumerate(widgets["weekButtons"])
            if button.isChecked()
        ],
        "trigger": (
            widgets["triggerCombo"].currentData() or SCHEDULED_HOME_CARD_TRIGGER
        ),
        "event": widgets["eventCombo"].currentData() or APPLICATION_STARTUP_EVENT,
        "mode": mode,
        "operation": (
            widgets["operationCombo"].currentData() or OPEN_HOME_CARD_ACTION
            if entry is not None and entry.get("source") == "default"
            else OPEN_HOME_CARD_ACTION
        ),
        "targetKey": targetKey,
        "targetTitle": (
            str(entry.get("title", "")).strip()
            if entry is not None
            else widgets.get("targetTitle", "")
        ),
        "actions": actions,
        "program": {
            "target": widgets["programInput"].text().strip(),
            "arguments": widgets["argumentsInput"].text().strip(),
            "working_dir": widgets["workingDirInput"].text().strip(),
        },
        "interval": {
            "value": widgets["intervalSpin"].value(),
            "unit": widgets["unitCombo"].currentData() or "day",
        },
        "start": (
            f"{widgets['startDatePicker'].getDate().toString('yyyy-MM-dd')} "
            f"{widgets['startTimePicker'].getTime().toString('HH:mm:ss')}"
        ),
        "wallpaper": {
            "mode": widgets["wallpaperModeCombo"].currentData() or FIXED_WALLPAPER,
            "fixed": widgets["fixedWallpaperInput"].text().strip(),
            "rotation": widgets["rotationField"].paths(),
        },
    }


def _fixedWallpaperProblem(path):
    if not path:
        return "请选择壁纸图片"
    if not isWallpaperImage(path):
        return "壁纸只支持 JPG、PNG 或 BMP 图片"
    if not Path(os.path.expandvars(path)).is_file():
        return "找不到这张图片"
    return ""


def _wallpaperProblem(wallpaper):
    if wallpaper["mode"] == FIXED_WALLPAPER:
        return _fixedWallpaperProblem(wallpaper["fixed"])
    if not wallpaper["rotation"]:
        return "轮换列表里还没有图片"
    return ""


def _guardProgramProblem(target, taskId=None):
    if not target:
        return "请选择要守护的程序"
    # 快捷方式不是进程，没法据此判断程序在不在运行。
    if not target.lower().endswith(".exe"):
        return "只能守护 .exe 程序；快捷方式可右键「打开文件所在的位置」找到它"
    if not Path(os.path.expandvars(target)).is_file():
        return "程序文件不存在"
    if any(
        rule["id"] != taskId and isSameProgram(rule["program"]["target"], target)
        for rule in guardRules(cfg.homeCardTasks.value)
    ):
        return "已有守护这个程序的自动任务"
    return ""


class AddHomeCardTaskDialog(ScheduledTaskDialog):
    def __init__(self, homeCards, parent=None):
        super().__init__(
            "添加自动任务",
            lambda form, scrollArea: createHomeCardTaskForm(
                form,
                homeCards,
                scrollArea=scrollArea,
            ),
            homeCardTaskData,
            parent,
            maxHeight=420,
            minWidth=640,
        )
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def validate(self):
        widgets = self.formWidgets
        data = homeCardTaskData(widgets)
        if data["trigger"] == PROCESS_GUARD_TRIGGER:
            problem = _guardProgramProblem(data["program"]["target"])
        elif data["mode"] == CUSTOM_HOME_CARD_TASK:
            return widgets["actionEditor"].validate(self)
        elif data["mode"] == WALLPAPER_HOME_CARD_TASK:
            problem = _wallpaperProblem(data["wallpaper"])
        elif data["targetKey"] in widgets.get("homeCards", {}):
            problem = ""
        else:
            problem = "请选择一个当前存在的主页卡片"
        if not problem:
            return True
        InfoBar.error(
            "无法保存",
            problem,
            duration=3000,
            position=InfoBarPosition.TOP,
            parent=self,
        )
        return False

    def getData(self):
        return {"id": newId(), **super().getData()}


class HomeCardTaskCard(ScheduledTaskCard):
    def __init__(self, data, homeCards, scrollArea, guardStop="", parent=None):
        self._homeCards = homeCards
        self._scrollArea = scrollArea
        self._guardStop = guardStop
        self._homeCardKeys = {
            entry["key"] for entry in _availableHomeCards(homeCards)
        }
        super().__init__(data, parent)

    def _createForm(self):
        return createHomeCardTaskForm(
            self,
            self._homeCards,
            self.data,
            self._scrollArea,
        )

    def _bindForm(self):
        widgets = self.formWidgets
        widgets["nameInput"].textChanged.connect(self._saveData)
        widgets["timePicker"].timeChanged.connect(self._saveData)
        for button in widgets["weekButtons"]:
            button.clicked.connect(self._saveData)
        widgets["triggerCombo"].currentIndexChanged.connect(self._saveData)
        widgets["triggerCombo"].currentIndexChanged.connect(self._refreshFormHeight)
        widgets["eventCombo"].currentIndexChanged.connect(self._saveData)
        widgets["modeCombo"].currentIndexChanged.connect(self._saveData)
        widgets["modeCombo"].currentIndexChanged.connect(self._refreshFormHeight)
        widgets["homeCardCombo"].currentIndexChanged.connect(self._saveData)
        widgets["homeCardCombo"].currentIndexChanged.connect(self._refreshFormHeight)
        widgets["operationCombo"].currentIndexChanged.connect(self._saveData)
        widgets["actionEditor"].changed.connect(self._saveData)
        # 输完才存：边打字边存，打到一半的路径会被守护当成新规则去拉起。
        widgets["programInput"].editingFinished.connect(self._onProgramEdited)
        widgets["argumentsInput"].editingFinished.connect(self._saveData)
        widgets["workingDirInput"].editingFinished.connect(self._saveData)
        widgets["intervalSpin"].valueChanged.connect(self._saveData)
        widgets["unitCombo"].currentIndexChanged.connect(self._saveData)
        widgets["startDatePicker"].dateChanged.connect(self._saveData)
        widgets["startTimePicker"].timeChanged.connect(self._saveData)
        widgets["wallpaperModeCombo"].currentIndexChanged.connect(self._saveData)
        widgets["wallpaperModeCombo"].currentIndexChanged.connect(
            self._refreshFormHeight
        )
        widgets["fixedWallpaperInput"].editingFinished.connect(
            self._onFixedWallpaperEdited
        )
        widgets["rotationField"].changed.connect(self._saveData)
        cfg.homeCardTaskState.valueChanged.connect(self._onTaskStateChanged)

    def _formData(self):
        self.formWidgets["targetTitle"] = self.data.get("targetTitle", "")
        return homeCardTaskData(self.formWidgets)

    def _onProgramEdited(self):
        programInput = self.formWidgets["programInput"]
        saved = self.data.get("program", {}).get("target", "")
        target = programInput.text().strip()
        if target == saved:
            return
        problem = _guardProgramProblem(target, self.data["id"])
        if problem:
            programInput.setText(saved)
            InfoBar.error(
                "无法保存",
                problem,
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
            return
        self._saveData()

    def _onFixedWallpaperEdited(self):
        fixedInput = self.formWidgets["fixedWallpaperInput"]
        saved = self.data.get("wallpaper", {}).get("fixed", "")
        path = fixedInput.text().strip()
        if path == saved:
            return
        problem = _fixedWallpaperProblem(path)
        if problem:
            fixedInput.setText(saved)
            InfoBar.error(
                "无法保存",
                problem,
                duration=3000,
                position=InfoBarPosition.TOP,
                parent=self.window(),
            )
            return
        self._saveData()

    def _onTaskStateChanged(self, *args):
        self.formWidgets["rotationField"].refresh()
        self.refreshSummary()

    def refreshSummary(self):
        self.expandCard.card.setContent(self._summary())

    def setGuardStop(self, reason):
        if reason == self._guardStop:
            return
        self._guardStop = reason
        self.expandCard.card.setContent(self._summary())

    def _summary(self):
        if self.data.get("trigger") == PROCESS_GUARD_TRIGGER:
            target = self.data.get("program", {}).get("target", "")
            summary = f"进程守护 · {PureWindowsPath(target).name or '未选择程序'}"
            if self._guardStop:
                summary += f"（已停止：{stopLabel(self._guardStop)}）"
            return summary
        if self.data.get("mode") == CUSTOM_HOME_CARD_TASK:
            target = f"自定义动作：{len(self.data.get('actions', []))} 个"
        elif self.data.get("mode") == WALLPAPER_HOME_CARD_TASK:
            target = wallpaperSummary(self.data, homeCardTaskState(self.data["id"]))
        else:
            targetKey = self.data.get("targetKey", "")
            target = self.data.get("targetTitle") or targetKey or "目标卡片"
            if targetKey not in self._homeCardKeys:
                target = f"{target}（已失效）"
            if self.data.get("operation") == CLOSE_HOME_CARD_ACTION:
                target = f"关闭{target}"
        if self.data.get("trigger") == APPLICATION_HOME_CARD_TRIGGER:
            trigger = APPLICATION_EVENT_LABELS.get(
                self.data.get("event"),
                APPLICATION_EVENT_LABELS[APPLICATION_STARTUP_EVENT],
            )
        elif self.data.get("trigger") == INTERVAL_HOME_CARD_TRIGGER:
            trigger = intervalSummary(self.data, clock.scheduledTaskNow("home-card"))
        else:
            trigger = f"触发时间：{self.data['time']}"
        return f"{trigger} · {target}"

    def setHomeCards(self, entries):
        self._homeCardKeys = {
            entry["key"] for entry in _availableHomeCards(entries)
        }
        self.formWidgets["targetKey"] = self.data.get("targetKey", "")
        self.formWidgets["targetTitle"] = self.data.get("targetTitle", "")
        updateHomeCardOptions(self.formWidgets, entries)
        self._saveData()


class HomeCardTaskPage(ScheduledTaskPage):
    def __init__(self, homeCards=None, parent=None):
        self._homeCards = _availableHomeCards(homeCards or [])
        self._guardStops = {}
        super().__init__(
            "自动任务",
            "还没有设置自动任务哦 ~",
            cfg.homeCardTasks,
            cfg.homeCardTasksEnabled,
            parent,
        )

    def setHomeCards(self, entries):
        self._homeCards = _availableHomeCards(entries or [])
        for card in self._cards:
            card.setHomeCards(self._homeCards)

    def setGuardStops(self, stops):
        """本次运行内已经停止守护的 Process Guard（任务 ID → 原因），显示在卡片摘要里。"""
        self._guardStops = dict(stops)
        for card in self._cards:
            card.setGuardStop(self._guardStops.get(card.data["id"], ""))

    def _normalizeTasks(self, tasks):
        return normalizeHomeCardTasks(tasks)

    def showEvent(self, event):
        # 「下次」的时刻随时间过去，回到页面时重算。
        for card in self._cards:
            card.refreshSummary()
        super().showEvent(event)

    def _createCard(self, task):
        return HomeCardTaskCard(
            task,
            self._homeCards,
            self.scrollArea,
            self._guardStops.get(task["id"], ""),
            self.view,
        )

    def _createDialog(self):
        return AddHomeCardTaskDialog(self._homeCards, self.window())
