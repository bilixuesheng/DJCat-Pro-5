import math
import time

from PySide6.QtCore import QPropertyAnimation, QSize, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    LineEdit,
    MessageBox,
    PickerColumnFormatter,
    PrimaryPushButton,
    PrimaryToolButton,
    SettingCard,
    SwitchButton,
    TitleLabel,
    ToolButton,
)

from app.config.cfg import cfg
from app.config.paths import ASSET_DIR
from app.view.components.scroll_area import ScrollArea
from app.view.components.task_picker import TouchTimePicker
from app.view.pages.broadcast_page import VerticalButton, showActionConfirmation
from app.view.pages.timer_window import TimerWindow

DEFAULT_TITLE = "距离考试结束还剩"
DEFAULT_END_TITLE = "考试结束"
VOICE_REMIND_SECONDS = 15 * 60


class UnitFormatter(PickerColumnFormatter):
    def __init__(self, unit):
        super().__init__()
        self.unit = unit

    def encode(self, value):
        return f"{value}{self.unit}"

    def decode(self, value: str):
        return int(str(value)[:-1])


class FormCard(SettingCard):
    def __init__(self, icon, title, content, widget, parent=None):
        super().__init__(icon, title, content, parent)
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)


class CountdownWindow(TimerWindow):
    backgroundItems = (
        cfg.countdownBackgroundMode,
        cfg.countdownBackgroundColor,
        cfg.countdownBackgroundImagePath,
        cfg.countdownBackgroundScaleMode,
    )
    actionPositionItem = cfg.countdownActionButtonPosition
    topmostInWindowedItem = cfg.countdownTopmostInWindowed
    topmostInFullscreenItem = cfg.countdownTopmostInFullscreen
    showTaskbarItem = cfg.showTaskbarInCountdown
    confirmCloseItem = cfg.confirmBeforeCloseCountdown
    closeMessage = "关闭后不会保存倒计时进度。"

    def __init__(self):
        self.voice_enabled = True
        self.initial_seconds = 0
        self.remaining = 0
        self.ended = False
        self.title_text = DEFAULT_TITLE
        self.end_title_text = DEFAULT_END_TITLE
        self._played15 = False
        self._controls_visible = False
        self._resetFlyout = None
        super().__init__()

        self.btn_reset = VerticalButton(FIF.SYNC, "重置", force_dark=True)
        self.btn_pause.clicked.connect(self._onPause)
        self.btn_rewind.clicked.connect(lambda: self._onAdjust(10))
        self.btn_forward.clicked.connect(lambda: self._onAdjust(-30))
        self.btn_reset.clicked.connect(self.resetCountdown)

        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tickCountdown)
        self._deadline = None
        self.sound = QSoundEffect(self)

    def _createControls(self):
        self.controlsWidget = QWidget(self)
        controlsLayout = QHBoxLayout(self.controlsWidget)
        # 全屏模式的控件间距放在控件自身内部；窗口化隐藏控件时会一起折叠
        controlsLayout.setContentsMargins(0, 20, 0, 0)
        controlsLayout.setSpacing(16)
        controlsLayout.addStretch(1)
        self.btn_rewind = ToolButton(FIF.SKIP_BACK.icon(color="white"), self.controlsWidget)
        self.btn_pause = PrimaryToolButton(FIF.PAUSE, self.controlsWidget)
        self.btn_forward = ToolButton(FIF.SKIP_FORWARD.icon(color="white"), self.controlsWidget)
        for button, name in (
            (self.btn_rewind, "倒回10秒"),
            (self.btn_pause, "暂停或继续"),
            (self.btn_forward, "快进30秒"),
        ):
            button.setFixedSize(56, 56)
            button.setIconSize(QSize(24, 24))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(name)
            controlsLayout.addWidget(button)
        for button in (self.btn_rewind, self.btn_forward):
            button.setStyleSheet(
                "QToolButton { background-color: rgba(255,255,255,0.15); color: white;"
                " border: none; border-radius: 28px; }"
                " QToolButton:hover { background-color: rgba(255,255,255,0.25); }"
            )
        self.btn_pause.setStyleSheet(
            self.btn_pause.styleSheet() + "PrimaryToolButton { border-radius: 28px; padding: 0; }"
        )
        controlsLayout.addStretch(1)

        self._controlsFx = QGraphicsOpacityEffect(self.controlsWidget)
        self._controlsFx.setOpacity(0)
        self.controlsWidget.setGraphicsEffect(self._controlsFx)
        self.controlsWidget.setEnabled(False)
        self._controlsAnim = QPropertyAnimation(self._controlsFx, b"opacity", self)
        self._controlsAnim.setDuration(200)
        self._controlsAnim.finished.connect(self._onControlsAnimationFinished)

        self.hideControlsTimer = QTimer(self)
        self.hideControlsTimer.setSingleShot(True)
        self.hideControlsTimer.setInterval(10_000)
        self.hideControlsTimer.timeout.connect(lambda: self._setControlsVisible(False))
        return (self.controlsWidget,)

    def _cornerButtons(self):
        return [self.btn_reset, *super()._cornerButtons()]

    def _setControlsShown(self, shown):
        if not shown:
            self._setControlsVisible(False, animated=False)
        self.controlsWidget.setVisible(shown)

    def startCountdown(self, title, seconds, voice_enabled, end_title=DEFAULT_END_TITLE):
        self.title_text = title
        self.end_title_text = end_title
        self.voice_enabled = voice_enabled
        self.initial_seconds = seconds
        self.remaining = seconds
        self.ended = False
        self._played15 = False
        self.titleLabel.setText(title)
        self.btn_pause.setIcon(FIF.PAUSE)
        self._refreshTime()
        self._setControlsVisible(False, animated=False)

        self.is_windowed = False
        self._setupCornerButtons()
        self._applyWindowState()
        self._startTimer()

    def _resetCountdown(self):
        self.ended = False
        self._played15 = False
        self.remaining = self.initial_seconds
        self.titleLabel.setText(self.title_text)
        self.btn_pause.setIcon(FIF.PAUSE)
        self._refreshTime()
        self._startTimer()

    def resetCountdown(self):
        if not cfg.confirmBeforeResetCountdown.value:
            self._resetCountdown()
            return None
        if self._resetFlyout is not None:
            return self._resetFlyout
        self._resetFlyout = showActionConfirmation(
            self,
            self.btn_reset,
            "确认重置？",
            "倒计时将恢复到最初设置的时间。",
            "重置",
            self._resetCountdown,
            "_resetFlyout",
        )
        return self._resetFlyout

    def _onPause(self):
        if self.ended:
            return
        if self.timer.isActive():
            self._tickCountdown()
            self.timer.stop()
            self._deadline = None
            self.btn_pause.setIcon(FIF.PLAY)
        else:
            self._startTimer()
            self.btn_pause.setIcon(FIF.PAUSE)
        self.hideControlsTimer.start()

    def _onAdjust(self, delta):
        was_active = self.timer.isActive()
        if was_active:
            self._tickCountdown()
        self._setRemaining(self.remaining + delta)
        if was_active and self.remaining > 0:
            self._deadline = time.monotonic() + self.remaining
        self.hideControlsTimer.start()

    def _startTimer(self):
        self._deadline = time.monotonic() + self.remaining
        self.timer.start()

    def _tickCountdown(self):
        if self._deadline is None or not self.timer.isActive():
            return
        remaining = max(0, math.ceil(self._deadline - time.monotonic()))
        self._setRemaining(remaining)

    def _setRemaining(self, value):
        prev = self.remaining
        self.remaining = max(0, value)
        self._refreshTime()

        if self.ended and self.remaining > 0:
            self.ended = False
            self.titleLabel.setText(self.title_text)
            self._startTimer()

        if (
            self.voice_enabled
            and not self._played15
            and prev > VOICE_REMIND_SECONDS >= self.remaining > 0
        ):
            self._played15 = True
            self._playSound("15.wav")

        if self.remaining == 0 and not self.ended:
            self.ended = True
            self.timer.stop()
            self._deadline = None
            self.titleLabel.setText(self.end_title_text)
            if self.voice_enabled:
                self._playSound("end.wav")

    def _refreshTime(self):
        hours, rest = divmod(self.remaining, 3600)
        minutes, seconds = divmod(rest, 60)
        separator = "\u2009:\u2009" if self.is_windowed else " : "
        self.timeLabel.setText(
            f"{hours}{separator}{minutes}{separator}{seconds}"
        )
        # 文本长度变化会影响窗口化下的自适应字号
        if self.is_windowed:
            self._applyFonts(self.contentsRect().height())

    def _playSound(self, name):
        self.sound.setSource(QUrl.fromLocalFile(str(ASSET_DIR / name)))
        self.sound.play()

    def _setControlsVisible(self, visible, animated=True):
        self._controls_visible = visible
        self.controlsWidget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not visible,
        )
        if visible:
            self.controlsWidget.setEnabled(True)
        target = 1.0 if visible else 0.0
        self._controlsAnim.stop()
        if animated:
            self._controlsAnim.setStartValue(self._controlsFx.opacity())
            self._controlsAnim.setEndValue(target)
            self._controlsAnim.start()
        else:
            self._controlsFx.setOpacity(target)
            self.controlsWidget.setEnabled(visible)
        if visible:
            self.hideControlsTimer.start()
        else:
            self.hideControlsTimer.stop()

    def _onControlsAnimationFinished(self):
        if not self._controls_visible:
            self.controlsWidget.setEnabled(False)
        self.btn_pause.update()

    def mouseReleaseEvent(self, e):
        if (
            not self.is_windowed
            and e.button() == Qt.MouseButton.LeftButton
            and not self._moved
        ):
            self._setControlsVisible(not self._controls_visible)
        super().mouseReleaseEvent(e)

    def closeEvent(self, event):
        if self._resetFlyout is not None:
            self._resetFlyout.hide()
            self._resetFlyout.deleteLater()
            self._resetFlyout = None
        self.hideControlsTimer.stop()
        self._controlsAnim.stop()
        self.sound.stop()
        super().closeEvent(event)


