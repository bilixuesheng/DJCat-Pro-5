from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PillPushButton,
    StrongBodyLabel,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.home_card_tasks import (
    APPLICATION_HOME_CARD_TRIGGER,
    APPLICATION_QUIT_EVENT,
    APPLICATION_STARTUP_EVENT,
    CLOSE_HOME_CARD_ACTION,
    CUSTOM_HOME_CARD_TASK,
    EXISTING_HOME_CARD_TASK,
    HOME_CARD_TASK_KEY,
    OPEN_HOME_CARD_ACTION,
    SCHEDULED_HOME_CARD_TRIGGER,
    SILENT_STARTUP_EVENT,
    normalize_home_card_tasks,
)
from app.common.home_cards import new_id, validate_action
from app.config.cfg import cfg
from app.view.components.home_card_dialog import ActionSequenceEditor
from app.view.components.task_page import (
    ScheduledTaskCard,
    ScheduledTaskDialog,
    ScheduledTaskPage,
)
from app.view.components.task_picker import TaskFormSettingCard, TouchTimePicker

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


def _available_home_cards(entries) -> list[dict]:
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


def _home_card_text(entry, occurrence=None):
    title = str(entry.get("title", "")).strip() or str(entry.get("key", ""))
    source = SOURCE_LABELS.get(entry.get("source"), "")
    if occurrence is not None:
        source = f"{source} {occurrence}".strip()
    return f"{title}（{source}）" if source else title


def update_home_card_options(widgets, entries):
    cards = _available_home_cards(entries)
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
            _home_card_text(entry, occurrence),
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


