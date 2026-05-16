import sys
from PySide6.QtCore import Qt, Signal, QPoint, QSize, QEvent
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QToolButton, QApplication
from qfluentwidgets import (LineEdit, TextEdit, PrimaryPushButton, PushButton, 
                            TitleLabel, ToolButton, MessageBox, Action, RoundMenu,
                            isDarkTheme, qconfig, CheckBox) # 导入 CheckBox
from qfluentwidgets import FluentIcon as FIF
from qframelesswindow import FramelessWindow

from app.common.config import cfg

class VerticalButton(QToolButton):
    def __init__(self, icon, text, primary=False, parent=None):
        super().__init__(parent)
        self.primary = primary
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIcon(icon.icon())
        self.setText(text)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(80, 65)
        self.updateStyle()
        
    def updateStyle(self):
        theme_color = qconfig.themeColor.value.name()
        is_dark = isDarkTheme() if cfg.customThemeMode.value == "System" else cfg.customThemeMode.value == "Dark"
        if self.primary:
            self.setStyleSheet(f"QToolButton {{ background-color: {theme_color}; color: white; border-radius: 8px; border: none; font-size: 13px; padding-top: 6px; padding-bottom: 4px;}} QToolButton:hover {{ opacity: 0.8; }}")
        else:
            bg = "rgba(255,255,255,0.1)" if is_dark else "rgba(0,0,0,0.05)"
            hover_bg = "rgba(255,255,255,0.15)" if is_dark else "rgba(0,0,0,0.1)"
            color = "white" if is_dark else "black"
            self.setStyleSheet(f"QToolButton {{ background-color: {bg}; color: {color}; border-radius: 8px; border: none; font-size: 13px; padding-top: 6px; padding-bottom: 4px;}} QToolButton:hover {{ background-color: {hover_bg}; }}")
            
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
        layout = QHBoxLayout(self)
        self.btn = VerticalButton(FIF.FULL_SCREEN, "回到全屏投送", primary=True, parent=self)
        self.btn.clicked.connect(self.restoreSignal.emit)
        layout.addWidget(self.btn)
        self.setWindowOpacity(0.5)
        self._dragPos = QPoint()

    def enterEvent(self, event): self.setWindowOpacity(1.0)
    def leaveEvent(self, event): self.setWindowOpacity(0.5)
    def mousePressEvent(self, event): self._dragPos = event.globalPosition().toPoint() - self.pos()
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._dragPos)

