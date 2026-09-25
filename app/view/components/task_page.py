from copy import deepcopy

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    MessageBoxBase,
    PushButton,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import SettingMaterialCard
from app.view.components.task_picker import (
    TaskExpandSettingCard,
    TaskMasterSwitch,
    configureTaskExpandCard,
)


class ScheduledTaskDialog(MessageBoxBase):
    """New-task dialog: the task form in a scroll area, returning an enabled task."""

    def __init__(
        self,
        title,
        createForm,
        taskData,
        parent=None,
        maxHeight=280,
        minWidth=580,
    ):
        super().__init__(parent)
        self._taskData = taskData
        self.titleLabel = SubtitleLabel(title, self)
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.formWidget, self.formWidgets = createForm(self, self.scrollArea)
        self.scrollArea.setWidget(self.formWidget)
        self.scrollArea.setMinimumHeight(180)
        self.scrollArea.setMaximumHeight(maxHeight)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addWidget(self.scrollArea)
        self.widget.setMinimumWidth(minWidth)

    def getData(self):
        return {**self._taskData(self.formWidgets), "enabled": True}


class ScheduledTaskCard(SettingMaterialCard):
    """An existing task: header with enable switch, the form revealed below it.

    Subclasses set ICON and implement _createForm, _bindForm, _formData and
    _summary; whatever those read must be set before calling super().__init__.
    """

    ICON = FIF.HISTORY
    deleteClicked = Signal()
    dataChanged = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.expandCard = TaskExpandSettingCard(
            self.ICON,
            data["name"],
            self._summary(),
            self,
        )
        self.paintFilter = self.applyExpandCardMaterial(self.expandCard)
        self.expandBehavior = configureTaskExpandCard(self.expandCard)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.expandCard)

        self.enableSwitch = SwitchButton(self)
        self.enableSwitch.setChecked(data.get("enabled", True))
        self.enableSwitch.checkedChanged.connect(self._onEnabledChanged)
        self.expandCard.addWidget(self.enableSwitch)

        self.formWidget, self.formWidgets = self._createForm()
        self.formHeightTimer = QTimer(self)
        self.formHeightTimer.setSingleShot(True)
        self.formHeightTimer.setInterval(10)
        self.formHeightTimer.timeout.connect(self.expandCard._adjustViewSize)
        self._bindForm()

        deleteButton = PushButton(FIF.DELETE, "删除任务", self)
        deleteButton.clicked.connect(self.deleteClicked)
        buttonLayout = QHBoxLayout()
        buttonLayout.setContentsMargins(16, 0, 16, 0)
        for button in self._extraButtons():
            buttonLayout.addWidget(button)
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(deleteButton)

        container = QWidget(self)
        containerLayout = QVBoxLayout(container)
        containerLayout.setContentsMargins(0, 0, 0, 16)
        containerLayout.addWidget(self.formWidget)
        containerLayout.addSpacing(10)
        containerLayout.addLayout(buttonLayout)
        self.expandCard.viewLayout.addWidget(container)

    def _extraButtons(self):
        return ()

    def _onEnabledChanged(self, checked):
        if self.data.get("enabled", True) == checked:
            return
        self.data["enabled"] = checked
        self.dataChanged.emit()

    def _saveData(self, *args):
        updated = self._formData()
        changed = any(self.data.get(key) != value for key, value in updated.items())
        self.data.update(updated)
        self.expandCard.card.setTitle(self.data["name"])
        self.expandCard.card.setContent(self._summary())
        if changed:
            self.dataChanged.emit()

    def _refreshFormHeight(self, *args):
        self.expandCard._adjustViewSize()
        self.formHeightTimer.start()