def create_home_card_task_form(
    parent,
    homeCards,
    initialData=None,
    scrollArea=None,
):
    now = QTime.currentTime()
    data = initialData or {
        "name": "",
        "time": now.toString("HH:mm:ss"),
        "weeks": list(range(7)),
        "trigger": SCHEDULED_HOME_CARD_TRIGGER,
        "event": APPLICATION_STARTUP_EVENT,
        "mode": EXISTING_HOME_CARD_TASK,
        "operation": OPEN_HOME_CARD_ACTION,
        "targetKey": "",
        "targetTitle": "",
        "actions": [],
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
    triggerIndex = triggerCombo.findData(data.get("trigger"))
    triggerCombo.setCurrentIndex(triggerIndex if triggerIndex >= 0 else 0)
    triggerCombo.setFixedWidth(180)
    layout.addWidget(
        TaskFormSettingCard(
            FIF.HISTORY,
            "触发时机",
            "选择固定时间或软件行为触发",
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

    modeCombo = ComboBox(form)
    modeCombo.addItem("已有卡片", userData=EXISTING_HOME_CARD_TASK)
    modeCombo.addItem("自定义", userData=CUSTOM_HOME_CARD_TASK)
    modeIndex = modeCombo.findData(data.get("mode"))
    modeCombo.setCurrentIndex(modeIndex if modeIndex >= 0 else 0)
    modeCombo.setFixedWidth(180)
    layout.addWidget(
        TaskFormSettingCard(
            FIF.APPLICATION,
            "任务类型",
            "执行已有主页卡片，或编排自定义动作",
            modeCombo,
            form,
        )
    )
    widgets["modeCombo"] = modeCombo

    homeCardCombo = ComboBox(form)
    homeCardCombo.setFixedWidth(280)
    widgets["homeCardCombo"] = homeCardCombo
    update_home_card_options(widgets, homeCards)
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
                "id": new_id(),
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

    def updateVisibility(*args):
        isExisting = modeCombo.currentData() == EXISTING_HOME_CARD_TASK
        isScheduled = triggerCombo.currentData() == SCHEDULED_HOME_CARD_TRIGGER
        selected = widgets.get("homeCards", {}).get(homeCardCombo.currentData())
        isDefault = selected is not None and selected.get("source") == "default"
        eventCard.setVisible(not isScheduled)
        timeCard.setVisible(isScheduled)
        weekCard.setVisible(isScheduled)
        homeCardCard.setVisible(isExisting)
        operationCard.setVisible(isExisting and isDefault)
        actionCard.setVisible(not isExisting)

    triggerCombo.currentIndexChanged.connect(updateVisibility)
    modeCombo.currentIndexChanged.connect(updateVisibility)
    homeCardCombo.currentIndexChanged.connect(updateVisibility)
    updateVisibility()
    return form, widgets


def home_card_task_data(widgets):
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
    }


class AddHomeCardTaskDialog(ScheduledTaskDialog):
    def __init__(self, homeCards, parent=None):
        super().__init__(
            "添加自动任务",
            lambda form, scrollArea: create_home_card_task_form(
                form,
                homeCards,
                scrollArea=scrollArea,
            ),
            home_card_task_data,
            parent,
            maxHeight=420,
            minWidth=640,
        )
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def validate(self):
        data = home_card_task_data(self.formWidgets)
        if data["mode"] == EXISTING_HOME_CARD_TASK:
            if data["targetKey"] not in self.formWidgets.get("homeCards", {}):
                InfoBar.error(
                    "无法保存",
                    "请选择一个当前存在的主页卡片",
                    duration=3000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return False
        else:
            if not data["actions"]:
                InfoBar.error(
                    "无法保存",
                    "至少添加一个动作",
                    duration=3000,
                    position=InfoBarPosition.TOP,
                    parent=self,
                )
                return False
            for action in data["actions"]:
                error = validate_action(action)
                if error:
                    InfoBar.error(
                        "动作无效",
                        error,
                        duration=3000,
                        position=InfoBarPosition.TOP,
                        parent=self,
                    )
                    return False
        return True

    def getData(self):
        return {"id": new_id(), **super().getData()}


class HomeCardTaskCard(ScheduledTaskCard):
    def __init__(self, data, homeCards, scrollArea, parent=None):
        self._homeCards = homeCards
        self._scrollArea = scrollArea
        self._homeCardKeys = {
            entry["key"] for entry in _available_home_cards(homeCards)
        }
        super().__init__(data, parent)

    def _createForm(self):
        return create_home_card_task_form(
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

    def _formData(self):
        self.formWidgets["targetTitle"] = self.data.get("targetTitle", "")
        return home_card_task_data(self.formWidgets)

    def _summary(self):
        if self.data.get("mode") == CUSTOM_HOME_CARD_TASK:
            target = f"自定义动作：{len(self.data.get('actions', []))} 个"
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
        else:
            trigger = f"触发时间：{self.data['time']}"
        return f"{trigger} · {target}"

    def setHomeCards(self, entries):
        self._homeCardKeys = {
            entry["key"] for entry in _available_home_cards(entries)
        }
        self.formWidgets["targetKey"] = self.data.get("targetKey", "")
        self.formWidgets["targetTitle"] = self.data.get("targetTitle", "")
        update_home_card_options(self.formWidgets, entries)
        self._saveData()


class HomeCardTaskPage(ScheduledTaskPage):
    def __init__(self, homeCards=None, parent=None):
        self._homeCards = _available_home_cards(homeCards or [])
        super().__init__(
            "自动任务",
            "还没有设置自动任务哦 ~",
            cfg.homeCardTasks,
            cfg.homeCardTasksEnabled,
            parent,
        )

    def setHomeCards(self, entries):
        self._homeCards = _available_home_cards(entries or [])
        for card in self._cards:
            card.setHomeCards(self._homeCards)

    def _normalizeTasks(self, tasks):
        return normalize_home_card_tasks(tasks)

    def _createCard(self, task):
        return HomeCardTaskCard(task, self._homeCards, self.scrollArea, self.view)

    def _createDialog(self):
        return AddHomeCardTaskDialog(self._homeCards, self.window())
