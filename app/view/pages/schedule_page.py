import os
from copy import deepcopy

from PySide6.QtCore import Qt, QTime, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    ExpandSettingCard,
    LineEdit,
    MessageBoxBase,
    PickerColumnFormatter,
    PillPushButton,
    PushButton,
    SettingCard,
    Slider,
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


class SecondsFormatter(PickerColumnFormatter):
    def encode(self, value):
        return str(value) + "秒"

    def decode(self, value: str):
        return int(value[:-1])

class BroadcastSettingCard(SettingCard):
    def __init__(self, icon, title, content, widget, parent=None):
        super().__init__(icon, title, content, parent)
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


def create_task_form(parent_widget, initial_data=None):
    form = QWidget(parent_widget)
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)

    default_time = QTime.currentTime()
    data = initial_data or {
        "name": "", "time": default_time.toString("HH:mm:ss"),
        "weeks": [0,1,2,3,4,5,6], "type": "预设: 12:30报时",
        "content": "", "file": "", "repeat": 3
    }

    widgets = {}

    nameInput = LineEdit(form)
    nameInput.setText(data["name"])
    nameInput.setPlaceholderText("任务名称 (例如: 中午报时)")
    layout.addWidget(BroadcastSettingCard(FIF.EDIT, "任务名称", "设置该播报任务的标题", nameInput, form))
    widgets['nameInput'] = nameInput

    timePicker = TimePicker(form, showSeconds=True)
    timePicker.setColumnFormatter(2, SecondsFormatter())
    timePicker.setTime(QTime.fromString(data["time"], "HH:mm:ss") if data["time"] else default_time)
    layout.addWidget(BroadcastSettingCard(FIF.ALBUM, "播报时间", "设置触发的具体时间(时:分:秒)", timePicker, form))
    widgets['timePicker'] = timePicker

    weekWidget = QWidget()
    weekLayout = QHBoxLayout(weekWidget)
    weekLayout.setContentsMargins(0, 0, 0, 0)
    weekBtns = []
    for i, d in enumerate(["一", "二", "三", "四", "五", "六", "日"]):
        btn = PillPushButton(d, weekWidget)
        btn.setCheckable(True)
        btn.setChecked(i in data["weeks"])
        weekBtns.append(btn)
        weekLayout.addWidget(btn)
    layout.addWidget(BroadcastSettingCard(FIF.CALENDAR, "重复频率", "选择在一周中的哪几天执行", weekWidget, form))
    widgets['weekBtns'] = weekBtns

    typeCombo = ComboBox(form)
    typeCombo.addItems(["预设: 12:30报时", "预设: 18:25报时", "预设: 上课铃", "系统TTS", "本地音频"])
    typeCombo.setCurrentText(data["type"])
    typeCombo.setFixedWidth(200)
    layout.addWidget(BroadcastSettingCard(FIF.MUSIC, "播报类型", "选择音频来源或语音合成", typeCombo, form))
    widgets['typeCombo'] = typeCombo

    ttsInput = LineEdit(form)
    ttsInput.setText(data["content"])
    ttsInput.setPlaceholderText("输入语音合成的文字内容")
    ttsCard = BroadcastSettingCard(FIF.CHAT, "TTS内容", "输入要被朗读的文本", ttsInput, form)
    layout.addWidget(ttsCard)
    widgets['ttsInput'] = ttsInput

    fileBtn = PushButton("选择文件" if not data["file"] else os.path.basename(data["file"]), form)
    fileCard = BroadcastSettingCard(FIF.FOLDER, "音频文件", "选择本地 mp3/wav 文件", fileBtn, form)
    layout.addWidget(fileCard)
    widgets['fileBtn'] = fileBtn
    widgets['filePath'] = data["file"]

    def _selectFile():
        p, _ = QFileDialog.getOpenFileName(form, "选择音频", "", "Audio (*.mp3 *.wav)")
        if p:
            widgets['filePath'] = p
            fileBtn.setText(os.path.basename(p))
    fileBtn.clicked.connect(_selectFile)

    repeatSpin = SpinBox(form)
    repeatSpin.setRange(1, 10)
    repeatSpin.setValue(data["repeat"])
    layout.addWidget(BroadcastSettingCard(FIF.SYNC, "重复播放", "播报执行的次数", repeatSpin, form))
    widgets['repeatSpin'] = repeatSpin

    volumeSlider = Slider(Qt.Orientation.Horizontal, form)
    volumeSlider.setRange(0, 100)
    volumeSlider.setValue(data.get("volume", 100))
    volumeSlider.setFixedWidth(170)
    layout.addWidget(BroadcastSettingCard(FIF.VOLUME, "播报音量", "设置当前任务的播放音量", volumeSlider, form))
    widgets['volumeSlider'] = volumeSlider

    def _updateVisibility(text):
        ttsCard.setVisible("TTS" in text)
        fileCard.setVisible(text == "本地音频")
    typeCombo.currentTextChanged.connect(_updateVisibility)
    _updateVisibility(typeCombo.currentText())

    return form, widgets


class AddTaskDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("添加播报任务", self)

        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setStyleSheet("QScrollArea { border: none; background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")

        self.formWidget, self.formWidgets = create_task_form(self)
        self.scrollArea.setWidget(self.formWidget)

        self.scrollArea.setMinimumHeight(180)
        self.scrollArea.setMaximumHeight(280)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(10)
        self.viewLayout.addWidget(self.scrollArea)
        self.widget.setMinimumWidth(580)

    def get_data(self):
        w = self.formWidgets
        return {
            "name": w['nameInput'].text() or "未命名任务",
            "time": w['timePicker'].getTime().toString("HH:mm:ss"),
            "weeks": [i for i, b in enumerate(w['weekBtns']) if b.isChecked()],
            "type": w['typeCombo'].currentText(),
            "content": w['ttsInput'].text(),
            "file": w['filePath'],
            "repeat": w['repeatSpin'].value(),
            "volume": w['volumeSlider'].value(),
            "enabled": True
        }


class TaskCard(CardWidget):
    deleteClicked = Signal(dict)
    dataChanged = Signal()

    def __init__(self, data, parent=None):
        super().__init__(parent)
        self.data = data
        self.expandCard = ExpandSettingCard(
            FIF.MEGAPHONE,
            data["name"],
            f"触发时间: {data['time']}",
            self,
        )
        self.paintFilter = CardPaintFilter(self)
        self.expandCard.card.installEventFilter(self.paintFilter)
        self.expandCard.borderWidget.installEventFilter(self.paintFilter)

        self.cardLayout = QVBoxLayout(self)
        self.cardLayout.setContentsMargins(0, 0, 0, 0)
        self.cardLayout.addWidget(self.expandCard)

        self._target_title_label = None
        self._target_content_label = None
        for lbl in self.findChildren(QLabel):
            if lbl.text() == data["name"]:
                self._target_title_label = lbl
            elif lbl.text() == f"触发时间: {data['time']}":
                self._target_content_label = lbl

        self.switchBtn = SwitchButton(self)
        self.switchBtn.setChecked(data["enabled"])
        self.switchBtn.checkedChanged.connect(self._onEnableChanged)
        self.expandCard.addWidget(self.switchBtn)

        self.formWidget, self.formWidgets = create_task_form(self, data)

        self.formWidgets['nameInput'].textChanged.connect(self._saveData)
        self.formWidgets['timePicker'].timeChanged.connect(self._saveData)
        for btn in self.formWidgets['weekBtns']: btn.clicked.connect(self._saveData)
        self.formWidgets['typeCombo'].currentTextChanged.connect(self._saveData)
        # 立即刷新发起布局请求，延迟刷新再读取最终高度。
        self.formWidgets['typeCombo'].currentTextChanged.connect(
            lambda: QTimer.singleShot(1, self.expandCard._adjustViewSize)
        )
        self.formWidgets['typeCombo'].currentTextChanged.connect(
            self.expandCard._adjustViewSize
        )
        self.formWidgets['ttsInput'].textChanged.connect(self._saveData)
        self.formWidgets['repeatSpin'].valueChanged.connect(self._saveData)
        self.formWidgets['volumeSlider'].valueChanged.connect(self._saveData)

        self.formWidgets['fileBtn'].clicked.disconnect()
        def _new_select():
            p, _ = QFileDialog.getOpenFileName(self, "选择音频", "", "Audio (*.mp3 *.wav)")
            if p:
                self.formWidgets['filePath'] = p
                self.formWidgets['fileBtn'].setText(os.path.basename(p))
                self._saveData()
        self.formWidgets['fileBtn'].clicked.connect(_new_select)

        btnLayout = QHBoxLayout()
        self.playBtn = PushButton(FIF.PLAY, "试听配置", self)
        self.playBtn.clicked.connect(self._playTest)
        self.delBtn = PushButton(FIF.DELETE, "删除任务", self)
        self.delBtn.clicked.connect(lambda: self.deleteClicked.emit(self.data))

        btnLayout.addWidget(self.playBtn)
        btnLayout.addStretch(1)
        btnLayout.addWidget(self.delBtn)

        containerLayout = QVBoxLayout()
        containerLayout.setContentsMargins(48, 10, 16, 16)
        containerLayout.addWidget(self.formWidget)
        containerLayout.addSpacing(10)
        containerLayout.addLayout(btnLayout)

        container = QWidget()
        container.setLayout(containerLayout)
        self.expandCard.viewLayout.addWidget(container)

    def _onEnableChanged(self, checked):
        self.data["enabled"] = checked
        self._saveData()

    def _saveData(self, *args):
        w = self.formWidgets
        self.data.update({
            "name": w['nameInput'].text() or "未命名任务",
            "time": w['timePicker'].getTime().toString("HH:mm:ss"),
            "weeks": [i for i, b in enumerate(w['weekBtns']) if b.isChecked()],
            "type": w['typeCombo'].currentText(),
            "content": w['ttsInput'].text(),
            "file": w['filePath'],
            "repeat": w['repeatSpin'].value(),
            "volume": w['volumeSlider'].value()
        })

        if self._target_title_label: self._target_title_label.setText(self.data["name"])
        if self._target_content_label: self._target_content_label.setText(f"触发时间: {self.data['time']}")

        self.dataChanged.emit()

    def _playTest(self):
        from app.signal_bus import signalBus
        signalBus.testAudio.emit(self.data)


