import json
import threading

import requests
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QScroller,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CheckBox,
    Flyout,
    FlyoutAnimationType,
    FlyoutView,
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SmoothScrollDelegate,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
    ToolButton,
    isDarkTheme,
    qconfig,
)
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow

from app.common.ai_markdown import PEAK_HOURS_TEXT, fetchQuota, machineId
from app.common.update_download import isHttpsResponseChain
from app.config.cfg import cfg
from app.config.constants import AI_MARKDOWN_API
from app.config.paths import ASSET_DIR
from app.view.components.markdown_view import MarkdownView
from app.view.components.window_background import WindowBackground


def showActionConfirmation(
    window,
    target,
    title,
    warning,
    confirmText,
    callback,
    referenceName=None,
):
    view = FlyoutView(title, warning, FIF.QUESTION)
    buttons = QWidget(view)
    layout = QHBoxLayout(buttons)
    layout.setContentsMargins(0, 0, 0, 0)
    cancelButton = PushButton("取消", buttons)
    confirmButton = PrimaryPushButton(confirmText, buttons)
    layout.addWidget(cancelButton)
    layout.addWidget(confirmButton)
    view.addWidget(buttons, align=Qt.AlignmentFlag.AlignRight)

    flyout = Flyout.make(
        view,
        target,
        window,
        FlyoutAnimationType.PULL_UP,
    )
    flyout.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    def clearReference():
        if referenceName and getattr(window, referenceName, None) is flyout:
            setattr(window, referenceName, None)

    flyout.destroyed.connect(clearReference)

    def dismiss():
        clearReference()
        flyout.hide()
        flyout.close()
        flyout.deleteLater()

    def confirm():
        dismiss()
        QTimer.singleShot(0, callback)

    cancelButton.clicked.connect(dismiss)
    confirmButton.clicked.connect(confirm)
    return flyout


def showCloseConfirmation(window, target, warning):
    return showActionConfirmation(
        window,
        target,
        "确认关闭？",
        warning,
        "关闭",
        window.close,
        "_closeFlyout",
    )


class _VerticalButtonMixin:
    def _initVerticalButton(self, icon_enum, text, primary, force_dark):
        self.icon_enum = icon_enum
        self._buttonText = text
        self._primary = primary
        self.force_dark = force_dark
        self._windowed = False
        self.setIcon(QIcon())
        self.setText(text)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(80, 65)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.updateStyle()

    def updateStyle(self):
        dark = self.force_dark or (
            isDarkTheme()
            if cfg.customThemeMode.value == "System"
            else cfg.customThemeMode.value == "Dark"
        )
        if self._primary:
            normal = qconfig.themeColor.value.name()
            hover = qconfig.themeColor.value.lighter(108).name()
            pressed = qconfig.themeColor.value.darker(108).name()
            foreground = "white"
        elif dark:
            normal = "rgba(255, 255, 255, 26)"
            hover = "rgba(255, 255, 255, 38)"
            pressed = "rgba(255, 255, 255, 18)"
            foreground = "white"
        else:
            normal = "rgba(0, 0, 0, 13)"
            hover = "rgba(0, 0, 0, 26)"
            pressed = "rgba(0, 0, 0, 20)"
            foreground = "black"

        self.setStyleSheet(
            f"QPushButton {{ color: {foreground}; background-color: {normal};"
            " border: none; border-radius: 8px; padding: 0; }"
            f" QPushButton:hover {{ background-color: {hover}; }}"
            f" QPushButton:pressed {{ background-color: {pressed}; }}"
        )
        self.update()

    def setWindowed(self, windowed: bool):
        self._windowed = windowed
        self.setFixedSize(50, 40) if windowed else self.setFixedSize(80, 65)
        self.update()

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        option.text = ""

        painter = QStylePainter(self)
        painter.drawControl(QStyle.ControlElement.CE_PushButton, option)
        if not self.isEnabled():
            painter.setOpacity(0.36)
        elif self.isDown():
            painter.setOpacity(0.63)

        color = self._foregroundColor()
        icon = self.icon_enum.icon(color=color)
        iconSize = self.iconSize()
        iconX = (self.width() - iconSize.width()) // 2
        iconY = (self.height() - iconSize.height()) // 2 if self._windowed else 9
        icon.paint(painter, iconX, iconY, iconSize.width(), iconSize.height())

        if not self._windowed:
            painter.setPen(color)
            painter.drawText(
                0,
                iconY + iconSize.height() + 4,
                self.width(),
                22,
                Qt.AlignmentFlag.AlignCenter,
                self._buttonText,
            )

    def _foregroundColor(self):
        dark = self.force_dark or (
            isDarkTheme()
            if cfg.customThemeMode.value == "System"
            else cfg.customThemeMode.value == "Dark"
        )
        return QColor("white") if self._primary or dark else QColor("black")


