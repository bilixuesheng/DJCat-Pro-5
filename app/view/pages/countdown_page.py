from PySide6.QtCore import QPropertyAnimation, Qt, QTime, QTimer, QUrl, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    LineEdit,
    MessageBox,
    PickerColumnFormatter,
    PrimaryPushButton,
    SettingCard,
    SwitchButton,
    TimePicker,
    TitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow

from app.config.cfg import cfg
from app.config.paths import ASSET_DIR
from app.view.components.setting_card_group import QWIDGETSIZE_MAX
from app.view.pages.broadcast_page import VerticalButton

DEFAULT_TITLE = "距离考试结束还剩"
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


class CountdownWindow(FramelessWindow):
    closeClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("CountdownWindow")
        self.titleBar.hide()
        # 顶层窗口的 QSS 边框需要该属性才会绘制
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        # 固定布局窗口，任何模式下都不允许边缘拉伸
        self.setResizeEnabled(False)

        self.is_windowed = False
        self.voice_enabled = True
        self.initial_seconds = 0
        self.remaining = 0
        self.ended = False
        self.title_text = DEFAULT_TITLE
        self._played15 = False
        self._moved = False
        self._controls_visible = False

        self.titleLabel = QLabel(self)
        self.timeLabel = QLabel(self)
        for label in (self.titleLabel, self.timeLabel):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: white; background: transparent;")
            # 大字体的文本宽度不能反过来撑大窗口最小尺寸
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.controlsWidget = QWidget(self)
        controlsLayout = QHBoxLayout(self.controlsWidget)
        controlsLayout.setContentsMargins(0, 0, 0, 0)
        controlsLayout.setSpacing(16)
        controlsLayout.addStretch(1)
        self.btn_pause = QPushButton("暂停", self.controlsWidget)
        self.btn_add = QPushButton("加10秒", self.controlsWidget)
        self.btn_sub = QPushButton("减10秒", self.controlsWidget)
        for button in (self.btn_pause, self.btn_add, self.btn_sub):
            button.setFixedSize(100, 40)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                "QPushButton { background-color: rgba(255,255,255,0.15); color: white;"
                " border: none; border-radius: 8px; font-size: 16px; }"
                " QPushButton:hover { background-color: rgba(255,255,255,0.25); }"
            )
            controlsLayout.addWidget(button)
        controlsLayout.addStretch(1)

        self._controlsFx = QGraphicsOpacityEffect(self.controlsWidget)
        self._controlsFx.setOpacity(0)
        self.controlsWidget.setGraphicsEffect(self._controlsFx)
        self.controlsWidget.setEnabled(False)
        self._controlsAnim = QPropertyAnimation(self._controlsFx, b"opacity", self)
        self._controlsAnim.setDuration(200)

        self.hideControlsTimer = QTimer(self)
        self.hideControlsTimer.setSingleShot(True)
        self.hideControlsTimer.setInterval(10_000)
        self.hideControlsTimer.timeout.connect(lambda: self._setControlsVisible(False))

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.timeLabel)
        self.vBoxLayout.addSpacing(20)
        self.vBoxLayout.addWidget(self.controlsWidget)
        self.vBoxLayout.addStretch(2)

        self.btnContainer = QWidget(self)
        self.btnLayout = QHBoxLayout(self.btnContainer)
        self.btnLayout.setContentsMargins(0, 0, 0, 0)
        self.btnLayout.setSpacing(12)
        self.btn_reset = VerticalButton(FIF.SYNC, "重置", force_dark=True)
        self.btn_win = VerticalButton(FIF.COPY, "窗口化", force_dark=True)
        self.btn_close = VerticalButton(FIF.CLOSE, "关闭", primary=True, force_dark=True)

        self.btn_pause.clicked.connect(self._onPause)
        self.btn_add.clicked.connect(lambda: self._onAdjust(10))
        self.btn_sub.clicked.connect(lambda: self._onAdjust(-10))
        self.btn_reset.clicked.connect(self.resetCountdown)
        self.btn_win.clicked.connect(self.toggleWindowMode)
        self.btn_close.clicked.connect(self.close)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(lambda: self._setRemaining(self.remaining - 1))

        self.sound = QSoundEffect(self)

    def startCountdown(self, title, seconds, voice_enabled):
        self.title_text = title
        self.voice_enabled = voice_enabled
        self.initial_seconds = seconds
        self.remaining = seconds
        self.ended = False
        self._played15 = False
        self.titleLabel.setText(title)
        self.btn_pause.setText("暂停")
        self._updateDisplay()
        self._setControlsVisible(False, animated=False)

        self.is_windowed = False
        self._setupCornerButtons()
        self._applyWindowState()
        self.timer.start()

    def resetCountdown(self):
        self.ended = False
        self._played15 = False
        self.remaining = self.initial_seconds
        self.titleLabel.setText(self.title_text)
        self.btn_pause.setText("暂停")
        self._updateDisplay()
        self.timer.start()

    def _onPause(self):
        if self.ended:
            return
        if self.timer.isActive():
            self.timer.stop()
            self.btn_pause.setText("继续")
        else:
            self.timer.start()
            self.btn_pause.setText("暂停")
        self.hideControlsTimer.start()

    def _onAdjust(self, delta):
        self._setRemaining(self.remaining + delta)
        self.hideControlsTimer.start()

    def _setRemaining(self, value):
        prev = self.remaining
        self.remaining = max(0, value)
        self._updateDisplay()

        if self.ended and self.remaining > 0:
            self.ended = False
            self.titleLabel.setText(self.title_text)
            self.timer.start()

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
            self.titleLabel.setText("考试结束")
            if self.voice_enabled:
                self._playSound("end.wav")

    def _updateDisplay(self):
        hours, rest = divmod(self.remaining, 3600)
        minutes, seconds = divmod(rest, 60)
        # 窗口化宽度有限，用紧凑格式换取更大的字号
        sep = ":" if self.is_windowed else " : "
        self.timeLabel.setText(f"{hours}{sep}{minutes}{sep}{seconds}")
        # 文本长度变化会影响窗口化下的自适应字号
        if self.is_windowed:
            self._applyFonts(self.height())

    def _playSound(self, name):
        self.sound.setSource(QUrl.fromLocalFile(str(ASSET_DIR / name)))
        self.sound.play()

    def _setControlsVisible(self, visible, animated=True):
        self._controls_visible = visible
        self.controlsWidget.setEnabled(visible)
        target = 1.0 if visible else 0.0
        self._controlsAnim.stop()
        if animated:
            self._controlsAnim.setStartValue(self._controlsFx.opacity())
            self._controlsAnim.setEndValue(target)
            self._controlsAnim.start()
        else:
            self._controlsFx.setOpacity(target)
        if visible:
            self.hideControlsTimer.start()
        else:
            self.hideControlsTimer.stop()

    def _setupCornerButtons(self):
        while self.btnLayout.count():
            item = self.btnLayout.takeAt(0)
            if item.widget():
                self.btnLayout.removeWidget(item.widget())

        widgets = [self.btn_reset, self.btn_win, self.btn_close]
        if cfg.actionButtonPosition.value == "左下角":
            widgets.reverse()
        for w in widgets:
            self.btnLayout.addWidget(w)

        for button in (self.btn_reset, self.btn_win, self.btn_close):
            button.setWindowed(self.is_windowed)
            button.updateStyle()
        self.btn_win.icon_enum = FIF.FULL_SCREEN if self.is_windowed else FIF.COPY
        self.btn_win.updateStyle()

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def _updateBtnPosition(self):
        margin = self.btnLayout.spacing()
        if cfg.actionButtonPosition.value == "左下角":
            target_x = margin
        else:
            target_x = self.width() - self.btnContainer.width() - margin
        target_y = self.height() - self.btnContainer.height() - margin
        self.btnContainer.move(target_x, target_y)
        self.btnContainer.raise_()

    def toggleWindowMode(self):
        self.is_windowed = not self.is_windowed
        self._updateDisplay()
        self._setupCornerButtons()
        self._applyWindowState()

    def _applyWindowState(self):
        is_top = (
            cfg.countdownTopmostInWindowed.value
            if self.is_windowed
            else cfg.countdownTopmostInFullscreen.value
        )
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if is_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        border = "border: 1px solid #808080;" if self.is_windowed else ""
        self.setStyleSheet(f"CountdownWindow {{ background-color: black; {border} }}")
        self.titleLabel.setVisible(not self.is_windowed)

        if self.is_windowed:
            self.showNormal()
            rect = self.screen().availableGeometry()
            # 底部留出角落小操作按钮的高度，避免与暂停/加减秒按钮重叠
            self.vBoxLayout.setContentsMargins(16, 12, 16, 56)
            # 先按目标高度缩小字体，否则旧字体的最小尺寸会钳制 resize
            self._applyFonts(300)
            self.setFixedSize(500, 300)
            self.move(rect.center() - self.rect().center())
        else:
            self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
            self.setMinimumSize(0, 0)
            self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
            if cfg.showTaskbarInCountdown.value:
                self.showNormal()
                self.setGeometry(self.screen().availableGeometry())
            else:
                self.showFullScreen()

        self.show()
        self.raise_()
        self.activateWindow()

    def _applyFonts(self, h):
        font = self.titleLabel.font()
        font.setPixelSize(max(16, h // 14))
        font.setBold(True)
        self.titleLabel.setFont(font)
        font = self.timeLabel.font()
        size = max(32, h * 2 // 5 if self.is_windowed else h // 5)
        font.setPixelSize(size)
        font.setBold(True)
        # 窗口化宽度固定，超宽时按比例缩小字号到刚好放得下
        if self.is_windowed:
            width = QFontMetrics(font).horizontalAdvance(self.timeLabel.text())
            margins = self.vBoxLayout.contentsMargins()
            avail = self.width() - margins.left() - margins.right()
            if width > avail:
                font.setPixelSize(max(32, size * avail // width))
        self.timeLabel.setFont(font)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._applyFonts(self.height())
        self._updateBtnPosition()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragPos = e.globalPosition().toPoint() - self.pos()
            self._moved = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.is_windowed and e.buttons() == Qt.MouseButton.LeftButton:
            if (e.globalPosition().toPoint() - self.pos() - self._dragPos).manhattanLength() > 3:
                self._moved = True
            self.move(e.globalPosition().toPoint() - self._dragPos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._moved:
            self._setControlsVisible(not self._controls_visible)
        super().mouseReleaseEvent(e)

    def closeEvent(self, event):
        self.timer.stop()
        self.hideControlsTimer.stop()
        self.closeClicked.emit()
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

        self.titleInput = LineEdit(self)
        self.titleInput.setText(DEFAULT_TITLE)
        self.titleInput.setPlaceholderText(DEFAULT_TITLE)
        self.vBoxLayout.addWidget(
            FormCard(FIF.FONT, "倒计时标题", "显示在倒计时上方，结束时变为“考试结束”", self.titleInput, self)
        )

        self.timePicker = TimePicker(self, showSeconds=True)
        for column, unit in enumerate(("时", "分", "秒")):
            self.timePicker.setColumnFormatter(column, UnitFormatter(unit))
        self.timePicker.setTime(QTime(1, 0, 0))
        self.vBoxLayout.addWidget(
            FormCard(FIF.STOP_WATCH, "倒计时时长", "设置倒计时的时、分、秒", self.timePicker, self)
        )

        self.voiceSwitch = SwitchButton(self)
        self.voiceSwitch.setChecked(True)
        self.vBoxLayout.addWidget(
            FormCard(FIF.VOLUME, "语音播报", "剩余 15 分钟与倒计时结束时播放提示音", self.voiceSwitch, self)
        )

        self.vBoxLayout.addStretch(1)

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
            MessageBox("无法开始", "倒计时时长不能为 0，请先设置时长。", self.window()).exec()
            return

        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.countdownWin.startCountdown(
            self.titleInput.text().strip() or DEFAULT_TITLE,
            seconds,
            self.voiceSwitch.isChecked(),
        )
        self.window().hide()

    def _onReturnToHome(self):
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self.window().show()
        self.window().raise_()
        self.window().activateWindow()
        self.backSignal.emit()