class SchedulePage(ScrollArea):
    backSignal = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QWidget()
        self.layout = QVBoxLayout(self.view)
        self.layout.setContentsMargins(30, 30, 30, 30)

        header = QHBoxLayout()
        self.backBtn = ToolButton(FIF.RETURN, self)
        self.backBtn.clicked.connect(self.backSignal.emit)
        self.title = TitleLabel("定时播报", self)
        self.addBtn = ToolButton(FIF.ADD, self)
        self.addBtn.clicked.connect(self._addTask)

        header.addWidget(self.backBtn)
        header.addWidget(self.title)
        header.addStretch(1)
        header.addWidget(self.addBtn)
        self.layout.addLayout(header)

        self.cardLayout = QVBoxLayout()
        self.cardLayout.setSpacing(10)
        self.layout.addLayout(self.cardLayout)

        self.emptyLabel = SubtitleLabel("还没有设置播报任务哦 ~", self.view)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emptyLabel.setStyleSheet("color: gray;")
        self.layout.addWidget(self.emptyLabel, 1, Qt.AlignmentFlag.AlignCenter)

        self.layout.addStretch(1)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.enableTransparentBackground()

        self._loadTasks()
        cfg.broadcastTasks.valueChanged.connect(self._onTasksChanged)

    def _onTasksChanged(self, tasks):
        if tasks != self.current_tasks:
            self._loadTasks()

    def _loadTasks(self):
        while self.cardLayout.count():
            w = self.cardLayout.takeAt(0).widget()
            if w: w.deleteLater()

        self.current_tasks = deepcopy(cfg.broadcastTasks.value)

        if not self.current_tasks:
            self.emptyLabel.show()
        else:
            self.emptyLabel.hide()
            for i, task in enumerate(self.current_tasks):
                card = TaskCard(task, self)
                card.deleteClicked.connect(self._removeTask)
                card.dataChanged.connect(lambda idx=i, c=card: self._updateTask(idx, c.data))
                self.cardLayout.addWidget(card)

    def _updateTask(self, index, updated_data):
        self.current_tasks[index] = updated_data
        cfg.set(cfg.broadcastTasks, self.current_tasks)

    def _addTask(self):
        w = AddTaskDialog(self.window())
        if w.exec():
            data = w.get_data()
            self.current_tasks.append(data)
            cfg.set(cfg.broadcastTasks, self.current_tasks)
            self._loadTasks()

    def _removeTask(self, data):
        self.current_tasks.remove(data)
        cfg.set(cfg.broadcastTasks, self.current_tasks)
        self._loadTasks()