class _VerticalPushButton(_VerticalButtonMixin, PushButton):
    def __init__(self, icon_enum, text, parent=None, force_dark=False):
        super().__init__(parent)
        self._initVerticalButton(icon_enum, text, False, force_dark)


class _VerticalPrimaryPushButton(_VerticalButtonMixin, PrimaryPushButton):
    def __init__(self, icon_enum, text, parent=None, force_dark=False):
        super().__init__(parent)
        self._initVerticalButton(icon_enum, text, True, force_dark)


def VerticalButton(
    icon_enum,
    text,
    primary=False,
    parent=None,
    force_dark=False,
):
    buttonType = _VerticalPrimaryPushButton if primary else _VerticalPushButton
    return buttonType(
        icon_enum,
        text,
        parent=parent,
        force_dark=force_dark,
    )

class FloatingMiniWindow(QWidget):
    restoreSignal = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.setFixedSize(60, 60)

        self.btn = QToolButton(self)
        self.btn.setFixedSize(60, 60)
        self.btn.setIconSize(QSize(24, 24))

        self.btn.installEventFilter(self)

        self.setWindowOpacity(0.5)
        self._dragPos = QPoint()
        self._isDragging = False

        self._updateStyle()
        qconfig.themeColor.valueChanged.connect(self._updateStyle)

    def _updateStyle(self):
        theme_color = qconfig.themeColor.value.name()
        self.btn.setStyleSheet(f"""
            QToolButton {{
                background-color: {theme_color};
                border-radius: 30px;
                border: none;
            }}
            QToolButton:hover {{
                background-color: {theme_color};
            }}
        """)
        self.btn.setIcon(FIF.FULL_SCREEN.icon(color=QColor("white")))

    def eventFilter(self, obj, event):
        if obj == self.btn:
            if event.type() == QEvent.Type.Enter:
                self.setWindowOpacity(1.0)
                return False
            elif event.type() == QEvent.Type.Leave:
                self.setWindowOpacity(0.5)
                return False
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._isDragging = False
                # 记录点击位置相对窗口左上角的偏移量，修复跳跃问题
                self._dragPos = event.globalPosition().toPoint() - self.pos()
                return True # 拦截事件，避免直接触发点击
            elif event.type() == QEvent.Type.MouseMove and event.buttons() == Qt.MouseButton.LeftButton:
                if not self._dragPos.isNull():
                    # 移动距离超过 3 像素才判定为拖拽 (防手抖误触)
                    if (event.globalPosition().toPoint() - self.pos() - self._dragPos).manhattanLength() > 3:
                        self._isDragging = True
                    self.move(event.globalPosition().toPoint() - self._dragPos)
                return True
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if not self._isDragging:
                    self.restoreSignal.emit()
                self._isDragging = False
                self._dragPos = QPoint()
                return True
        return super().eventFilter(obj, event)