class CountdownEditPage(QWidget):
    backSignal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.setSpacing(10)

        topLayout = QHBoxLayout()
        self.backBtn = ToolButton(FIF.RETURN, self)
        self.backBtn.clicked.connect(self.backSignal.emit)
        self.pageTitle = TitleLabel("考试倒计时", self)
        topLayout.addWidget(self.backBtn)
        topLayout.addWidget(self.pageTitle)
        topLayout.addStretch(1)
        self.vBoxLayout.addLayout(topLayout)

        self.scrollArea = ScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.scrollWidget = QWidget(self.scrollArea)
        self.scrollLayout = QVBoxLayout(self.scrollWidget)
        self.scrollLayout.setContentsMargins(0, 0, 0, 0)
        self.scrollLayout.setSpacing(10)

        self.titleInput = LineEdit(self.scrollWidget)
        self.titleInput.setText(DEFAULT_TITLE)
        self.titleInput.setPlaceholderText(DEFAULT_TITLE)
        self.scrollLayout.addWidget(
            FormCard(
                FIF.FONT,
                "倒计时标题",
                "显示在倒计时上方",
                self.titleInput,
                self.scrollWidget,
            )
        )

        self.endTitleInput = LineEdit(self.scrollWidget)
        self.endTitleInput.setText(DEFAULT_END_TITLE)
        self.endTitleInput.setPlaceholderText(DEFAULT_END_TITLE)
        self.scrollLayout.addWidget(
            FormCard(
                FIF.FONT,
                "结束时标题",
                "倒计时结束后显示在上方",
                self.endTitleInput,
                self.scrollWidget,
            )
        )

        self.timePicker = TouchTimePicker(self.scrollWidget, showSeconds=True)
        for column, unit in enumerate(("时", "分", "秒")):
            self.timePicker.setColumnFormatter(column, UnitFormatter(unit))
        self.timePicker.setTime(QTime(1, 0, 0))
        self.scrollLayout.addWidget(
            FormCard(
                FIF.STOP_WATCH,
                "倒计时时长",
                "设置倒计时的时、分、秒",
                self.timePicker,
                self.scrollWidget,
            )
        )

        self.voiceSwitch = SwitchButton(self.scrollWidget)
        self.voiceSwitch.setChecked(True)
        self.scrollLayout.addWidget(
            FormCard(
                FIF.VOLUME,
                "语音播报",
                "剩余 15 分钟与倒计时结束时播放提示音",
                self.voiceSwitch,
                self.scrollWidget,
            )
        )
        self.scrollLayout.addStretch(1)
        self.scrollArea.setWidget(self.scrollWidget)
        self.vBoxLayout.addWidget(self.scrollArea, 1)

        btnLayout = QHBoxLayout()
        self.startBtn = PrimaryPushButton(self)
        self.startBtn.setIcon(FIF.PLAY)
        self.startBtn.setText("开始倒计时")
        self.startBtn.setMinimumWidth(200)
        self.startBtn.clicked.connect(self._onStart)
        btnLayout.addStretch(1)
        btnLayout.addWidget(self.startBtn)
        self.vBoxLayout.addLayout(btnLayout)

        self.countdownWin = CountdownWindow()
        self.countdownWin.closeClicked.connect(self._onReturnToHome)

    def _onStart(self):
        time = self.timePicker.getTime()
        seconds = time.hour() * 3600 + time.minute() * 60 + time.second()
        if seconds <= 0:
            dialog = MessageBox(
                "无法开始",
                "倒计时时长不能为 0，请先设置时长。",
                self.window(),
            )
            try:
                dialog.exec()
            finally:
                dialog.deleteLater()
            return

        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.countdownWin.startCountdown(
            self.titleInput.text().strip() or DEFAULT_TITLE,
            seconds,
            self.voiceSwitch.isChecked(),
            self.endTitleInput.text().strip() or DEFAULT_END_TITLE,
        )
        self.window().hide()

    def _onReturnToHome(self):
        showMainWindow = cfg.showMainWindowAfterCountdown.value
        QApplication.instance().setQuitOnLastWindowClosed(showMainWindow)
        if showMainWindow:
            self.window().show()
            self.window().raise_()
            self.window().activateWindow()
        self.backSignal.emit()
