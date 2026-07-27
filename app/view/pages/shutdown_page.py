from copy import deepcopy

from PySide6.QtCore import QRect, Qt, QTime, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ExpandSettingCard,
    LineEdit,
    MessageBoxBase,
    PickerColumnFormatter,
    PillPushButton,
    PushButton,
    SettingCard,
    SpinBox,
    SubtitleLabel,
    SwitchButton,
    TimePicker,
    TitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import CardPaintFilter

DEFAULT_PROMPT_TITLE = "Windows 即将关闭你的计算机"
DEFAULT_PROMPT_MESSAGE = (
    "若还有未进行的操作，可选择“等我1分钟”，"
    "则该弹窗1分钟后将再次提醒。"
)
WAIT_RESULT = 0
SHUTDOWN_RESULT = 1
SKIP_RESULT = 2


class SecondsFormatter(PickerColumnFormatter):
    def encode(self, value):
        return str(value) + "秒"

    def decode(self, value: str):
        return int(value[:-1])


class ShutdownSettingCard(SettingCard):
    def __init__(self, icon, title, content, widget, parent=None):
        super().__init__(icon, title, content, parent)
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


def create_shutdown_form(parent, initialData=None):
    form = QWidget(parent)
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)

    now = QTime.currentTime()
    data = initialData or {
        "name": "",
        "time": now.toString("HH:mm:ss"),
        "weeks": [0, 1, 2, 3, 4, 5, 6],
        "notify": True,
        "promptTitle": DEFAULT_PROMPT_TITLE,
        "promptMessage": DEFAULT_PROMPT_MESSAGE,
        "allowSkip": True,
        "waitSeconds": 30,
    }
    widgets = {}

    nameInput = LineEdit(form)
    nameInput.setText(data.get("name", ""))
    nameInput.setPlaceholderText("任务名称（例如：每日关机）")
    layout.addWidget(
        ShutdownSettingCard(
            FIF.EDIT,
            "任务名称",
            "设置该关机任务的标题",
            nameInput,
            form,
        )
    )
    widgets["nameInput"] = nameInput

    timePicker = TimePicker(form, showSeconds=True)
    timePicker.setColumnFormatter(2, SecondsFormatter())
    taskTime = QTime.fromString(data.get("time", ""), "HH:mm:ss")
    timePicker.setTime(taskTime if taskTime.isValid() else now)
    layout.addWidget(
        ShutdownSettingCard(
            FIF.ALBUM,
            "关机时间",
            "设置触发关机任务的时间",
            timePicker,
            form,
        )
    )
    widgets["timePicker"] = timePicker

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
    layout.addWidget(
        ShutdownSettingCard(
            FIF.CALENDAR,
            "重复频率",
            "选择在一周中的哪几天执行",
            weekWidget,
            form,
        )
    )
    widgets["weekButtons"] = weekButtons

    notifySwitch = SwitchButton(form)
    notifySwitch.setChecked(data.get("notify", True))
    layout.addWidget(
        ShutdownSettingCard(
            FIF.INFO,
            "提示关机",
            "到时间后先显示关机提醒",
            notifySwitch,
            form,
        )
    )
    widgets["notifySwitch"] = notifySwitch

    titleInput = LineEdit(form)
    titleInput.setText(data.get("promptTitle", DEFAULT_PROMPT_TITLE))
    titleInput.setPlaceholderText(DEFAULT_PROMPT_TITLE)
    titleCard = ShutdownSettingCard(
        FIF.FONT,
        "提示大标题",
        "设置关机提醒的大标题",
        titleInput,
        form,
    )
    layout.addWidget(titleCard)
    widgets["titleInput"] = titleInput

    messageInput = LineEdit(form)
    messageInput.setText(data.get("promptMessage", DEFAULT_PROMPT_MESSAGE))
    messageInput.setPlaceholderText(DEFAULT_PROMPT_MESSAGE)
    messageCard = ShutdownSettingCard(
        FIF.MESSAGE,
        "提示正文",
        "设置关机提醒的正文",
        messageInput,
        form,
    )
    layout.addWidget(messageCard)
    widgets["messageInput"] = messageInput

    skipSwitch = SwitchButton(form)
    skipSwitch.setChecked(data.get("allowSkip", True))
    skipCard = ShutdownSettingCard(
        FIF.CANCEL,
        "本次不关机",
        "在提醒中显示“本次不关机”按钮",
        skipSwitch,
        form,
    )
    layout.addWidget(skipCard)
    widgets["skipSwitch"] = skipSwitch

    waitSpin = SpinBox(form)
    waitSpin.setRange(5, 300)
    waitSpin.setSuffix(" 秒")
    waitSpin.setValue(data.get("waitSeconds", 30))
    waitCard = ShutdownSettingCard(
        FIF.STOP_WATCH,
        "等待操作时间",
        "无操作时自动关机前等待的时间",
        waitSpin,
        form,
    )
    layout.addWidget(waitCard)
    widgets["waitSpin"] = waitSpin

    conditionalCards = (titleCard, messageCard, skipCard, waitCard)

    def updateVisibility(checked):
        for card in conditionalCards:
            card.setVisible(checked)

    notifySwitch.checkedChanged.connect(updateVisibility)
    updateVisibility(notifySwitch.isChecked())
    return form, widgets


