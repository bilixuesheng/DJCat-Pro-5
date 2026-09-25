import os
import threading
import weakref
from typing import ClassVar

from PySide6.QtCore import QObject, Qt, QTime, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PillPushButton,
    PushButton,
    Slider,
    SpinBox,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.edge_tts import DEFAULT_EDGE_VOICE, loadChineseVoices
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


class ChineseVoiceLoader(QObject):
    finished = Signal(list, str)
    _lock: ClassVar = threading.Lock()
    _loading: ClassVar = False
    _cachedVoices: ClassVar = None
    _waiters: ClassVar = []

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._waiting = False

    def start(self):
        with self._lock:
            if self._cachedVoices is not None:
                voices = list(self._cachedVoices)
            else:
                voices = None
                if not self._waiting:
                    self._waiters.append(weakref.ref(self))
                    self._waiting = True
                if self._loading:
                    return
                type(self)._loading = True

        if voices is not None:
            QTimer.singleShot(0, lambda: self._emit(voices, ""))
            return
        self._thread = threading.Thread(
            target=type(self)._loadShared,
            daemon=True,
            name="djcat-edge-voices",
        )
        self._thread.start()

    @classmethod
    def _loadShared(cls):
        voices, error = cls._fetch()
        with cls._lock:
            if not error:
                cls._cachedVoices = list(voices)
            waiters = cls._waiters
            cls._waiters = []
            cls._loading = False
        for reference in waiters:
            loader = reference()
            if loader is not None:
                loader._emit(voices, error)

    @staticmethod
    def _fetch():
        try:
            return loadChineseVoices(), ""
        except Exception as exception:
            return [], str(exception)

    def _emit(self, voices, error):
        self._waiting = False
        try:
            self.finished.emit(voices, error)
        except RuntimeError:
            pass

    def _load(self):
        self._emit(*self._fetch())


def create_task_form(parent_widget, initial_data=None):
    form = QWidget(parent_widget)
    layout = QVBoxLayout(form)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)

    default_time = QTime.currentTime()
    data = initial_data or {
        "name": "", "time": default_time.toString("HH:mm:ss"),
        "weeks": [0,1,2,3,4,5,6], "type": "预设: 12:30报时",
        "content": "", "file": "", "repeat": 3,
        "voice": DEFAULT_EDGE_VOICE,
    }

    widgets = {}

    nameInput = LineEdit(form)
    nameInput.setText(data["name"])
    nameInput.setPlaceholderText("任务名称 (例如: 中午报时)")
    layout.addWidget(TaskFormSettingCard(FIF.EDIT, "任务名称", "设置该播报任务的标题", nameInput, form))
    widgets['nameInput'] = nameInput

    timePicker = TouchTimePicker(form, showSeconds=True)
    timePicker.setColumnFormatter(2, SecondsFormatter())
    timePicker.setTime(QTime.fromString(data["time"], "HH:mm:ss") if data["time"] else default_time)
    layout.addWidget(TaskFormSettingCard(FIF.ALBUM, "播报时间", "设置触发的具体时间(时:分:秒)", timePicker, form))
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
    layout.addWidget(TaskFormSettingCard(FIF.CALENDAR, "重复频率", "选择在一周中的哪几天执行", weekWidget, form))
    widgets['weekBtns'] = weekBtns

    typeCombo = ComboBox(form)
    typeCombo.addItems([
        "预设: 12:30报时",
        "预设: 18:25报时",
        "预设: 上课铃",
        "系统TTS",
        "Edge TTS（需要联网）",
        "本地音频",
    ])
    typeCombo.setCurrentText(data["type"])
    typeCombo.setFixedWidth(200)
    layout.addWidget(TaskFormSettingCard(FIF.MUSIC, "播报类型", "选择音频来源或语音合成", typeCombo, form))
    widgets['typeCombo'] = typeCombo

    ttsInput = LineEdit(form)
    ttsInput.setText(data["content"])
    ttsInput.setPlaceholderText("输入语音合成的文字内容")
    ttsCard = TaskFormSettingCard(FIF.CHAT, "TTS内容", "输入要被朗读的文本", ttsInput, form)
    layout.addWidget(ttsCard)
    widgets['ttsInput'] = ttsInput

    voiceCombo = ComboBox(form)
    voiceCombo.setFixedWidth(260)
    voiceCombo.addItem(
        "晓晓（普通话 · 女声，默认）",
        userData=data.get("voice", DEFAULT_EDGE_VOICE),
    )
    voiceCard = TaskFormSettingCard(
        FIF.PEOPLE,
        "Edge TTS 音色",
        "仅显示中文音色；加载音色和语音播报均需要联网",
        voiceCombo,
        form,
    )
    layout.addWidget(voiceCard)
    widgets['voiceCombo'] = voiceCombo
    widgets['voiceCard'] = voiceCard

    fileBtn = PushButton("选择文件" if not data["file"] else os.path.basename(data["file"]), form)
    fileCard = TaskFormSettingCard(FIF.FOLDER, "音频文件", "选择本地 mp3/wav 文件", fileBtn, form)
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
    layout.addWidget(TaskFormSettingCard(FIF.SYNC, "重复播放", "播报执行的次数", repeatSpin, form))
    widgets['repeatSpin'] = repeatSpin

    volumeSlider = Slider(Qt.Orientation.Horizontal, form)
    volumeSlider.setRange(0, 100)
    volumeSlider.setValue(data.get("volume", 100))
    volumeSlider.setFixedWidth(170)
    volumeLabel = QLabel(str(volumeSlider.value()), form)
    volumeLabel.setFixedWidth(24)
    volumeLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    volumeSlider.valueChanged.connect(volumeLabel.setNum)

    volumeWidget = QWidget(form)
    volumeLayout = QHBoxLayout(volumeWidget)
    volumeLayout.setContentsMargins(0, 0, 0, 0)
    volumeLayout.setSpacing(8)
    volumeLayout.addWidget(volumeSlider)
    volumeLayout.addWidget(volumeLabel)

    layout.addWidget(TaskFormSettingCard(FIF.VOLUME, "播报音量", "设置当前任务的播放音量", volumeWidget, form))
    widgets['volumeSlider'] = volumeSlider

    voiceLoader = ChineseVoiceLoader(form)
    widgets['voiceLoader'] = voiceLoader
    widgets['voicesLoaded'] = False

    def _onVoicesLoaded(voices, error):
        selected_voice = voiceCombo.currentData() or data.get(
            "voice", DEFAULT_EDGE_VOICE
        )
        if voices:
            voiceCombo.clear()
            for voice in voices:
                voiceCombo.addItem(voice["label"], userData=voice["name"])
            voiceCombo.setFixedWidth(260)
            selected_index = voiceCombo.findData(selected_voice)
            voiceCombo.setCurrentIndex(max(0, selected_index))
            widgets['voicesLoaded'] = True
            voiceCombo.setEnabled(True)
            return

        voiceCombo.setEnabled(True)
        InfoBar.error(
            title="中文音色加载失败",
            content="请检查网络连接，当前保留默认音色“晓晓”。",
            duration=5000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=form.window(),
        )

    voiceLoader.finished.connect(_onVoicesLoaded)

    def _updateVisibility(text):
        ttsCard.setVisible("TTS" in text)
        is_edge_tts = text == "Edge TTS（需要联网）"
        voiceCard.setVisible(is_edge_tts)
        fileCard.setVisible(text == "本地音频")
        if is_edge_tts and not widgets['voicesLoaded']:
            voiceCombo.setEnabled(False)
            voiceLoader.start()
    typeCombo.currentTextChanged.connect(_updateVisibility)
    _updateVisibility(typeCombo.currentText())

    return form, widgets