class ScheduledTaskPage(QWidget):
    """A Scheduled Task list backed by one cfg list and its master switch.

    Edits are debounced into cfg; new tasks go to the front of the list.
    Subclasses implement _createCard and _createDialog; whatever those read
    must be set before calling super().__init__.
    """

    backSignal = Signal()

    def __init__(self, title, emptyText, tasksItem, enabledItem, parent=None):
        super().__init__(parent)
        self._tasksItem = tasksItem
        self._enabledItem = enabledItem
        self._cards = []
        self.currentTasks = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(30, 30, 30, 30)

        header = QHBoxLayout()
        self.backButton = ToolButton(FIF.RETURN, self)
        self.backButton.clicked.connect(self.backSignal.emit)
        self.titleLabel = TitleLabel(title, self)
        self.masterSwitch = TaskMasterSwitch(enabledItem, self)
        self.addButton = ToolButton(FIF.ADD, self)
        self.addButton.clicked.connect(self._addTask)
        header.addWidget(self.backButton)
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.masterSwitch)
        header.addSpacing(8)
        header.addWidget(self.addButton)
        self.layout.addLayout(header)

        self.scrollArea = ScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.view = QWidget(self.scrollArea)
        contentLayout = QVBoxLayout(self.view)
        contentLayout.setContentsMargins(0, 0, 0, 0)
        self.cardLayout = QVBoxLayout()
        self.cardLayout.setSpacing(10)
        contentLayout.addLayout(self.cardLayout)
        self.emptyLabel = SubtitleLabel(emptyText, self.view)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emptyLabel.setStyleSheet("color: gray;")
        contentLayout.addWidget(self.emptyLabel, 1, Qt.AlignmentFlag.AlignCenter)
        contentLayout.addStretch(1)
        self.scrollArea.setWidget(self.view)
        self.layout.addWidget(self.scrollArea, 1)

        self.saveTimer = QTimer(self)
        self.saveTimer.setSingleShot(True)
        self.saveTimer.setInterval(300)
        self.saveTimer.timeout.connect(self.flushPendingSave)
        self._savePending = False
        self._loadTasks()
        self._tasksItem.valueChanged.connect(self._onTasksChanged)
        self._enabledItem.valueChanged.connect(self._setTaskControlsEnabled)
        self._setTaskControlsEnabled(self._enabledItem.value)

    def _normalizeTasks(self, tasks):
        return tasks

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
        rawTasks = self._tasksItem.value
        tasks = self._normalizeTasks(rawTasks)
        self.currentTasks = deepcopy(tasks)
        if tasks != rawTasks:
            cfg.set(self._tasksItem, tasks)
        self._cards = []
        self.emptyLabel.setVisible(not self.currentTasks)
        for index, task in enumerate(self.currentTasks):
            card = self._createCard(task)
            card.deleteClicked.connect(
                lambda taskIndex=index: self._removeTask(taskIndex)
            )
            card.dataChanged.connect(
                lambda taskIndex=index, taskCard=card: self._updateTask(
                    taskIndex,
                    taskCard.data,
                )
            )
            card.setEnabled(self._enabledItem.value)
            self._cards.append(card)
            self.cardLayout.addWidget(card)

    def _setTaskControlsEnabled(self, enabled):
        self.addButton.setEnabled(enabled)
        for card in self._cards:
            card.setEnabled(enabled)

    def _addTask(self):
        self.flushPendingSave()
        dialog = self._createDialog()
        try:
            if dialog.exec():
                self.currentTasks.insert(0, dialog.getData())
                cfg.set(self._tasksItem, self._normalizeTasks(self.currentTasks))
                self._loadTasks()
        finally:
            dialog.deleteLater()

    def _updateTask(self, index, data):
        if not 0 <= index < len(self.currentTasks):
            return
        self.currentTasks[index] = deepcopy(data)
        self._savePending = True
        self.saveTimer.start()

    def _removeTask(self, index):
        self.saveTimer.stop()
        self._savePending = False
        del self.currentTasks[index]
        cfg.set(self._tasksItem, self.currentTasks)
        self._loadTasks()

    def flushPendingSave(self):
        if not self._savePending:
            return
        self._savePending = False
        self.saveTimer.stop()
        tasks = self._normalizeTasks(self.currentTasks)
        self.currentTasks = deepcopy(tasks)
        cfg.set(self._tasksItem, tasks)

    def hideEvent(self, event):
        self.flushPendingSave()
        super().hideEvent(event)