def shutdown_task_data(widgets):
    return {
        "name": widgets["nameInput"].text() or "未命名任务",
        "time": widgets["timePicker"].getTime().toString("HH:mm:ss"),
        "weeks": [
            index
            for index, button in enumerate(widgets["weekButtons"])
            if button.isChecked()
        ],
        "notify": widgets["notifySwitch"].isChecked(),
        "promptTitle": widgets["titleInput"].text() or DEFAULT_PROMPT_TITLE,
        "promptMessage": (
            widgets["messageInput"].text() or DEFAULT_PROMPT_MESSAGE
        ),
        "allowSkip": widgets["skipSwitch"].isChecked(),
        "waitSeconds": widgets["waitSpin"].value(),
    }


class AddShutdownTaskDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("添加关机任务", self)
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.formWidget, self.formWidgets = create_shutdown_form(self)
        self.scrollArea.setWidget(self.formWidget)
        self.scrollArea.setMinimumHeight(180)
        self.scrollArea.setMaximumHeight(280)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addWidget(self.scrollArea)
        self.widget.setMinimumWidth(580)

    def get_data(self):
        return {**shutdown_task_data(self.formWidgets), "enabled": True}


class ShutdownTaskCard(CardWidget):
    deleteClicked = Signal(dict)
    dataChanged = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        name = data.get("name") or "未命名任务"
        time = data.get("time") or "00:00:00"
        self.data.update({"name": name, "time": time})
        self.expandCard = ExpandSettingCard(
            FIF.POWER_BUTTON,
            name,
            f"关机时间：{time}",
            self,
        )
        self.paintFilter = CardPaintFilter(self)
        self.expandCard.card.installEventFilter(self.paintFilter)
        self.expandCard.borderWidget.installEventFilter(self.paintFilter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.expandCard)

        self.titleLabel = None
        self.timeLabel = None
        for label in self.findChildren(QLabel):
            if label.text() == name:
                self.titleLabel = label
            elif label.text() == f"关机时间：{time}":
                self.timeLabel = label

        self.enableSwitch = SwitchButton(self)
        self.enableSwitch.setChecked(data.get("enabled", True))
        self.enableSwitch.checkedChanged.connect(self._onEnabledChanged)
        self.expandCard.addWidget(self.enableSwitch)

        self.formWidget, self.formWidgets = create_shutdown_form(self, data)
        self._bindForm()

        deleteButton = PushButton(FIF.DELETE, "删除任务", self)
        deleteButton.clicked.connect(lambda: self.deleteClicked.emit(self.data))
        buttonLayout = QHBoxLayout()
        buttonLayout.addStretch(1)
        buttonLayout.addWidget(deleteButton)

        containerLayout = QVBoxLayout()
        containerLayout.setContentsMargins(48, 10, 16, 16)
        containerLayout.addWidget(self.formWidget)
        containerLayout.addSpacing(10)
        containerLayout.addLayout(buttonLayout)

        container = QWidget(self)
        container.setLayout(containerLayout)
        self.expandCard.viewLayout.addWidget(container)

    def _bindForm(self):
        widgets = self.formWidgets
        widgets["nameInput"].textChanged.connect(self._saveData)
        widgets["timePicker"].timeChanged.connect(self._saveData)
        for button in widgets["weekButtons"]:
            button.clicked.connect(self._saveData)
        widgets["notifySwitch"].checkedChanged.connect(self._saveData)
        widgets["notifySwitch"].checkedChanged.connect(
            self._refreshFormHeight
        )
        widgets["titleInput"].textChanged.connect(self._saveData)
        widgets["messageInput"].textChanged.connect(self._saveData)
        widgets["skipSwitch"].checkedChanged.connect(self._saveData)
        widgets["waitSpin"].valueChanged.connect(self._saveData)

    def _refreshFormHeight(self):
        # Qt 会延迟处理显隐布局，第二次刷新读取最终高度。
        QTimer.singleShot(10, self.expandCard._adjustViewSize)
        self.expandCard._adjustViewSize()

    def _onEnabledChanged(self, checked):
        self.data["enabled"] = checked
        self._saveData()

    def _saveData(self, *args):
        self.data.update(shutdown_task_data(self.formWidgets))
        if self.titleLabel:
            self.titleLabel.setText(self.data["name"])
        if self.timeLabel:
            self.timeLabel.setText(f"关机时间：{self.data['time']}")
        self.dataChanged.emit()


