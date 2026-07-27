import hashlib
import json
import threading
import uuid

import requests
from PySide6.QtCore import QEvent, QPoint, QSize, QSysInfo, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
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
    LineEdit,
    MessageBox,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SubtitleLabel,
    TextEdit,
    TitleLabel,
    ToolButton,
    isDarkTheme,
    qconfig,
)
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow

from app.config.cfg import cfg
from app.config.constants import AI_MARKDOWN_API
from app.config.paths import ASSET_DIR


class VerticalButton(QToolButton):
    def __init__(self, icon_enum, text, primary=False, parent=None, force_dark=False):
        super().__init__(parent)
        self.primary = primary
        self.icon_enum = icon_enum  # 保存图标枚举，方便变色
        self.force_dark = force_dark  # 纯黑背景窗口（如考试倒计时）固定使用深色样式
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setText(text)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(80, 65)
        self.updateStyle()

    def updateStyle(self):
        theme_color = qconfig.themeColor.value.name()
        is_dark = self.force_dark or (isDarkTheme() if cfg.customThemeMode.value == "System" else cfg.customThemeMode.value == "Dark")

        if self.primary:
            # 主题色背景需要固定高对比前景。
            self.setStyleSheet(f"QToolButton {{ background-color: {theme_color}; color: white; border-radius: 8px; border: none; font-size: 13px; padding-top: 6px; padding-bottom: 4px;}} QToolButton:hover {{ opacity: 0.8; }}")
            self.setIcon(self.icon_enum.icon(color=QColor("white")))
        else:
            bg = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.05)"
            hover_bg = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.1)"
            color_str = "white" if is_dark else "black"
            self.setStyleSheet(f"QToolButton {{ background-color: {bg}; color: {color_str}; border-radius: 8px; border: none; font-size: 13px; padding-top: 6px; padding-bottom: 4px;}} QToolButton:hover {{ background-color: {hover_bg}; }}")
            self.setIcon(self.icon_enum.icon(color=QColor(color_str)))

    def setWindowed(self, windowed: bool):
        if windowed:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.setFixedSize(50, 40)
        else:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            self.setFixedSize(80, 65)

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

    def __init__(self):
        super().__init__()
        self.setObjectName("BroadcastWindow")
        self.titleBar.hide()
        # 顶层窗口的 QSS 边框需要该属性才会绘制
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self._is_editing = False
        self._isTracking = False

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(40, 20, 40, 20)

        self.titleLabel = TitleLabel(self)
        font = QFont(); font.setPointSize(48); font.setBold(True)
        self.titleLabel.setFont(font)

        self.contentEdit = QTextEdit(self)
        self.contentEdit.setReadOnly(True)
        self.contentEdit.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.contentEdit.setStyleSheet("border: none; background: transparent;")
        self.contentEdit.viewport().installEventFilter(self)

        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.vBoxLayout.addWidget(self.contentEdit, 1)

        self.btnContainer = QWidget(self)
        self.btnLayout = QHBoxLayout(self.btnContainer)
        self.btnLayout.setContentsMargins(0, 0, 0, 0)
        self.btnLayout.setSpacing(12)

        self.is_windowed = False
        self.miniWindow = FloatingMiniWindow()
        self.miniWindow.restoreSignal.connect(self.restoreFromMini)

        self.btn_edit = VerticalButton(FIF.EDIT, "编辑")
        self.btn_min = VerticalButton(FIF.MINIMIZE, "最小化")
        self.btn_win = VerticalButton(FIF.FULL_SCREEN, "窗口化")
        self.btn_close = VerticalButton(FIF.CLOSE, "关闭", primary=True)

        self.btn_edit.clicked.connect(self._onEdit)
        self.btn_min.clicked.connect(self.minimizeToMini)
        self.btn_win.clicked.connect(self.toggleWindowMode)
        self.btn_close.clicked.connect(self.close)

    def eventFilter(self, obj, event):
        if obj == self.contentEdit.viewport():
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if self.is_windowed:
                    self._isTracking = True
                    self._dragPos = event.globalPosition().toPoint() - self.pos()
                    return True
            elif event.type() == QEvent.Type.MouseMove and getattr(self, '_isTracking', False):
                if self.is_windowed:
                    self.move(event.globalPosition().toPoint() - self._dragPos)
                    return True
            elif event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._isTracking = False
        return super().eventFilter(obj, event)

    def _applyStyle(self):
        is_dark = isDarkTheme() if cfg.customThemeMode.value == "System" else cfg.customThemeMode.value == "Dark"
        bg_color = "#202020" if is_dark else "#FFFFFF"
        text_color = "white" if is_dark else "black"
        border = "border: 1px solid #808080;" if self.is_windowed else ""
        self.setStyleSheet(f"BroadcastWindow {{ background-color: {bg_color}; {border} }} QTextEdit {{ color: {text_color}; }}")

    def setContent(self, title, text, is_markdown=False):
        self._applyStyle()

        self.btn_edit.updateStyle()
        self.btn_min.updateStyle()
        self.btn_win.updateStyle()
        self.btn_close.updateStyle()

        self.titleLabel.setText(title)
        self.titleLabel.setStyleSheet(f"color: {qconfig.themeColor.value.name()};")

        if is_markdown:
            self.contentEdit.setMarkdown(text)
        else:
            self.contentEdit.setPlainText(text)

        font = QFont(); font.setPointSize(26)
        self.contentEdit.setFont(font)

    def setupLayout(self):
        while self.btnLayout.count():
            item = self.btnLayout.takeAt(0)
            if item.widget(): self.btnLayout.removeWidget(item.widget())

        widgets = [self.btn_edit, self.btn_min, self.btn_win, self.btn_close]
        if cfg.actionButtonPosition.value == "左下角":
            widgets.reverse()

        for w in widgets: self.btnLayout.addWidget(w)

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
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
        if cfg.actionButtonPosition.value == "右下角":
            self.miniWindow.move(rect.width() - 150, rect.height() - 150)
        else:
            self.miniWindow.move(50, rect.height() - 150)

    def restoreFromMini(self):
        self.miniWindow.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def _onEdit(self):
        self._is_editing = True
        self.close()

    def closeEvent(self, event):
        if self._is_editing: self.editClicked.emit()
        else: self.closeClicked.emit()
        self._is_editing = False
        super().closeEvent(event)

    def mousePressEvent(self, e):
        if self.is_windowed and e.button() == Qt.MouseButton.LeftButton:
            self._isTracking = True
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