class BroadcastWindow(FramelessWindow):
    editClicked = Signal()
    closeClicked = Signal()
    
    def __init__(self):
        super().__init__()
        self.setObjectName("BroadcastWindow")
        self.titleBar.hide()
        self._is_editing = False
        self._isTracking = False
        
        self.vBoxLayout = QVBoxLayout(self)
        # 将底部边距改小，让正文填满底部
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
        
        # === 修改：创建一个独立的悬浮容器存放按钮，不再放入 vBoxLayout ===
        self.btnContainer = QWidget(self)
        self.btnLayout = QHBoxLayout(self.btnContainer)
        self.btnLayout.setContentsMargins(0, 0, 0, 0)
        self.btnLayout.setSpacing(12) # 按钮之间的间距设定为 12
        
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

    def setContent(self, title, text, is_markdown=False):
        is_dark = isDarkTheme() if cfg.customThemeMode.value == "System" else cfg.customThemeMode.value == "Dark"
        bg_color = "#202020" if is_dark else "#FFFFFF"
        text_color = "white" if is_dark else "black"
        self.setStyleSheet(f"BroadcastWindow {{ background-color: {bg_color}; }} QTextEdit {{ color: {text_color}; }}")
        
        self.btn_edit.updateStyle()
        self.btn_min.updateStyle()
        self.btn_win.updateStyle()
        self.btn_close.updateStyle()
        
        self.titleLabel.setText(title)
        self.titleLabel.setStyleSheet(f"color: {qconfig.themeColor.value.name()};")
        
        # 根据开关状态决定渲染方式
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
        
        # === 新增：让容器自适应按钮大小，并更新位置 ===
        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updateBtnPosition()

    def _updateBtnPosition(self):
        # 按钮距离屏幕底边和侧边的距离，设定为等于按钮间距（12）
        margin = self.btnLayout.spacing() 
        
        # 根据设置动态计算悬浮坐标
        if cfg.actionButtonPosition.value == "左下角":
            target_x = margin
        else:
            target_x = self.width() - self.btnContainer.width() - margin
            
        target_y = self.height() - self.btnContainer.height() - margin
        
        self.btnContainer.move(target_x, target_y)
        self.btnContainer.raise_() # 确保按钮图层永远在正文的最上方

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
        self.btn_win.setIcon(FIF.FULL_SCREEN.icon() if self.is_windowed else FIF.COPY.icon())
        
        # === 新增：让悬浮容器重新收缩贴合小尺寸按钮，并更新位置 ===
        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def _applyWindowState(self):
        is_top = cfg.topmostInWindowed.value if self.is_windowed else cfg.topmostInFullscreen.value
        flags = Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
        if is_top: flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        
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
        self.miniWindow.btn.updateStyle()
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
        
        # 新增 Markdown 选项
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
        self.vBoxLayout.addWidget(self.titleInput)
        
        self.contentInput = TextEdit(self)
        # 初始化占位符
        self.contentInput.setPlaceholderText("在此输入要投送的正文")
        self.vBoxLayout.addWidget(self.contentInput)
        
        btnLayout = QHBoxLayout()
        self.templateBtn = PushButton(self)
        self.templateBtn.setIcon(FIF.DOCUMENT)
        self.templateBtn.setText("导入模板")
        self.templateBtn.clicked.connect(self._showTemplateMenu)
        
        self.broadcastBtn = PrimaryPushButton(self)
        self.broadcastBtn.setIcon(FIF.SEND)
        self.broadcastBtn.setText("投送")
        self.broadcastBtn.setMinimumWidth(200)
        self.broadcastBtn.clicked.connect(self._onBroadcast)
        
        btnLayout.addWidget(self.templateBtn)
        btnLayout.addStretch(1)
        btnLayout.addWidget(self.broadcastBtn)
        self.vBoxLayout.addLayout(btnLayout)
        
        self.broadcastWin = BroadcastWindow()
        self.broadcastWin.editClicked.connect(self._onReturnToEdit)
        self.broadcastWin.closeClicked.connect(self._onReturnToHome)

    def _onMarkdownStateChanged(self, state):
        # 切换占位符提示内容
        if self.markdownCheckBox.isChecked():
            self.contentInput.setPlaceholderText("支持Markdown语法（注意，在该模式下换行要换两次）")
        else:
            self.contentInput.setPlaceholderText("在此输入要投送的正文")

    def _showTemplateMenu(self):
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FIF.DOCUMENT, "中午作业模板", triggered=self._useNoonTemplate))
        menu.addAction(Action(FIF.DOCUMENT, "晚辅导作业模板", triggered=self._useNightTemplate))
        menu.exec(self.templateBtn.mapToGlobal(QPoint(0, self.templateBtn.height())))

    def _useNoonTemplate(self):
        self.titleInput.setText("今日中午作业")
        if self.markdownCheckBox.isChecked():
            # Markdown 模式
            self.contentInput.setText("**【数学】**\n- \n---\n**⚠️请值日人员到卫生区打扫⚠️**")
        else:
            # 普通文本模式
            self.contentInput.setText("【数学】\n  -\n\n【 ⚠️请值日人员到卫生区打扫⚠️ 】")

    def _useNightTemplate(self):
        self.titleInput.setText("今日晚辅导作业")
        if self.markdownCheckBox.isChecked():
            # Markdown 模式
            self.contentInput.setText("**【语文】**\n- \n\n**【数学】**\n- \n\n**【英语】**\n- ")
        else:
            # 普通文本模式
            self.contentInput.setText("【语文】\n  -\n\n【英语】\n  -\n\n【物理】\n  -")

    def _onBroadcast(self):
        QApplication.instance().setQuitOnLastWindowClosed(False)
        # 将 CheckBox 状态传入窗口
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
        QApplication.instance().setQuitOnLastWindowClosed(True)
        self.titleInput.clear(); self.contentInput.clear()
        self.window().show(); self.window().raise_(); self.window().activateWindow()
        self.backSignal.emit()

    def _onBack(self):
        if self.titleInput.text().strip() or self.contentInput.toPlainText().strip():
            w = MessageBox("未投送内容", "您还有内容未投送，是否退出？", self.window())
            if not w.exec(): return
        self.titleInput.clear(); self.contentInput.clear()
        self.backSignal.emit()
