from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow

from app.platform.screens import screenFor
from app.view.components.setting_card_group import QWIDGETSIZE_MAX
from app.view.components.window_background import (
    TIMER_THEME_BACKGROUND,
    WINDOW_SHADOW_MARGIN,
    WindowBackground,
)
from app.view.pages.broadcast_page import (
    VerticalButton,
    placeCornerButtons,
    showCloseConfirmation,
)


class TimerWindow(FramelessWindow):
    """Big white time on a full-screen or 600 × 190 windowed background.

    Exam Countdown and Fullscreen Clock differ only in the cfg items below,
    the text they show and the extra controls under the time.
    """

    backgroundItems = ()
    actionPositionItem = None
    topmostInWindowedItem = None
    topmostInFullscreenItem = None
    showTaskbarItem = None
    confirmCloseItem = None
    closeMessage = ""
    windowedTimeRatio = (1, 2)

    closeClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName(type(self).__name__)
        self.titleBar.hide()
        # 首次显示前启用透明表面，Win10 也由 Qt 绘制圆角。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setResizeEnabled(False)
        self.background = WindowBackground(
            *self.backgroundItems,
            lambda: TIMER_THEME_BACKGROUND,
            self,
        )
        self.background.lower()
        self.background.setGeometry(self.contentsRect())

        self.isWindowed = False
        self._closeFlyout = None
        self._moved = False

        self.titleLabel = QLabel(self)
        self.timeLabel = QLabel(self)
        for label in (self.titleLabel, self.timeLabel):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: white; background: transparent;")
            # 大字体的文本宽度不能反过来撑大窗口最小尺寸
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.timeLabel)
        for widget in self._createControls():
            self.vBoxLayout.addWidget(widget)
        self.vBoxLayout.addStretch(2)

        self.btnContainer = QWidget(self)
        self.btnLayout = QHBoxLayout(self.btnContainer)
        self.btnLayout.setContentsMargins(0, 0, 0, 0)
        self.btnLayout.setSpacing(12)
        self.btnWin = VerticalButton(FIF.COPY, "窗口化", forceDark=True)
        self.btnClose = VerticalButton(FIF.CLOSE, "关闭", primary=True, forceDark=True)
        self.btnWin.clicked.connect(self.toggleWindowMode)
        self.btnClose.clicked.connect(self._onClose)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)

    def _createControls(self):
        return ()

    def _cornerButtons(self):
        return [self.btnWin, self.btnClose]

    def _refreshTime(self):
        pass

    def _setControlsShown(self, shown):
        pass

    def _setupCornerButtons(self):
        while self.btnLayout.count():
            item = self.btnLayout.takeAt(0)
            if item.widget():
                self.btnLayout.removeWidget(item.widget())

        buttons = self._cornerButtons()
        ordered = reversed(buttons) if self._buttonsAtLeft() else buttons
        for button in ordered:
            self.btnLayout.addWidget(button)
        for button in buttons:
            button.setWindowed(self.isWindowed)
            button.updateStyle()
        self.btnWin.iconEnum = FIF.FULL_SCREEN if self.isWindowed else FIF.COPY
        self.btnWin.updateStyle()

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def _buttonsAtLeft(self):
        return self.actionPositionItem.value == "左下角"

    def _updateBtnPosition(self):
        placeCornerButtons(self.btnContainer, self.contentsRect(), self._buttonsAtLeft())

    def toggleWindowMode(self):
        self.isWindowed = not self.isWindowed
        self._refreshTime()
        self._setupCornerButtons()
        self._applyWindowState()

    def _applyWindowState(self):
        isTop = (
            self.topmostInWindowedItem.value
            if self.isWindowed
            else self.topmostInFullscreenItem.value
        )
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if isTop:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        margin = WINDOW_SHADOW_MARGIN if self.isWindowed else 0
        self.setContentsMargins(margin, margin, margin, margin)
        self.background.setRoundedWindow(self.isWindowed)
        self.background.setGeometry(self.contentsRect())
        self.setStyleSheet(f"{self.objectName()} {{ background-color: transparent; }}")
        self.titleLabel.setVisible(not self.isWindowed)
        self._setControlsShown(not self.isWindowed)

        if self.isWindowed:
            self.showNormal()
            rect = screenFor(self).availableGeometry()
            # 底部只留角落操作按钮自身的高度
            self.vBoxLayout.setContentsMargins(16, 12, 16, 56)
            # 先按目标高度缩小字体，否则旧字体的最小尺寸会钳制 resize
            self._applyFonts(190)
            self.setFixedSize(600 + 2 * margin, 190 + 2 * margin)
            self.move(rect.center() - self.rect().center())
        else:
            self.vBoxLayout.setContentsMargins(40, 20, 40, 20)
            self.setMinimumSize(0, 0)
            self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
            if self.showTaskbarItem.value:
                self.showNormal()
                self.setGeometry(screenFor(self).availableGeometry())
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
        numerator, denominator = self.windowedTimeRatio
        size = max(32, height * numerator // denominator if self.isWindowed else height * 9 // 40)
        font.setPixelSize(size)
        font.setBold(True)
        # 超宽时按比例缩小字号到刚好放得下
        width = QFontMetrics(font).horizontalAdvance(self.timeLabel.text())
        margins = self.vBoxLayout.contentsMargins()
        available = self.contentsRect().width() - margins.left() - margins.right()
        if width > available:
            font.setPixelSize(max(32, size * available // width))
        self.timeLabel.setFont(font)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.background.setGeometry(self.contentsRect())
        self._applyFonts(self.contentsRect().height())
        self._updateBtnPosition()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragPos = event.globalPosition().toPoint() - self.pos()
            self._moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isWindowed and event.buttons() == Qt.MouseButton.LeftButton:
            position = event.globalPosition().toPoint()
            if (position - self.pos() - self._dragPos).manhattanLength() > 3:
                self._moved = True
            self.move(position - self._dragPos)
        super().mouseMoveEvent(event)

    def _onClose(self):
        if not self.confirmCloseItem.value:
            self.close()
            return
        if self._closeFlyout is not None:
            return
        self._closeFlyout = showCloseConfirmation(self, self.btnClose, self.closeMessage)

    def closeEvent(self, event):
        if self._closeFlyout is not None:
            self._closeFlyout.hide()
            self._closeFlyout.deleteLater()
            self._closeFlyout = None
        self.timer.stop()
        self.closeClicked.emit()
        super().closeEvent(event)