def broadcast_task_data(widgets):
    return {
        "name": widgets["nameInput"].text() or "未命名任务",
        "time": widgets["timePicker"].getTime().toString("HH:mm:ss"),
        "weeks": [
            index
            for index, button in enumerate(widgets["weekBtns"])
            if button.isChecked()
        ],
        "type": widgets["typeCombo"].currentText(),
        "content": widgets["ttsInput"].text(),
        "file": widgets["filePath"],
        "repeat": widgets["repeatSpin"].value(),
        "volume": widgets["volumeSlider"].value(),
        "voice": widgets["voiceCombo"].currentData() or DEFAULT_EDGE_VOICE,
    }


class AddTaskDialog(ScheduledTaskDialog):
    def __init__(self, parent=None):
        super().__init__(
            "添加播报任务",
            lambda form, _scrollArea: create_task_form(form),
            broadcast_task_data,
            parent,
        )


class TaskCard(ScheduledTaskCard):
    ICON = FIF.MEGAPHONE

    def _createForm(self):
        return create_task_form(self, self.data)

    def _bindForm(self):
        widgets = self.formWidgets
        widgets["nameInput"].textChanged.connect(self._saveData)
        widgets["timePicker"].timeChanged.connect(self._saveData)
        for button in widgets["weekBtns"]:
            button.clicked.connect(self._saveData)
        widgets["typeCombo"].currentTextChanged.connect(self._saveData)
        widgets["typeCombo"].currentTextChanged.connect(self._refreshFormHeight)
        widgets["ttsInput"].textChanged.connect(self._saveData)
        widgets["voiceCombo"].currentIndexChanged.connect(self._saveData)
        # 表单自己的选择文件槽先连，这里排在它之后，读到的已是新路径。
        widgets["fileBtn"].clicked.connect(self._saveData)
        widgets["repeatSpin"].valueChanged.connect(self._saveData)
        widgets["volumeSlider"].valueChanged.connect(self._saveData)

    def _extraButtons(self):
        self.playBtn = PushButton(FIF.PLAY, "试听配置", self)
        self.playBtn.clicked.connect(self._playTest)
        return (self.playBtn,)

    def _formData(self):
        return broadcast_task_data(self.formWidgets)

    def _summary(self):
        return f"触发时间: {self.data['time']}"

    def _playTest(self):
        from app.signal_bus import signalBus
        signalBus.testAudio.emit(self.data)


class SchedulePage(ScheduledTaskPage):
    def __init__(self, parent=None):
        super().__init__(
            "定时播报",
            "还没有设置播报任务哦 ~",
            cfg.broadcastTasks,
            cfg.broadcastTasksEnabled,
            parent,
        )

    def _createCard(self, task):
        return TaskCard(task, self.view)

    def _createDialog(self):
        return AddTaskDialog(self.window())