class BroadcastWindow(FramelessWindow):
    editClicked = Signal()
    closeClicked = Signal()
    BORDER_WIDTH = 12

    def __init__(self):
        super().__init__()
        self.setObjectName("BroadcastWindow")
        self.titleBar.hide()
        # 顶层窗口的 QSS 边框需要该属性才会绘制
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._is_editing = False
        self._isTracking = False
        self._closeFlyout = None
        self.background = WindowBackground(
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            self._themeBackgroundColor,
            self,
        )
        self.background.lower()
        self.background.setGeometry(self.rect())
        cfg.customThemeMode.valueChanged.connect(self.background.refresh)

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 0)

        self.titleLabel = TitleLabel(self)
        font = QFont(); font.setPointSize(48); font.setBold(True)
        self.titleLabel.setFont(font)

        self.contentEdit = QTextEdit(self)
        self.contentEdit.setReadOnly(True)
        self.contentEdit.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.contentEdit.setStyleSheet("border: none; background: transparent;")
        self.contentScrollDelegate = SmoothScrollDelegate(self.contentEdit, True)
        QScroller.grabGesture(
            self.contentEdit.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )

        self.markdownView = MarkdownView(
            self,
            largeText=True,
            transparentBackground=True,
        )
        self.markdownView.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.markdownView.hide()

        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.vBoxLayout.addWidget(self.contentEdit, 1)
        self.vBoxLayout.addWidget(self.markdownView, 1)

        self.btnContainer = QWidget(self)
        self.btnLayout = QHBoxLayout(self.btnContainer)
        self.btnLayout.setContentsMargins(0, 0, 0, 0)
        self.btnLayout.setSpacing(12)

        self.is_windowed = False
        self.miniWindow = FloatingMiniWindow(self)
        self.miniWindow.restoreSignal.connect(self.restoreFromMini)

        self.btn_edit = VerticalButton(FIF.EDIT, "编辑")
        self.btn_min = VerticalButton(FIF.MINIMIZE, "最小化")
        self.btn_win = VerticalButton(FIF.FULL_SCREEN, "窗口化")
        self.btn_close = VerticalButton(FIF.CLOSE, "关闭", primary=True)

        self.btn_edit.clicked.connect(self._onEdit)
        self.btn_min.clicked.connect(self.minimizeToMini)
        self.btn_win.clicked.connect(self.toggleWindowMode)
        self.btn_close.clicked.connect(self._onClose)

    def _themeBackgroundColor(self):
        is_dark = (
            isDarkTheme()
            if cfg.customThemeMode.value == "System"
            else cfg.customThemeMode.value == "Dark"
        )
        return QColor("#202020" if is_dark else "#FFFFFF")

    def _applyStyle(self):
        is_dark = isDarkTheme() if cfg.customThemeMode.value == "System" else cfg.customThemeMode.value == "Dark"
        text_color = "white" if is_dark else "black"
        border = "border: 1px solid #808080;" if self.is_windowed else ""
        self.setStyleSheet(f"BroadcastWindow {{ background-color: transparent; {border} }} QTextEdit {{ color: {text_color}; background: transparent; }}")

    def setContent(self, title, text, is_markdown=False):
        self._applyStyle()

        self.btn_edit.updateStyle()
        self.btn_min.updateStyle()
        self.btn_win.updateStyle()
        self.btn_close.updateStyle()

        self.titleLabel.setText(title)
        self.titleLabel.setStyleSheet(f"color: {qconfig.themeColor.value.name()};")

        if is_markdown:
            self.contentEdit.clear()
            self.contentEdit.hide()
            self.markdownView.show()
            self.markdownView.syncTheme()
            self.markdownView.setMarkdown(text)
        else:
            self.markdownView.hide()
            self.markdownView.clear()
            self.contentEdit.show()
            self.contentEdit.setPlainText(text)
            font = QFont(); font.setPointSize(26)
            self.contentEdit.setFont(font)
            cursor = self.contentEdit.textCursor()
            blockFormat = cursor.blockFormat()
            blockFormat.setLineHeight(
                MarkdownView.LARGE_TEXT_LINE_HEIGHT,
                QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
            )
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeBlockFormat(blockFormat)

    def setupLayout(self):
        while self.btnLayout.count():
            item = self.btnLayout.takeAt(0)
            if item.widget(): self.btnLayout.removeWidget(item.widget())

        widgets = [self.btn_edit, self.btn_min, self.btn_win, self.btn_close]
        if cfg.broadcastActionButtonPosition.value == "左下角":
            widgets.reverse()

        for w in widgets: self.btnLayout.addWidget(w)

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.background.setGeometry(self.rect())
        self._updateBtnPosition()

    def _updateBtnPosition(self):
        margin = self.btnLayout.spacing()
        if cfg.broadcastActionButtonPosition.value == "左下角":
            target_x = margin
        else:
            target_x = self.width() - self.btnContainer.width() - margin

        target_y = self.height() - self.btnContainer.height() - margin
        self.btnContainer.move(target_x, target_y)
        self.btnContainer.raise_()

    def startBroadcast(self):
        self.is_windowed = False
        self.setupLayout()
        self._updateButtonsState()
        self._applyWindowState()

    def toggleWindowMode(self):
        self.is_windowed = not self.is_windowed
        self._updateButtonsState()
        self._applyWindowState()

    def _updateButtonsState(self):
        self.btn_edit.setWindowed(self.is_windowed)
        self.btn_min.setWindowed(self.is_windowed)
        self.btn_win.setWindowed(self.is_windowed)
        self.btn_close.setWindowed(self.is_windowed)

        self.btn_win.icon_enum = FIF.FULL_SCREEN if self.is_windowed else FIF.COPY
        self.btn_win.updateStyle()

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def _applyWindowState(self):
        is_top = cfg.topmostInWindowed.value if self.is_windowed else cfg.topmostInFullscreen.value
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if is_top: flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # 全屏时禁用系统边缘拉伸，避免鼠标在屏幕边缘仍能调整窗口大小
        self.setResizeEnabled(self.is_windowed)
        self._applyStyle()

        if self.is_windowed:
            self.showNormal()
            rect = self.screen().availableGeometry()
            self.resize(int(rect.width() * 0.5), int(rect.height() * 0.5))
            self.move(rect.center() - self.rect().center())
        else:
            if cfg.showTaskbarInBroadcast.value:
                self.showNormal()
                self.setGeometry(self.screen().availableGeometry())
            else:
                self.showFullScreen()

        self.show()
        self.raise_()
        self.activateWindow()

    def minimizeToMini(self):
        self.hide()
        self.miniWindow._updateStyle()
        self.miniWindow.show()
        rect = self.screen().availableGeometry()
        if cfg.broadcastActionButtonPosition.value == "右下角":
            self.miniWindow.move(
                rect.left() + rect.width() - 150,
                rect.top() + rect.height() - 150,
            )
        else:
            self.miniWindow.move(
                rect.left() + 50,
                rect.top() + rect.height() - 150,
            )

    def restoreFromMini(self):
        self.miniWindow.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def _onEdit(self):
        self._is_editing = True
        self.close()

    def _onClose(self):
        if not cfg.confirmBeforeCloseBroadcast.value:
            self.close()
            return
        if self._closeFlyout is not None:
            return
        self._closeFlyout = showCloseConfirmation(
            self,
            self.btn_close,
            "关闭后可通过“导入”恢复上次投送内容。",
        )

    def closeEvent(self, event):
        if self._closeFlyout is not None:
            self._closeFlyout.hide()
            self._closeFlyout.deleteLater()
            self._closeFlyout = None
        self.contentEdit.clear()
        self.markdownView.clear()
        self.miniWindow.hide()
        if self._is_editing: self.editClicked.emit()
        else: self.closeClicked.emit()
        self._is_editing = False
        super().closeEvent(event)

    def mousePressEvent(self, e):
        if self.is_windowed and e.button() == Qt.MouseButton.LeftButton:
            source = self.childAt(e.position().toPoint())
            blocked = any(
                source is widget or widget.isAncestorOf(source)
                for widget in (
                    self.contentEdit,
                    self.markdownView,
                    self.btnContainer,
                )
                if source is not None
            )
            self._isTracking = not blocked
            if self._isTracking:
                self._dragPos = e.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.is_windowed and getattr(self, '_isTracking', False):
            self.move(e.globalPosition().toPoint() - self._dragPos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._isTracking = False
        super().mouseReleaseEvent(e)

def _iterSseContent(lines):
    finished = False
    for line in lines:
        if not line or not line.startswith("data:"):
            continue

        data = line[5:].strip()
        if data == "[DONE]":
            if finished:
                return
            break

        payload = json.loads(data)
        choices = payload.get("choices", ())
        if choices:
            choice = choices[0]
            finishReason = choice.get("finish_reason")
            if finishReason == "length":
                raise RuntimeError("AI 输出过长，请缩短输入后重试。")
            if finishReason not in (None, "stop"):
                raise RuntimeError("AI 转换未正常完成，请重试。")
            finished = finishReason == "stop" or finished
            content = choice.get("delta", {}).get("content")
            if content:
                yield content

    raise RuntimeError("AI 服务流式响应未正常结束，请重试。")


class AIMarkdownDialog(MessageBoxBase):
    quotaReceived = Signal(int, int, int, object, str)
    chunkReceived = Signal(str)
    conversionFinished = Signal(int, int, int)
    conversionFailed = Signal(str, int, int, int)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._source = text
        self._result = ""
        self._running = False
        self._finished = False
        self._remaining = None
        self._limit = 15
        self._cost = 1
        self._peakEnabled = None
        self._borderIndex = 0
        self._quotaRequestRunning = False
        self._cancelEvent = threading.Event()
        self._responseLock = threading.Lock()
        self._activeResponse = None
        self._resultChunks = []
        self._pendingChunks = []

        self.titleLabel = SubtitleLabel("AI帮改Markdown", self)
        self.descriptionLabel = BodyLabel(
            "将要转换的作业清单或任务填入下面的输入框，即可转换为标准markdown格式。",
            self,
        )
        self.descriptionLabel.setWordWrap(True)
        self.inputEdit = TextEdit(self)
        self.inputEdit.setPlainText(text)
        self.inputEdit.setPlaceholderText("在此输入要转换的内容")
        self.inputEdit.setMinimumHeight(120)
        QScroller.grabGesture(
            self.inputEdit.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        self._inputStyle = self.inputEdit.styleSheet()
        self.quotaLabel = CaptionLabel(self)
        self.quotaLabel.setWordWrap(True)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descriptionLabel)
        self.viewLayout.addWidget(self.inputEdit)
        self.viewLayout.addWidget(self.quotaLabel)
        self.widget.setFixedWidth(min(680, max(0, self.width() - 80)))

        self.yesButton.setText("开始转换")
        self.cancelButton.setText("取消")
        self.inputEdit.textChanged.connect(self._refreshStartButton)
        self.quotaReceived.connect(self._onQuotaReceived)
        self.chunkReceived.connect(self._appendChunk)
        self.conversionFinished.connect(self._onConversionFinished)
        self.conversionFailed.connect(self._onConversionFailed)

        self._busyTimer = QTimer(self)
        self._busyTimer.setInterval(60)
        self._busyTimer.timeout.connect(self._updateBusyStyle)
        self._quotaTimer = QTimer(self)
        self._quotaTimer.setInterval(30_000)
        self._quotaTimer.timeout.connect(self._refreshQuota)
        self._quotaTimer.start()
        self._flushTimer = QTimer(self)
        self._flushTimer.setSingleShot(True)
        self._flushTimer.setInterval(50)
        self._flushTimer.timeout.connect(self._flushChunks)
        self._updateQuotaLabel()
        self._refreshStartButton()
        self._refreshQuota()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "widget"):
            self.widget.setFixedWidth(min(680, max(0, event.size().width() - 80)))

    def resultText(self):
        return "".join(self._resultChunks)

    def validate(self):
        if self._finished:
            return True
        if self._running:
            return False

        self._source = self.inputEdit.toPlainText().strip()
        if not self._source:
            return False

        self._startConversion()
        return False

    def reject(self):
        if self._running:
            self._cancelConversion()
        super().reject()

    def _fetchQuota(self):
        try:
            quota = fetchQuota()
            try:
                self.quotaReceived.emit(
                    *(quota if quota else (-1, self._limit, 1, None, ""))
                )
            except RuntimeError:
                pass
        finally:
            self._quotaRequestRunning = False

    def _refreshQuota(self):
        if self._quotaRequestRunning:
            return
        self._quotaRequestRunning = True
        self._peakEnabled = None
        self._updateQuotaLabel()
        threading.Thread(target=self._fetchQuota, daemon=True).start()

    def _startConversion(self):
        self._running = True
        self._result = ""
        self._resultChunks.clear()
        self._pendingChunks.clear()
        self._cancelEvent.clear()
        self.inputEdit.clear()
        self.inputEdit.setReadOnly(True)
        self.yesButton.setEnabled(False)
        self.cancelButton.setEnabled(True)
        self.cancelButton.setText("取消转换")
        self._busyTimer.start()
        self._updateBusyStyle()
        threading.Thread(target=self._streamConversion, daemon=True).start()

    def _streamConversion(self):
        remaining = self._remaining if self._remaining is not None else -1
        limit = self._limit
        cost = self._cost
        payload = {"content": self._source, "machine_id": machineId()}
        if cfg.aiMarkdownCustomStyleEnabled.value:
            customStyle = cfg.aiMarkdownCustomStyle.value.strip()
            if customStyle:
                payload["custom_style"] = customStyle
        response = None
        try:
            response = requests.post(
                AI_MARKDOWN_API,
                json=payload,
                stream=True,
                timeout=(10, 120),
            )
            if not isHttpsResponseChain(response, AI_MARKDOWN_API):
                raise RuntimeError("AI 服务连接未保持 HTTPS")
            with self._responseLock:
                if self._cancelEvent.is_set():
                    response.close()
                    return
                self._activeResponse = response
            with response:
                remaining = int(
                    response.headers.get("X-RateLimit-Remaining", remaining)
                )
                limit = int(response.headers.get("X-RateLimit-Limit", limit))
                cost = int(response.headers.get("X-RateLimit-Cost", cost))
                if not response.ok:
                    try:
                        message = response.json().get("message")
                    except (AttributeError, ValueError):
                        message = None
                    raise RuntimeError(
                        message or f"AI 服务暂时不可用（{response.status_code}）"
                    )

                response.encoding = "utf-8"
                for chunk in _iterSseContent(
                    response.iter_lines(chunk_size=1, decode_unicode=True)
                ):
                    if self._cancelEvent.is_set():
                        return
                    try:
                        self.chunkReceived.emit(chunk)
                    except RuntimeError:
                        return
            if self._cancelEvent.is_set():
                return
            try:
                self.conversionFinished.emit(remaining, limit, cost)
            except RuntimeError:
                pass
        except requests.RequestException:
            if self._cancelEvent.is_set():
                return
            try:
                self.conversionFailed.emit(
                    "无法连接 AI 服务，请检查网络后重试。",
                    remaining,
                    limit,
                    cost,
                )
            except RuntimeError:
                pass
        except (RuntimeError, TypeError, ValueError) as error:
            if self._cancelEvent.is_set():
                return
            try:
                self.conversionFailed.emit(str(error), remaining, limit, cost)
            except RuntimeError:
                pass
        finally:
            with self._responseLock:
                if self._activeResponse is response:
                    self._activeResponse = None
            if response is not None:
                response.close()

    def _appendChunk(self, chunk):
        self._resultChunks.append(chunk)
        self._pendingChunks.append(chunk)
        if not self._flushTimer.isActive():
            self._flushTimer.start()

    def _flushChunks(self):
        if not self._pendingChunks:
            return
        chunk = "".join(self._pendingChunks)
        self._pendingChunks.clear()
        self._result += chunk
        self.inputEdit.moveCursor(QTextCursor.MoveOperation.End)
        self.inputEdit.insertPlainText(chunk)
        self.inputEdit.ensureCursorVisible()

    def _cancelConversion(self):
        self._cancelEvent.set()
        with self._responseLock:
            response = self._activeResponse
        if response is not None:
            response.close()
        self._running = False
        self._stopBusyStyle()

    def _onQuotaReceived(
        self, remaining, limit, cost, peakEnabled, machineCode
    ):
        if self._finished:
            return
        self._remaining = remaining
        self._limit = limit
        self._cost = cost
        self._peakEnabled = peakEnabled
        if machineCode:
            cfg.set(cfg.aiMarkdownMachineCode, machineCode)
        self._updateQuotaLabel()
        self._refreshStartButton()

    def _onConversionFinished(self, remaining, limit, cost):
        self._flushTimer.stop()
        self._flushChunks()
        if not self._result.strip():
            self._onConversionFailed(
                "AI 没有返回内容，请重试。", remaining, limit, cost
            )
            return

        self._running = False
        self._finished = True
        self._quotaTimer.stop()
        self._remaining = remaining
        self._limit = limit
        self._cost = cost
        self._stopBusyStyle()
        self._updateQuotaLabel()
        self.yesButton.setText("使用结果")
        self.yesButton.setEnabled(True)
        self.cancelButton.setEnabled(True)
        self.cancelButton.setText("取消")

    def _onConversionFailed(self, message, remaining, limit, cost):
        self._flushTimer.stop()
        self._pendingChunks.clear()
        self._resultChunks.clear()
        self._result = ""
        self._running = False
        if remaining >= 0:
            self._remaining = remaining
            self._limit = limit
            self._cost = cost
        self._remaining = None
        self._stopBusyStyle()
        self.inputEdit.setPlainText(self._source)
        self.inputEdit.setReadOnly(False)
        self.cancelButton.setEnabled(True)
        self.cancelButton.setText("取消")
        self._updateQuotaLabel()
        self._refreshStartButton()
        self._refreshQuota()
        dialog = MessageBox("转换失败", message, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _updateQuotaLabel(self):
        if self._remaining is None:
            remaining = "正在查询"
        elif self._remaining < 0:
            remaining = "暂时无法获取"
        else:
            remaining = self._remaining
        quotaParts = [
            f"剩余 {remaining}/{self._limit}",
            f"当前每次扣 {self._cost} 点",
        ]
        if self._peakEnabled:
            quotaParts.append(f"双倍时段：{PEAK_HOURS_TEXT}")
        quotaParts.extend(("每天 0 点刷新", "禁止滥用", "设置中可自定义风格"))
        self.quotaLabel.setText("　·　".join(quotaParts))

    def _refreshStartButton(self):
        if not self._running and not self._finished:
            self.yesButton.setEnabled(
                bool(self.inputEdit.toPlainText().strip())
                and self._remaining is not None
                and self._remaining >= self._cost
            )

    def _updateBusyStyle(self):
        hue = self._borderIndex % 360
        colors = [
            QColor.fromHsv((hue + offset) % 360, 190, 255).name()
            for offset in (0, 90, 180, 270, 360)
        ]
        stops = ", ".join(
            f"stop:{index / 4:g} {color}" for index, color in enumerate(colors)
        )
        self._borderIndex = (hue + 6) % 360
        background = "#343434" if isDarkTheme() else "#E8E8E8"
        self.inputEdit.setStyleSheet(
            f"QTextEdit {{ background: {background}; border: 2px solid; "
            f"border-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, {stops}); "
            "border-radius: 8px; }"
        )

    def _stopBusyStyle(self):
        self._busyTimer.stop()
        self.inputEdit.setStyleSheet(self._inputStyle)

    def _stopTimers(self):
        self._busyTimer.stop()
        self._quotaTimer.stop()
        self._flushTimer.stop()

    def done(self, result):
        if self._running:
            self._cancelConversion()
        self._stopTimers()
        super().done(result)

    def closeEvent(self, event):
        if self._running:
            self._cancelConversion()
        self._stopTimers()
        super().closeEvent(event)


class BroadcastEditPage(QWidget):
    backSignal = Signal()
    editSignal = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)

        topLayout = QHBoxLayout()
        self.backBtn = ToolButton(FIF.RETURN, self)
        self.backBtn.clicked.connect(self._onBack)
        self.pageTitle = TitleLabel("全屏投送编辑器", self)

        self.markdownCheckBox = CheckBox("使用 Markdown 语法", self)
        self.markdownCheckBox.setChecked(cfg.broadcastMarkdownEnabled.value)
        self.markdownCheckBox.stateChanged.connect(self._onMarkdownStateChanged)

        topLayout.addWidget(self.backBtn)
        topLayout.addWidget(self.pageTitle)
        topLayout.addStretch(1)
        topLayout.addWidget(self.markdownCheckBox)
        self.vBoxLayout.addLayout(topLayout)

        self.titleInput = LineEdit(self)
        self.titleInput.setPlaceholderText("在此输入大标题")
        font = QFont(); font.setPointSize(20)
        self.titleInput.setFont(font)
        self.titleInput.setFixedHeight(48)
        self.vBoxLayout.addWidget(self.titleInput)

        self.contentInput = TextEdit(self)
        self.contentInput.setPlaceholderText("在此输入要投送的正文")
        QScroller.grabGesture(
            self.contentInput.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        self.vBoxLayout.addWidget(self.contentInput)

        btnLayout = QHBoxLayout()
        self.templateBtn = PushButton(self)
        self.templateBtn.setIcon(FIF.DOCUMENT)
        self.templateBtn.setText("导入")
        self.templateBtn.clicked.connect(self._showTemplateMenu)

        self.aiBtn = PushButton(self)
        self.aiBtn.setIcon(QIcon(str(ASSET_DIR / "deepseek.png")))
        self.aiBtn.setText("AI帮改Markdown")
        self.aiBtn.setEnabled(False)
        self.aiBtn.clicked.connect(self._showAIMarkdownDialog)

        self.broadcastBtn = PrimaryPushButton(self)
        self.broadcastBtn.setIcon(FIF.SEND)
        self.broadcastBtn.setText("投送")
        self.broadcastBtn.setMinimumWidth(200)
        self.broadcastBtn.clicked.connect(self._onBroadcast)

        btnLayout.addWidget(self.templateBtn)
        btnLayout.addWidget(self.aiBtn)
        btnLayout.addStretch(1)
        btnLayout.addWidget(self.broadcastBtn)
        self.vBoxLayout.addLayout(btnLayout)
        self._updateMarkdownUi()

        self.broadcastWin = BroadcastWindow()
        self.broadcastWin.editClicked.connect(self._onReturnToEdit)
        self.broadcastWin.closeClicked.connect(self._onReturnToHome)
        self._activeBroadcast = None

    def _onMarkdownStateChanged(self, state):
        cfg.set(
            cfg.broadcastMarkdownEnabled,
            self.markdownCheckBox.isChecked(),
        )
        self._updateMarkdownUi()

    def _updateMarkdownUi(self):
        if self.markdownCheckBox.isChecked():
            self.contentInput.setPlaceholderText("支持Markdown语法（注意，在该模式下换行要换两次）")
        else:
            self.contentInput.setPlaceholderText("在此输入要投送的正文")
        self.aiBtn.setEnabled(self.markdownCheckBox.isChecked())

    def _showAIMarkdownDialog(self):
        dialog = AIMarkdownDialog(
            self.contentInput.toPlainText(),
            self.window(),
        )
        try:
            if dialog.exec():
                self.contentInput.setPlainText(dialog.resultText())
        finally:
            dialog.deleteLater()

    def _showTemplateMenu(self):
        menu = RoundMenu(parent=self)
        menu.closedSignal.connect(menu.deleteLater)
        menu.addAction(Action(FIF.DOCUMENT, "中午作业模板", triggered=self._useNoonTemplate))
        menu.addAction(Action(FIF.DOCUMENT, "晚辅导作业模板", triggered=self._useNightTemplate))
        lastBroadcastAction = Action(
            FIF.HISTORY,
            "上次投送内容",
            triggered=self._useLastBroadcast,
        )
        lastBroadcastAction.setEnabled(self._lastBroadcast() is not None)
        menu.addAction(lastBroadcastAction)
        menu.exec(
            self.templateBtn.mapToGlobal(
                QPoint(0, self.templateBtn.height())
            )
        )

    def _useNoonTemplate(self):
        self.titleInput.setText("今日中午作业")
        if self.markdownCheckBox.isChecked():
            self.contentInput.setText("**【数学】**\n- \n---\n**⚠️请值日人员到卫生区打扫⚠️**")
        else:
            self.contentInput.setText("【数学】\n  -\n\n【 ⚠️请值日人员到卫生区打扫⚠️ 】")

    def _useNightTemplate(self):
        self.titleInput.setText("今日晚辅导作业")
        if self.markdownCheckBox.isChecked():
            self.contentInput.setText("**【语文】**\n- \n\n**【英语】**\n- \n\n**【物理】**\n- ")
        else:
            self.contentInput.setText("【语文】\n  -\n\n【英语】\n  -\n\n【物理】\n  -")

    def _lastBroadcast(self):
        broadcast = cfg.lastBroadcast.value
        if not isinstance(broadcast, dict):
            return None
        if (
            not isinstance(broadcast.get("title"), str)
            or not isinstance(broadcast.get("content"), str)
            or not isinstance(broadcast.get("isMarkdown"), bool)
        ):
            return None
        return broadcast

    def _useLastBroadcast(self):
        broadcast = self._lastBroadcast()
        if broadcast is None:
            return False
        self.titleInput.setText(broadcast["title"])
        self.contentInput.setPlainText(broadcast["content"])
        self.markdownCheckBox.setChecked(broadcast["isMarkdown"])
        return True

    def restoreLastBroadcast(self):
        if self._useLastBroadcast():
            self._onBroadcast()

    def _setBroadcastInactive(self):
        broadcast = cfg.lastBroadcast.value
        if isinstance(broadcast, dict) and broadcast.get("active") is True:
            cfg.set(cfg.lastBroadcast, {**broadcast, "active": False})

    def _onBroadcast(self):
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self._activeBroadcast = {
            "title": self.titleInput.text(),
            "content": self.contentInput.toPlainText(),
            "isMarkdown": self.markdownCheckBox.isChecked(),
        }
        cfg.set(cfg.lastBroadcast, {**self._activeBroadcast, "active": True})
        self.broadcastWin.setContent(
            self._activeBroadcast["title"],
            self._activeBroadcast["content"],
            self._activeBroadcast["isMarkdown"],
        )
        self.broadcastWin.startBroadcast()
        self.window().hide()

    def _onReturnToEdit(self):
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self._setBroadcastInactive()
        if self._activeBroadcast is not None:
            self.titleInput.setText(self._activeBroadcast["title"])
            self.contentInput.setPlainText(self._activeBroadcast["content"])
            self.markdownCheckBox.setChecked(
                self._activeBroadcast["isMarkdown"]
            )
        self.editSignal.emit()
        self.window().show(); self.window().raise_(); self.window().activateWindow()

    def _onReturnToHome(self):
        if getattr(self.window(), "_resourcesShutdown", False):
            return
        self._setBroadcastInactive()
        showMainWindow = cfg.showMainWindowAfterBroadcast.value
        QApplication.instance().setQuitOnLastWindowClosed(showMainWindow)
        self.titleInput.clear(); self.contentInput.clear()
        self._activeBroadcast = None
        if showMainWindow:
            self.window().show(); self.window().raise_(); self.window().activateWindow()
        self.backSignal.emit()

    def _onBack(self):
        if self.titleInput.text().strip() or self.contentInput.toPlainText().strip():
            dialog = MessageBox(
                "未投送内容",
                "您还有内容未投送，是否退出？",
                self.window(),
            )
            try:
                confirmed = dialog.exec()
            finally:
                dialog.deleteLater()
            if not confirmed:
                return
        self.titleInput.clear(); self.contentInput.clear()
        self.backSignal.emit()
