from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PillPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
    ToolButton,
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
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import SettingMaterialCard
from app.view.components.task_picker import (
    TaskExpandSettingCard,
    TaskFormSettingCard,
    TouchTimePicker,
    configure_task_expand_card,
)

SOURCE_LABELS = {
    "custom": "自定义",
    "application": "应用",
}
APPLICATION_EVENT_LABELS = {
    APPLICATION_STARTUP_EVENT: "电教猫启动时",
    SILENT_STARTUP_EVENT: "电教猫开机静默启动时",
    APPLICATION_QUIT_EVENT: "电教猫关闭时",
}


class HomeCardTaskSettingCard(TaskFormSettingCard):
    pass


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
        HomeCardTaskSettingCard(
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
        HomeCardTaskSettingCard(
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
    eventCard = HomeCardTaskSettingCard(
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
    timeCard = HomeCardTaskSettingCard(
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
    weekCard = HomeCardTaskSettingCard(
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
        HomeCardTaskSettingCard(
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
    homeCardCard = HomeCardTaskSettingCard(
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
    operationCard = HomeCardTaskSettingCard(
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


class AddHomeCardTaskDialog(MessageBoxBase):
    def __init__(self, homeCards, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("添加自动任务", self)
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.formWidget, self.formWidgets = create_home_card_task_form(
            self,
            homeCards,
            scrollArea=self.scrollArea,
        )
        self.scrollArea.setWidget(self.formWidget)
        self.scrollArea.setMinimumHeight(180)
        self.scrollArea.setMaximumHeight(420)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addWidget(self.scrollArea)
        self.widget.setMinimumWidth(640)
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
        return {
            "id": new_id(),
            **home_card_task_data(self.formWidgets),
            "enabled": True,
        }


class HomeCardTaskCard(SettingMaterialCard):
    deleteClicked = Signal(str)
    dataChanged = Signal()

    def __init__(self, data, homeCards, scrollArea, parent=None):
        super().__init__(parent)
        self.data = data
        self._homeCardKeys = {
            entry["key"] for entry in _available_home_cards(homeCards)
        }
        self.expandCard = TaskExpandSettingCard(
            FIF.HISTORY,
            data["name"],
            self._summary(),
            self,
        )
        self.paintFilter = self.applyExpandCardMaterial(self.expandCard)
        self.expandBehavior = configure_task_expand_card(self.expandCard)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.expandCard)

        self.titleLabel = None
        self.summaryLabel = None
        for label in self.findChildren(QLabel):
            if label.text() == data["name"]:
                self.titleLabel = label
            elif label.text() == self._summary():
                self.summaryLabel = label

        self.enableSwitch = SwitchButton(self)
        self.enableSwitch.setChecked(data.get("enabled", True))
        self.expandCard.addWidget(self.enableSwitch)

        self.formWidget, self.formWidgets = create_home_card_task_form(
            self,
            homeCards,
            data,
            scrollArea,
        )
        self.formHeightTimer = QTimer(self)
        self.formHeightTimer.setSingleShot(True)
        self.formHeightTimer.setInterval(10)
        self.formHeightTimer.timeout.connect(self.expandCard._adjustViewSize)
        self._bindForm()

        deleteButton = PushButton(FIF.DELETE, "删除任务", self)
        deleteButton.clicked.connect(lambda: self.deleteClicked.emit(self.data["id"]))
        buttonLayout = QHBoxLayout()
        buttonLayout.setContentsMargins(16, 0, 16, 0)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(deleteButton)

        container = QWidget(self)
        containerLayout = QVBoxLayout(container)
        containerLayout.setContentsMargins(0, 0, 0, 16)
        containerLayout.addWidget(self.formWidget)
        containerLayout.addSpacing(10)
        containerLayout.addLayout(buttonLayout)
        self.expandCard.viewLayout.addWidget(container)

    def _bindForm(self):
        widgets = self.formWidgets
        self.enableSwitch.checkedChanged.connect(self._onEnabledChanged)
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

    def _onEnabledChanged(self, checked):
        if self.data.get("enabled", True) == checked:
            return
        self.data["enabled"] = checked
        self.dataChanged.emit()

    def _saveData(self, *args):
        self.formWidgets["targetTitle"] = self.data.get("targetTitle", "")
        updated = home_card_task_data(self.formWidgets)
        changed = any(self.data.get(key) != value for key, value in updated.items())
        self.data.update(updated)
        if self.titleLabel is not None:
            self.titleLabel.setText(self.data["name"])
        if self.summaryLabel is not None:
            self.summaryLabel.setText(self._summary())
        if changed:
            self.dataChanged.emit()

    def _refreshFormHeight(self):
        self.expandCard._adjustViewSize()
        self.formHeightTimer.start()

    def setHomeCards(self, entries):
        self._homeCardKeys = {
            entry["key"] for entry in _available_home_cards(entries)
        }
        self.formWidgets["targetKey"] = self.data.get("targetKey", "")
        self.formWidgets["targetTitle"] = self.data.get("targetTitle", "")
        update_home_card_options(self.formWidgets, entries)
        self._saveData()


class HomeCardTaskPage(ScrollArea):
    backSignal = Signal()

    def __init__(self, homeCards=None, parent=None):
        super().__init__(parent)
        self._homeCards = _available_home_cards(homeCards or [])
        self._cards = []
        self.view = QWidget()
        self.layout = QVBoxLayout(self.view)
        self.layout.setContentsMargins(30, 30, 30, 30)

        header = QHBoxLayout()
        self.backButton = ToolButton(FIF.RETURN, self)
        self.backButton.clicked.connect(self.backSignal.emit)
        self.titleLabel = TitleLabel("自动任务", self)
        self.addButton = ToolButton(FIF.ADD, self)
        self.addButton.clicked.connect(self._addTask)
        header.addWidget(self.backButton)
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.addButton)
        self.layout.addLayout(header)

        self.cardLayout = QVBoxLayout()
        self.cardLayout.setSpacing(10)
        self.layout.addLayout(self.cardLayout)
        self.emptyLabel = SubtitleLabel("还没有设置自动任务哦 ~", self.view)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emptyLabel.setStyleSheet("color: gray;")
        self.layout.addWidget(self.emptyLabel, 1, Qt.AlignmentFlag.AlignCenter)
        self.layout.addStretch(1)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self.saveTimer = QTimer(self)
        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(300)
        self.saveTimer.timeout.connect(self.flushPendingSave)
        self._savePending = False
        self._loadTasks()
        cfg.homeCardTasks.valueChanged.connect(self._onTasksChanged)

    def setHomeCards(self, entries):
        self._homeCards = _available_home_cards(entries or [])
        for card in self._cards:
            card.setHomeCards(self._homeCards)

    def _onTasksChanged(self, tasks):
        if tasks != self.currentTasks:
            self._loadTasks()

    def _loadTasks(self):
        self.saveTimer.stop()
        self._savePending = False
        while self.cardLayout.count():
            widget = self.cardLayout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        rawTasks = cfg.homeCardTasks.value
        tasks = normalize_home_card_tasks(rawTasks)
        self.currentTasks = deepcopy(tasks)
        if tasks != rawTasks:
            cfg.set(cfg.homeCardTasks, tasks)
        self._cards = []
        self.emptyLabel.setVisible(not self.currentTasks)
        for index, task in enumerate(self.currentTasks):
            card = HomeCardTaskCard(task, self._homeCards, self, self)
            card.deleteClicked.connect(self._removeTask)
            card.dataChanged.connect(
                lambda taskIndex=index, taskCard=card: self._updateTask(
                    taskIndex,
                    taskCard.data,
                )
            )
            self._cards.append(card)
            self.cardLayout.addWidget(card)

    def _addTask(self):
        self.flushPendingSave()
        dialog = AddHomeCardTaskDialog(self._homeCards, self.window())
        try:
            if not dialog.exec():
                return
            self.currentTasks.insert(0, dialog.getData())
            cfg.set(
                cfg.homeCardTasks,
                normalize_home_card_tasks(self.currentTasks),
            )
            self._loadTasks()
        finally:
            dialog.deleteLater()

    def _updateTask(self, index, data):
        if not 0 <= index < len(self.currentTasks):
            return
        self.currentTasks[index] = deepcopy(data)
        self._savePending = True
        self.saveTimer.start()

    def _removeTask(self, taskId):
        self.saveTimer.stop()
        self._savePending = False
        self.currentTasks = [
            task for task in self.currentTasks if task.get("id") != taskId
        ]
        cfg.set(cfg.homeCardTasks, self.currentTasks)
        self._loadTasks()

    def flushPendingSave(self):
        if not self._savePending:
            return
        self._savePending = False
        self.saveTimer.stop()
        tasks = normalize_home_card_tasks(self.currentTasks)
        self.currentTasks = deepcopy(tasks)
        cfg.set(cfg.homeCardTasks, tasks)

    def hideEvent(self, event):
        self.flushPendingSave()
        super().hideEvent(event)


__all__ = [
    "AddHomeCardTaskDialog",
    "HomeCardTaskCard",
    "HomeCardTaskPage",
    "create_home_card_task_form",
    "home_card_task_data",
]