def _machineId():
    raw = bytes(QSysInfo.machineUniqueId())
    if not raw:
        raw = uuid.getnode().to_bytes(6, "big")
    return hashlib.sha256(raw).hexdigest()


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
    quotaReceived = Signal(int, int)
    chunkReceived = Signal(str)
    conversionFinished = Signal(int, int)
    conversionFailed = Signal(str, int, int)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._source = text
        self._result = ""
        self._running = False
        self._finished = False
        self._remaining = None
        self._limit = 15
        self._borderIndex = 0

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
        self.quotaLabel = CaptionLabel(self)

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
        self._updateQuotaLabel()
        self._refreshStartButton()
        threading.Thread(target=self._fetchQuota, daemon=True).start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "widget"):
            self.widget.setFixedWidth(min(680, max(0, event.size().width() - 80)))

    def resultText(self):
        return self._result

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
        if not self._running:
            super().reject()

    def _fetchQuota(self):
        try:
            response = requests.get(
                f"{AI_MARKDOWN_API}/quota",
                params={"machine_id": _machineId()},
                timeout=5,
            )
            response.raise_for_status()
            quota = response.json()
            self.quotaReceived.emit(quota["remaining"], quota["limit"])
        except (requests.RequestException, KeyError, TypeError, ValueError):
            pass

    def _startConversion(self):
        self._running = True
        self._result = ""
        self.inputEdit.clear()
        self.inputEdit.setReadOnly(True)
        self.yesButton.setEnabled(False)
        self.cancelButton.setEnabled(False)
        self._busyTimer.start()
        self._updateBusyStyle()
        threading.Thread(target=self._streamConversion, daemon=True).start()

    def _streamConversion(self):
        remaining = self._remaining if self._remaining is not None else -1
        limit = self._limit
        try:
            with requests.post(
                AI_MARKDOWN_API,
                json={"content": self._source, "machine_id": _machineId()},
                stream=True,
                timeout=(10, 120),
            ) as response:
                remaining = int(
                    response.headers.get("X-RateLimit-Remaining", remaining)
                )
                limit = int(response.headers.get("X-RateLimit-Limit", limit))
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
                    self.chunkReceived.emit(chunk)
            self.conversionFinished.emit(remaining, limit)
        except requests.RequestException:
            self.conversionFailed.emit(
                "无法连接 AI 服务，请检查网络后重试。",
                remaining,
                limit,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            self.conversionFailed.emit(str(error), remaining, limit)

    def _appendChunk(self, chunk):
        self._result += chunk
        self.inputEdit.moveCursor(QTextCursor.MoveOperation.End)
        self.inputEdit.insertPlainText(chunk)
        self.inputEdit.ensureCursorVisible()

    def _onQuotaReceived(self, remaining, limit):
        if self._finished:
            return
        self._remaining = remaining
        self._limit = limit
        self._updateQuotaLabel()
        self._refreshStartButton()

    def _onConversionFinished(self, remaining, limit):
        if not self._result.strip():
            self._onConversionFailed("AI 没有返回内容，请重试。", remaining, limit)
            return

        self._running = False
        self._finished = True
        self._remaining = remaining
        self._limit = limit
        self._stopBusyStyle()
        self._updateQuotaLabel()
        self.yesButton.setText("使用结果")
        self.yesButton.setEnabled(True)
        self.cancelButton.setEnabled(True)

    def _onConversionFailed(self, message, remaining, limit):
        self._running = False
        if remaining >= 0:
            self._remaining = remaining
            self._limit = limit
        self._stopBusyStyle()
        self.inputEdit.setPlainText(self._source)
        self.inputEdit.setReadOnly(False)
        self.cancelButton.setEnabled(True)
        self._updateQuotaLabel()
        self._refreshStartButton()
        MessageBox("转换失败", message, self).exec()

    def _updateQuotaLabel(self):
        remaining = "正在查询" if self._remaining is None else self._remaining
        self.quotaLabel.setText(
            f"剩余次数：{remaining} / 总次数：{self._limit}　·　禁止滥用"
        )

    def _refreshStartButton(self):
        if not self._running and not self._finished:
            self.yesButton.setEnabled(
                bool(self.inputEdit.toPlainText().strip()) and self._remaining != 0
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
        self.inputEdit.setStyleSheet("")


class BroadcastEditPage(QWidget):
    backSignal = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)

        topLayout = QHBoxLayout()
        self.backBtn = ToolButton(FIF.RETURN, self)
        self.backBtn.clicked.connect(self._onBack)
        self.pageTitle = TitleLabel("全屏投送编辑器", self)

        self.markdownCheckBox = CheckBox("使用 Markdown 语法", self)
        self.markdownCheckBox.setChecked(False)
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
        self.vBoxLayout.addWidget(self.contentInput)

        btnLayout = QHBoxLayout()
        self.templateBtn = PushButton(self)
        self.templateBtn.setIcon(FIF.DOCUMENT)
        self.templateBtn.setText("导入模板")
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

        self.broadcastWin = BroadcastWindow()
        self.broadcastWin.editClicked.connect(self._onReturnToEdit)
        self.broadcastWin.closeClicked.connect(self._onReturnToHome)

    def _onMarkdownStateChanged(self, state):
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
        if dialog.exec():
            self.contentInput.setPlainText(dialog.resultText())

    def _showTemplateMenu(self):
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.DOCUMENT, "中午作业模板", triggered=self._useNoonTemplate))
        menu.addAction(Action(FIF.DOCUMENT, "晚辅导作业模板", triggered=self._useNightTemplate))
        menu.exec(self.templateBtn.mapToGlobal(QPoint(0, self.templateBtn.height())))

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

    def _onBroadcast(self):
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self.broadcastWin.setContent(
            self.titleInput.text(),
            self.contentInput.toPlainText(),
            self.markdownCheckBox.isChecked()
        )
        self.broadcastWin.startBroadcast()
        self.window().hide()

    def _onReturnToEdit(self):
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self.window().show(); self.window().raise_(); self.window().activateWindow()

    def _onReturnToHome(self):
        showMainWindow = cfg.showMainWindowAfterFullscreenTask.value
        QApplication.instance().setQuitOnLastWindowClosed(showMainWindow)
        self.titleInput.clear(); self.contentInput.clear()
        if showMainWindow:
            self.window().show(); self.window().raise_(); self.window().activateWindow()
        self.backSignal.emit()

    def _onBack(self):
        if self.titleInput.text().strip() or self.contentInput.toPlainText().strip():
            w = MessageBox("未投送内容", "您还有内容未投送，是否退出？", self.window())
            if not w.exec(): return
        self.titleInput.clear(); self.contentInput.clear()
        self.backSignal.emit()
