from PySide6.QtCore import QRect, Qt, QTime, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    LineEdit,
    MessageBoxBase,
    PillPushButton,
    PushButton,
    SpinBox,
    SwitchButton,
    TitleLabel,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.view.components.task_page import (
    ScheduledTaskCard,
    ScheduledTaskDialog,
    ScheduledTaskPage,
)
from app.view.components.task_picker import (
    SecondsFormatter,
    TaskFormSettingCard,
    TouchTimePicker,
)

DEFAULT_PROMPT_TITLE = "Windows 即将关闭你的计算机"
DEFAULT_PROMPT_MESSAGE = (
    "若还有未进行的操作，可选择“等我1分钟”，"
    "则该弹窗1分钟后将再次提醒。"
)
WAIT_RESULT = 0
SHUTDOWN_RESULT = 1
SKIP_RESULT = 2


def createShutdownForm(parent, initialData=None):
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
        TaskFormSettingCard(
            FIF.EDIT,
            "任务名称",
            "设置该关机任务的标题",
            nameInput,
            form,
        )
    )
    widgets["nameInput"] = nameInput

    timePicker = TouchTimePicker(form, showSeconds=True)
    timePicker.setColumnFormatter(2, SecondsFormatter())
    taskTime = QTime.fromString(data.get("time", ""), "HH:mm:ss")
    timePicker.setTime(taskTime if taskTime.isValid() else now)
    layout.addWidget(
        TaskFormSettingCard(
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
        TaskFormSettingCard(
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
        TaskFormSettingCard(
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
    titleCard = TaskFormSettingCard(
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
    messageCard = TaskFormSettingCard(
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
    skipCard = TaskFormSettingCard(
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
    waitCard = TaskFormSettingCard(
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


def shutdownTaskData(widgets):
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


class AddShutdownTaskDialog(ScheduledTaskDialog):
    def __init__(self, parent=None):
        super().__init__(
            "添加关机任务",
            lambda form, _scrollArea: createShutdownForm(form),
            shutdownTaskData,
            parent,
        )


class ShutdownTaskCard(ScheduledTaskCard):
    ICON = FIF.POWER_BUTTON

    def __init__(self, data, parent=None):
        data["name"] = data.get("name") or "未命名任务"
        data["time"] = data.get("time") or "00:00:00"
        super().__init__(data, parent)

    def _createForm(self):
        return createShutdownForm(self, self.data)

    def _bindForm(self):
        widgets = self.formWidgets
        widgets["nameInput"].textChanged.connect(self._saveData)
        widgets["timePicker"].timeChanged.connect(self._saveData)
        for button in widgets["weekButtons"]:
            button.clicked.connect(self._saveData)
        widgets["notifySwitch"].checkedChanged.connect(self._saveData)
        widgets["notifySwitch"].checkedChanged.connect(self._refreshFormHeight)
        widgets["titleInput"].textChanged.connect(self._saveData)
        widgets["messageInput"].textChanged.connect(self._saveData)
        widgets["skipSwitch"].checkedChanged.connect(self._saveData)
        widgets["waitSpin"].valueChanged.connect(self._saveData)

    def _formData(self):
        return shutdownTaskData(self.formWidgets)

    def _summary(self):
        return f"关机时间：{self.data['time']}"


class ShutdownPage(ScheduledTaskPage):
    def __init__(self, parent=None):
        super().__init__(
            "定时关机",
            "还没有设置关机任务哦 ~",
            cfg.shutdownTasks,
            cfg.shutdownTasksEnabled,
            parent,
        )

    def _createCard(self, task):
        return ShutdownTaskCard(task, self.view)

    def _createDialog(self):
        return AddShutdownTaskDialog(self.window())


class ShutdownPromptDialog(MessageBoxBase):
    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.setMaskColor(QColor(0, 0, 0, 180))
        self.remainingSeconds = max(1, int(task.get("waitSeconds", 30)))
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
        self.buttonLayout.addWidget(self.yesButton)
        self.buttonLayout.addWidget(self.cancelButton)

        self.skipButton = None
        if task.get("allowSkip", True):
            self.skipButton = PushButton("本次不关机", self.buttonGroup)
            self.skipButton.clicked.connect(lambda: self.done(SKIP_RESULT))
            self.buttonLayout.addWidget(self.skipButton)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._onTimeout)
        self.finished.connect(self.timer.stop)
        self._updateCountdown()
        self.timer.start()

    def _updateCountdown(self):
        self.countdownLabel.setText(
            f"{self.remainingSeconds} 秒后将自动关机"
        )

    def _onTimeout(self):
        self.remainingSeconds -= 1
        if self.remainingSeconds <= 0:
            self.timer.stop()
            self.accept()
            return
        self._updateCountdown()


def showShutdownPrompt(task):
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

    dialog = None
    try:
        dialog = ShutdownPromptDialog(task, overlay)
        return dialog.exec()
    finally:
        if dialog is not None:
            dialog.deleteLater()
        overlay.close()
        overlay.deleteLater()
