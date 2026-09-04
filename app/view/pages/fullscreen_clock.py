from PySide6.QtCore import Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow

from app.config.cfg import cfg
from app.view.components.setting_card_group import QWIDGETSIZE_MAX
from app.view.components.window_background import WindowBackground
from app.view.pages.broadcast_page import VerticalButton, showCloseConfirmation


class FullscreenClockWindow(FramelessWindow):
    closeClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("FullscreenClockWindow")
        self.titleBar.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setResizeEnabled(False)

        self.background = WindowBackground(
            cfg.fullscreenClockBackgroundMode,
            cfg.fullscreenClockBackgroundColor,
            cfg.fullscreenClockBackgroundImagePath,
            cfg.fullscreenClockBackgroundScaleMode,
            lambda: QColor("black"),
            self,
        )
        self.background.lower()
        self.background.setGeometry(self.rect())

        self.is_windowed = False
        self._closeFlyout = None

        self.titleLabel = QLabel("当前时间", self)
        self.timeLabel = QLabel(self)
        for label in (self.titleLabel, self.timeLabel):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: white; background: transparent;")
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.timeLabel)
        self.vBoxLayout.addStretch(2)

        self.btnContainer = QWidget(self)
        self.btnLayout = QHBoxLayout(self.btnContainer)
        self.btnLayout.setContentsMargins(0, 0, 0, 0)
        self.btnLayout.setSpacing(12)
        self.btn_win = VerticalButton(FIF.COPY, "窗口化", force_dark=True)
        self.btn_close = VerticalButton(
            FIF.CLOSE,
            "关闭",
            primary=True,
            force_dark=True,
        )
        self.btn_win.clicked.connect(self.toggleWindowMode)
        self.btn_close.clicked.connect(self._onClose)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._updateTime)

    def startClock(self):
        self.timer.stop()
        self.is_windowed = cfg.fullscreenClockStartWindowed.value
        self._updateTime()
        self._setupCornerButtons()
        self._applyWindowState()

    def _updateTime(self):
        now = QTime.currentTime()
        self.timeLabel.setText(now.toString("HH : mm : ss"))
        self._applyFonts(self.height())
        self.timer.start(max(1, 1000 - now.msec()))

    def _setupCornerButtons(self):
        while self.btnLayout.count():
            item = self.btnLayout.takeAt(0)
            if item.widget():
                self.btnLayout.removeWidget(item.widget())

        widgets = [self.btn_win, self.btn_close]
        if cfg.fullscreenClockActionButtonPosition.value == "左下角":
            widgets.reverse()
        for widget in widgets:
            self.btnLayout.addWidget(widget)

        for button in (self.btn_win, self.btn_close):
            button.setWindowed(self.is_windowed)
            button.updateStyle()
        self.btn_win.icon_enum = FIF.FULL_SCREEN if self.is_windowed else FIF.COPY
        self.btn_win.updateStyle()

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def _updateBtnPosition(self):
        margin = self.btnLayout.spacing()
        if cfg.fullscreenClockActionButtonPosition.value == "左下角":
            targetX = margin
        else:
            targetX = self.width() - self.btnContainer.width() - margin
        targetY = self.height() - self.btnContainer.height() - margin
        self.btnContainer.move(targetX, targetY)
        self.btnContainer.raise_()

    def toggleWindowMode(self):
        self.is_windowed = not self.is_windowed
        self._setupCornerButtons()
        self._applyWindowState()

    def _applyWindowState(self):
        isTop = (
            cfg.fullscreenClockTopmostInWindowed.value
            if self.is_windowed
            else cfg.fullscreenClockTopmostInFullscreen.value
        )
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if isTop:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        self.background.setBorderVisible(self.is_windowed)
        self.setStyleSheet(
            "FullscreenClockWindow { background-color: transparent; }"
        )
        self.titleLabel.setVisible(not self.is_windowed)

        if self.is_windowed:
            self.showNormal()
            rect = self.screen().availableGeometry()
            self.vBoxLayout.setContentsMargins(16, 12, 16, 56)
            self._applyFonts(220)
            self.setFixedSize(680, 220)
            self.move(rect.center() - self.rect().center())
        else:
            self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
            self.setMinimumSize(0, 0)
            self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
            if cfg.showTaskbarInFullscreenClock.value:
                self.showNormal()
                self.setGeometry(self.screen().availableGeometry())
            else:
                self.showFullScreen()

        self.show()
        self.raise_()
        self.activateWindow()

    def _applyFonts(self, height):
        font = self.titleLabel.font()
        font.setPixelSize(max(16, height // 14))
        font.setBold(True)
        self.titleLabel.setFont(font)

        font = self.timeLabel.font()
        size = max(32, height * 9 // 20 if self.is_windowed else height * 9 // 40)
        font.setPixelSize(size)
        font.setBold(True)
        width = QFontMetrics(font).horizontalAdvance(self.timeLabel.text())
        margins = self.vBoxLayout.contentsMargins()
        available = self.width() - margins.left() - margins.right()
        if width > available:
            font.setPixelSize(max(32, size * available // width))
        self.timeLabel.setFont(font)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.background.setGeometry(self.rect())
        self._applyFonts(self.height())
        self._updateBtnPosition()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragPos = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_windowed and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._dragPos)
        super().mouseMoveEvent(event)

    def _onClose(self):
        if not cfg.confirmBeforeCloseFullscreenClock.value:
            self.close()
            return
        if self._closeFlyout is not None:
            return
        self._closeFlyout = showCloseConfirmation(
            self,
            self.btn_close,
            "关闭当前的全屏时钟？",
        )

    def closeEvent(self, event):
        if self._closeFlyout is not None:
            self._closeFlyout.hide()
            self._closeFlyout.deleteLater()
            self._closeFlyout = None
        self.timer.stop()
        self.closeClicked.emit()
        super().closeEvent(event)