class ShutdownPage(ScrollArea):
    backSignal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget()
        self.layout = QVBoxLayout(self.view)
        self.layout.setContentsMargins(30, 30, 30, 30)

        header = QHBoxLayout()
        self.backButton = ToolButton(FIF.RETURN, self)
        self.backButton.clicked.connect(self.backSignal.emit)
        self.titleLabel = TitleLabel("定时关机", self)
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

        self.emptyLabel = SubtitleLabel("还没有设置关机任务哦 ~", self.view)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emptyLabel.setStyleSheet("color: gray;")
        self.layout.addWidget(
            self.emptyLabel,
            1,
            Qt.AlignmentFlag.AlignCenter,
        )
        self.layout.addStretch(1)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()
        self._loadTasks()
        cfg.shutdownTasks.valueChanged.connect(self._onTasksChanged)

    def _onTasksChanged(self, tasks):
        if tasks != self.current_tasks:
            self._loadTasks()

    def _loadTasks(self):
        while self.cardLayout.count():
            widget = self.cardLayout.takeAt(0).widget()
            if widget:
                widget.deleteLater()

        self.current_tasks = deepcopy(cfg.shutdownTasks.value)
        self.emptyLabel.setVisible(not self.current_tasks)
        for index, task in enumerate(self.current_tasks):
            card = ShutdownTaskCard(task, self)
            card.deleteClicked.connect(self._removeTask)
            card.dataChanged.connect(
                lambda taskIndex=index, taskCard=card: self._updateTask(
                    taskIndex,
                    taskCard.data,
                )
            )
            self.cardLayout.addWidget(card)

    def _addTask(self):
        dialog = AddShutdownTaskDialog(self.window())
        if dialog.exec():
            self.current_tasks.append(dialog.get_data())
            cfg.set(cfg.shutdownTasks, self.current_tasks)
            self._loadTasks()

    def _updateTask(self, index, data):
        self.current_tasks[index] = data
        cfg.set(cfg.shutdownTasks, self.current_tasks)

    def _removeTask(self, data):
        self.current_tasks.remove(data)
        cfg.set(cfg.shutdownTasks, self.current_tasks)
        self._loadTasks()


class ShutdownPromptDialog(MessageBoxBase):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.remaining_seconds = max(1, int(task.get("waitSeconds", 30)))
        self.titleLabel = TitleLabel(
            task.get("promptTitle") or DEFAULT_PROMPT_TITLE,
            self,
        )
        self.messageLabel = BodyLabel(
            task.get("promptMessage") or DEFAULT_PROMPT_MESSAGE,
            self,
        )
        self.messageLabel.setWordWrap(True)
        self.countdownLabel = BodyLabel(self.buttonGroup)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(8)
        self.viewLayout.addWidget(self.messageLabel)
        self.widget.setMinimumWidth(720)

        self.yesButton.setText("立即关机")
        self.cancelButton.setText("等我 1 分钟")
        self.buttonLayout.removeWidget(self.yesButton)
        self.buttonLayout.removeWidget(self.cancelButton)
        self.buttonLayout.addWidget(self.countdownLabel, 1)
        self.buttonLayout.addWidget(self.cancelButton)

        self.skipButton = None
        if task.get("allowSkip", True):
            self.skipButton = PushButton("本次不关机", self.buttonGroup)
            self.skipButton.clicked.connect(lambda: self.done(SKIP_RESULT))
            self.buttonLayout.addWidget(self.skipButton)
        self.buttonLayout.addWidget(self.yesButton)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._onTimeout)
        self.finished.connect(self.timer.stop)
        self._updateCountdown()
        self.timer.start()

    def _updateCountdown(self):
        self.countdownLabel.setText(
            f"{self.remaining_seconds} 秒后将自动关机"
        )

    def _onTimeout(self):
        self.remaining_seconds -= 1
        if self.remaining_seconds <= 0:
            self.timer.stop()
            self.accept()
            return
        self._updateCountdown()


def show_shutdown_prompt(task):
    overlay = QWidget()
    overlay.setWindowFlags(
        Qt.WindowType.Tool
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
    )
    overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    geometry = QRect()
    for screen in QApplication.screens():
        geometry = geometry.united(screen.geometry())
    overlay.setGeometry(geometry)
    overlay.show()
    overlay.raise_()
    overlay.activateWindow()

    dialog = ShutdownPromptDialog(task, overlay)
    result = dialog.exec()
    overlay.close()
    return result
