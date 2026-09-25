import json
import sys
import threading

import requests
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QSize, Qt, QTimer, Signal
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

if sys.platform == "win32":
    from ctypes.wintypes import MSG

    import win32con
    import win32gui

from app.common.ai_markdown import PEAK_HOURS_TEXT, fetchQuota, machineId
from app.common.update_download import isHttpsResponseChain
from app.config.cfg import cfg
from app.config.constants import AI_MARKDOWN_API
from app.config.paths import ASSET_DIR
from app.platform.screens import screenFor
from app.view.components.busy_glow import BusyGlowOverlay
from app.view.components.markdown_view import MarkdownView
from app.view.components.scroll_area import setTouchScrollSuppressed
from app.view.components.window_background import (
    WINDOW_SHADOW_MARGIN,
    WindowBackground,
    projectionThemeBackground,
    projectionTitleColor,
)


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


def placeCornerButtons(container, rect, atLeft):
    """Pin the corner action buttons inside rect, one layout spacing from its edges."""
    margin = container.layout().spacing()
    if atLeft:
        x = rect.left() + margin
    else:
        x = rect.right() + 1 - container.width() - margin
    container.move(x, rect.bottom() + 1 - container.height() - margin)
    container.raise_()


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
    def _initVerticalButton(self, iconEnum, text, primary, forceDark):
        self.iconEnum = iconEnum
        self._buttonText = text
        self._primary = primary
        self.forceDark = forceDark
        self._windowed = False
        self.setIcon(QIcon())
        self.setText(text)
        self.setIconSize(QSize(20, 20))
        self.setFixedSize(80, 65)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.updateStyle()

    def updateStyle(self):
        dark = self.forceDark or isDarkTheme()
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
        icon = self.iconEnum.icon(color=color)
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
        dark = self.forceDark or isDarkTheme()
        return QColor("white") if self._primary or dark else QColor("black")


class _VerticalPushButton(_VerticalButtonMixin, PushButton):
    def __init__(self, iconEnum, text, parent=None, forceDark=False):
        super().__init__(parent)
        self._initVerticalButton(iconEnum, text, False, forceDark)


class _VerticalPrimaryPushButton(_VerticalButtonMixin, PrimaryPushButton):
    def __init__(self, iconEnum, text, parent=None, forceDark=False):
        super().__init__(parent)
        self._initVerticalButton(iconEnum, text, True, forceDark)


def VerticalButton(
    iconEnum,
    text,
    primary=False,
    parent=None,
    forceDark=False,
):
    buttonType = _VerticalPrimaryPushButton if primary else _VerticalPushButton
    return buttonType(
        iconEnum,
        text,
        parent=parent,
        forceDark=forceDark,
    )


class _BroadcastContentDragFilter(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window

    def eventFilter(self, obj, event):
        return self.window._filterContentDragEvent(obj, event)


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
        themeColor = qconfig.themeColor.value.name()
        self.btn.setStyleSheet(f"""
            QToolButton {{
                background-color: {themeColor};
                border-radius: 30px;
                border: none;
            }}
            QToolButton:hover {{
                background-color: {themeColor};
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
                self._dragPos = event.globalPosition().toPoint() - self.pos()
                return True
            elif event.type() == QEvent.Type.MouseMove and event.buttons() == Qt.MouseButton.LeftButton:
                if not self._dragPos.isNull():
                    # 手抖不算拖动
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
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._isEditing = False
        self._isTracking = False
        self._contentDragFilterInstalled = False
        self._contentDragActive = False
        self._contentDragStart = QPoint()
        self._contentDragOffset = QPoint()
        self._contentDragMoved = False
        self._contentDragFilter = _BroadcastContentDragFilter(self)
        self._contentDragDistances = {}
        self._closeFlyout = None
        self.background = WindowBackground(
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            projectionThemeBackground,
            self,
        )
        self.background.lower()
        self.background.setGeometry(self.contentsRect())
        qconfig.themeChanged.connect(self.background.refresh)

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

        self.isWindowed = False
        self.miniWindow = FloatingMiniWindow(self)
        self.miniWindow.restoreSignal.connect(self.restoreFromMini)

        self.btnEdit = VerticalButton(FIF.EDIT, "编辑")
        self.btnMin = VerticalButton(FIF.MINIMIZE, "最小化")
        self.btnWin = VerticalButton(FIF.FULL_SCREEN, "窗口化")
        self.btnClose = VerticalButton(FIF.CLOSE, "关闭", primary=True)

        self.btnEdit.clicked.connect(self._onEdit)
        self.btnMin.clicked.connect(self.minimizeToMini)
        self.btnWin.clicked.connect(self.toggleWindowMode)
        self.btnClose.clicked.connect(self._onClose)

    def _applyStyle(self):
        isDark = isDarkTheme()
        textColor = "white" if isDark else "black"
        margin = WINDOW_SHADOW_MARGIN if self.isWindowed else 0
        self.setContentsMargins(margin, margin, margin, margin)
        self.background.setRoundedWindow(self.isWindowed)
        self.background.setGeometry(self.contentsRect())
        self.setStyleSheet(f"BroadcastWindow {{ background-color: transparent; }} QTextEdit {{ color: {textColor}; background: transparent; }}")

    def setContent(self, title, text, isMarkdown=False):
        self._applyStyle()

        self.btnEdit.updateStyle()
        self.btnMin.updateStyle()
        self.btnWin.updateStyle()
        self.btnClose.updateStyle()

        self.titleLabel.setText(title)
        self.titleLabel.setStyleSheet(f"color: {projectionTitleColor().name()};")

        if isMarkdown:
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

        widgets = [self.btnEdit, self.btnMin, self.btnWin, self.btnClose]
        if cfg.broadcastActionButtonPosition.value == "左下角":
            widgets.reverse()

        for w in widgets: self.btnLayout.addWidget(w)

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.background.setGeometry(self.contentsRect())
        self._updateBtnPosition()

    def _updateBtnPosition(self):
        placeCornerButtons(
            self.btnContainer,
            self.contentsRect(),
            cfg.broadcastActionButtonPosition.value == "左下角",
        )

    def startBroadcast(self):
        self.isWindowed = False
        self.setupLayout()
        self._updateButtonsState()
        self._applyWindowState()

    def toggleWindowMode(self):
        self.isWindowed = not self.isWindowed
        self._updateButtonsState()
        self._applyWindowState()

    def _updateButtonsState(self):
        self.btnEdit.setWindowed(self.isWindowed)
        self.btnMin.setWindowed(self.isWindowed)
        self.btnWin.setWindowed(self.isWindowed)
        self.btnClose.setWindowed(self.isWindowed)

        self.btnWin.iconEnum = FIF.FULL_SCREEN if self.isWindowed else FIF.COPY
        self.btnWin.updateStyle()

        self.btnContainer.adjustSize()
        self._updateBtnPosition()

    def _applyWindowState(self):
        isTop = cfg.topmostInWindowed.value if self.isWindowed else cfg.topmostInFullscreen.value
        flags = (
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if isTop: flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # 全屏时禁用系统边缘拉伸，避免鼠标在屏幕边缘仍能调整窗口大小
        self.setResizeEnabled(self.isWindowed)
        self._updateContentInteraction()
        self._applyStyle()

        if self.isWindowed:
            self.showNormal()
            rect = screenFor(self).availableGeometry()
            margin = WINDOW_SHADOW_MARGIN
            self.resize(int(rect.width() * 0.5) + 2 * margin, int(rect.height() * 0.5) + 2 * margin)
            self.move(rect.center() - self.rect().center())
        else:
            if cfg.showTaskbarInBroadcast.value:
                self.showNormal()
                self.setGeometry(screenFor(self).availableGeometry())
            else:
                self.showFullScreen()

        self.show()
        self.raise_()
        self.activateWindow()

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and getattr(self, "isWindowed", False):
            msg = MSG.from_address(int(message))
            if msg.message == win32con.WM_NCHITTEST:
                if not self._isResizeEnabled or self.isMaximized() or self.isFullScreen():
                    return True, win32con.HTCLIENT
                # 消息坐标包含负坐标屏幕和触控位置，不能用鼠标光标位置代替。
                x = (msg.lParam & 0xFFFF) - (0x10000 if msg.lParam & 0x8000 else 0)
                y = ((msg.lParam >> 16) & 0xFFFF) - (0x10000 if msg.lParam & 0x80000000 else 0)
                x, y = win32gui.ScreenToClient(msg.hWnd, (x, y))
                scale = self.devicePixelRatioF()
                position = QPointF(x / scale, y / scale) - self.background.pos()
                edges = self.background.resizeEdges(position, self.BORDER_WIDTH)
                hitTests = {
                    Qt.Edge.LeftEdge: win32con.HTLEFT,
                    Qt.Edge.RightEdge: win32con.HTRIGHT,
                    Qt.Edge.TopEdge: win32con.HTTOP,
                    Qt.Edge.BottomEdge: win32con.HTBOTTOM,
                    Qt.Edge.TopEdge | Qt.Edge.LeftEdge: win32con.HTTOPLEFT,
                    Qt.Edge.TopEdge | Qt.Edge.RightEdge: win32con.HTTOPRIGHT,
                    Qt.Edge.BottomEdge | Qt.Edge.LeftEdge: win32con.HTBOTTOMLEFT,
                    Qt.Edge.BottomEdge | Qt.Edge.RightEdge: win32con.HTBOTTOMRIGHT,
                }
                return True, hitTests.get(edges, win32con.HTCLIENT)
        return super().nativeEvent(eventType, message)

    def _updateContentInteraction(self):
        application = QApplication.instance()
        # 两个正文 viewport 在构造时各抓一次触控手势，之后只调拖动阈值让出触控：
        # 抓了又放会在 Qt 的手势管理器里留下残留，之后创建窗口时崩溃。
        for viewport in self._contentViewports():
            self._contentDragDistances[viewport] = setTouchScrollSuppressed(
                viewport,
                self.isWindowed,
                self._contentDragDistances.get(viewport),
            )
        if self.isWindowed:
            if application is not None and not self._contentDragFilterInstalled:
                application.installEventFilter(self._contentDragFilter)
                self._contentDragFilterInstalled = True
        else:
            self._removeContentDragFilter()

    def _contentViewports(self):
        return self.contentEdit.viewport(), self.markdownView.viewport()

    def _removeContentDragFilter(self):
        if not self._contentDragFilterInstalled:
            return
        application = QApplication.instance()
        if application is not None:
            application.removeEventFilter(self._contentDragFilter)
        self._contentDragFilterInstalled = False
        self._resetContentDrag()

    @staticmethod
    def _containsWidget(root, widget):
        return widget is root or root.isAncestorOf(widget)

    def _isContentWidget(self, widget):
        if not isinstance(widget, QWidget):
            return False
        return any(
            self._containsWidget(view, widget)
            for view in (self.contentEdit, self.markdownView)
        )

    def _isContentScrollBar(self, widget):
        if not isinstance(widget, QWidget):
            return False
        scrollBars = (
            self.contentEdit.verticalScrollBar(),
            self.markdownView._scroll.verticalScrollBar(),
        )
        return any(self._containsWidget(scrollBar, widget) for scrollBar in scrollBars)

    def _beginContentDrag(self, globalPosition):
        self._contentDragActive = True
        self._contentDragStart = globalPosition
        self._contentDragOffset = globalPosition - self.pos()
        self._contentDragMoved = False

    def _resetContentDrag(self):
        self._contentDragActive = False
        self._contentDragStart = QPoint()
        self._contentDragOffset = QPoint()
        self._contentDragMoved = False

    def _filterContentDragEvent(self, obj, event):
        if not self.isWindowed:
            return False

        eventType = event.type()
        if (
            eventType == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._contentDragActive
        ):
            moved = self._contentDragMoved
            self._resetContentDrag()
            return moved

        if eventType == QEvent.Type.MouseMove and self._contentDragActive:
            globalPosition = event.globalPosition().toPoint()
            if (
                not self._contentDragMoved
                and (globalPosition - self._contentDragStart).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                self._contentDragMoved = True
            if self._contentDragMoved:
                self.move(globalPosition - self._contentDragOffset)
                return True
            return False

        if not self._isContentWidget(obj) or self._isContentScrollBar(obj):
            return False

        if eventType == QEvent.Type.Wheel:
            return True
        if (
            eventType == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._beginContentDrag(event.globalPosition().toPoint())

        return False

    def minimizeToMini(self):
        self.hide()
        self.miniWindow._updateStyle()
        self.miniWindow.show()
        rect = screenFor(self).availableGeometry()
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
        self._isEditing = True
        self.close()

    def _onClose(self):
        if not cfg.confirmBeforeCloseBroadcast.value:
            self.close()
            return
        if self._closeFlyout is not None:
            return
        self._closeFlyout = showCloseConfirmation(
            self,
            self.btnClose,
            "关闭后可通过“导入”恢复上次投送内容。",
        )

    def closeEvent(self, event):
        self._removeContentDragFilter()
        if self._closeFlyout is not None:
            self._closeFlyout.hide()
            self._closeFlyout.deleteLater()
            self._closeFlyout = None
        self.contentEdit.clear()
        self.markdownView.clear()
        self.miniWindow.hide()
        if self._isEditing: self.editClicked.emit()
        else: self.closeClicked.emit()
        self._isEditing = False
        super().closeEvent(event)

    def mousePressEvent(self, e):
        if self.isWindowed and e.button() == Qt.MouseButton.LeftButton:
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
        if self.isWindowed and getattr(self, '_isTracking', False):
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
                raise RuntimeError("AI 整理未正常完成，请重试。")
            finished = finishReason == "stop" or finished
            content = choice.get("delta", {}).get("content")
            if content:
                yield content

    raise RuntimeError("AI 服务流式响应未正常结束，请重试。")


def _emitSignal(signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:
        pass


def _streamAIMarkdown(request, emitChunk):
    remaining = request._remaining if request._remaining is not None else -1
    limit = request._limit
    cost = request._cost
    payload = {"content": request._source, "machine_id": machineId()}
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
        with request._responseLock:
            if request._cancelEvent.is_set():
                response.close()
                return
            request._activeResponse = response
        with response:
            remaining = int(
                response.headers.get("X-RateLimit-Remaining", remaining)
            )
            limit = int(response.headers.get("X-RateLimit-Limit", limit))
            cost = int(response.headers.get("X-RateLimit-Cost", cost))
            if not response.ok:
                # 该怪谁只有服务端知道（它看得到 DeepSeek 怎么回的），所以有服务端的
                # 原因就照原样显示。服务端的错误都带 JSON；拿不到 JSON 的 5xx 是前面的
                # 反向代理在替已经挂掉的服务端回话。
                try:
                    message = response.json().get("message")
                except (AttributeError, ValueError):
                    message = None
                if message:
                    raise RuntimeError(message)
                if response.status_code in (502, 503, 504):
                    raise RuntimeError("电教猫 Pro 基础服务器已离线，请等待修复。")
                raise RuntimeError(f"AI 服务暂时不可用（{response.status_code}）")

            response.encoding = "utf-8"
            for chunk in _iterSseContent(
                response.iter_lines(chunk_size=1, decode_unicode=True)
            ):
                if request._cancelEvent.is_set():
                    return
                emitChunk(chunk)
        if request._cancelEvent.is_set():
            return
        _emitSignal(request.conversionFinished, remaining, limit, cost)
    except requests.RequestException:
        if request._cancelEvent.is_set():
            return
        # 一个回应都没收到：可能是服务器离线，也可能是这台电脑自己没网。
        _emitSignal(
            request.conversionFailed,
            "无法连接电教猫 Pro 服务器。请先检查这台电脑的网络；"
            "网络正常时，可能是服务器暂时离线。",
            remaining,
            limit,
            cost,
        )
    except (RuntimeError, TypeError, ValueError) as error:
        if request._cancelEvent.is_set():
            return
        _emitSignal(
            request.conversionFailed,
            str(error),
            remaining,
            limit,
            cost,
        )
    finally:
        with request._responseLock:
            if request._activeResponse is response:
                request._activeResponse = None
        if response is not None:
            response.close()


class _AIMarkdownRequest(QObject):
    chunkReceived = Signal(str)
    conversionFinished = Signal(int, int, int)
    conversionFailed = Signal(str, int, int, int)
    stopped = Signal()

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self._source = source
        self._remaining = None
        self._limit = 15
        self._cost = 1
        self._cancelEvent = threading.Event()
        self._responseLock = threading.Lock()
        self._activeResponse = None
        self._resultChunks = []

    def start(self):
        threading.Thread(target=self._stream, daemon=True).start()

    def cancel(self):
        self._cancelEvent.set()
        with self._responseLock:
            response = self._activeResponse
        if response is not None:
            threading.Thread(target=response.close, daemon=True).start()

    def resultText(self):
        return "".join(self._resultChunks)

    def _stream(self):
        def emitChunk(chunk):
            self._resultChunks.append(chunk)
            _emitSignal(self.chunkReceived, chunk)

        try:
            _streamAIMarkdown(self, emitChunk)
        finally:
            _emitSignal(self.stopped)


class AIMarkdownDialog(MessageBoxBase):
    quotaReceived = Signal(int, int, int, object, str)

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
        self._quotaRequestRunning = False
        self._request = None
        self._pendingChunks = []

        self.titleLabel = SubtitleLabel("AI 整理 Markdown", self)
        self.descriptionLabel = BodyLabel(
            "将作业清单或任务填入下面的输入框，即可整理为标准 Markdown 格式。",
            self,
        )
        self.descriptionLabel.setWordWrap(True)
        self.inputEdit = TextEdit(self)
        self.inputEdit.setPlainText(text)
        self.inputEdit.setPlaceholderText("在此输入要整理的内容")
        self.inputEdit.setMinimumHeight(120)
        QScroller.grabGesture(
            self.inputEdit.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        self.quotaLabel = CaptionLabel(self)
        self.quotaLabel.setWordWrap(True)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descriptionLabel)
        self.viewLayout.addWidget(self.inputEdit)
        self.viewLayout.addWidget(self.quotaLabel)
        self.widget.setFixedWidth(min(680, max(0, self.width() - 80)))
        self._glow = BusyGlowOverlay(self.inputEdit)

        self.yesButton.setText("开始整理")
        self.cancelButton.setText("取消")
        self.inputEdit.textChanged.connect(self._refreshStartButton)
        self.quotaReceived.connect(self._onQuotaReceived)

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
        self._pendingChunks.clear()
        self.inputEdit.clear()
        self.inputEdit.setReadOnly(True)
        self.yesButton.setEnabled(False)
        self.cancelButton.setEnabled(True)
        self.cancelButton.setText("取消整理")
        self._glow.start()
        request = _AIMarkdownRequest(self._source, self)
        request.chunkReceived.connect(self._appendChunk)
        request.conversionFinished.connect(self._onConversionFinished)
        request.conversionFailed.connect(self._onConversionFailed)
        request.stopped.connect(request.deleteLater)
        self._request = request
        request.start()

    def _appendChunk(self, chunk):
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
        if self._request is not None:
            self._request.cancel()
            self._request = None
        self._running = False
        self._glow.stop()

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
        self._request = None
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
        self._glow.stop()
        self._updateQuotaLabel()
        self.yesButton.setText("使用结果")
        self.yesButton.setEnabled(True)
        self.cancelButton.setEnabled(True)
        self.cancelButton.setText("取消")

    def _onConversionFailed(self, message, remaining, limit, cost):
        self._request = None
        self._flushTimer.stop()
        self._pendingChunks.clear()
        self._result = ""
        self._running = False
        if remaining >= 0:
            self._remaining = remaining
            self._limit = limit
            self._cost = cost
        self._remaining = None
        self._glow.stop()
        self.inputEdit.setPlainText(self._source)
        self.inputEdit.setReadOnly(False)
        self.cancelButton.setEnabled(True)
        self.cancelButton.setText("取消")
        self._updateQuotaLabel()
        self._refreshStartButton()
        self._refreshQuota()
        dialog = MessageBox("整理失败", message, self)
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

    def _stopTimers(self):
        self._glow.stop(immediate=True)
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
        self._inlineAIRequest = None
        self._inlineAISnapshot = None
        self._inlineAIPendingChunks = []
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)

        topLayout = QHBoxLayout()
        self.backBtn = ToolButton(FIF.RETURN, self)
        self.backBtn.clicked.connect(self._onBack)
        self.pageTitle = TitleLabel("全屏投送编辑器", self)

        self.markdownCheckBox = CheckBox("使用 Markdown 语法", self)
        self.markdownCheckBox.setChecked(cfg.broadcastMarkdownEnabled.value)
        self.markdownCheckBox.stateChanged.connect(self._onMarkdownStateChanged)

        self.organizeCheckBox = CheckBox("整理并投送", self)
        self.organizeCheckBox.setChecked(
            cfg.organizeMarkdownBeforeBroadcast.value
        )
        self.organizeCheckBox.stateChanged.connect(
            self._onOrganizeStateChanged
        )

        topLayout.addWidget(self.backBtn)
        topLayout.addWidget(self.pageTitle)
        topLayout.addStretch(1)
        topLayout.addWidget(self.organizeCheckBox)
        topLayout.addWidget(self.markdownCheckBox)
        self.vBoxLayout.addLayout(topLayout)

        self.titleInput = LineEdit(self)
        self.titleInput.setPlaceholderText("在此输入大标题")
        font = QFont(); font.setPointSize(20)
        self.titleInput.setFont(font)
        self.titleInput.setFixedHeight(48)
        self.titleInput.setText(cfg.broadcastTitle.value)
        self.titleInput.editingFinished.connect(self._saveTitle)
        self.vBoxLayout.addWidget(self.titleInput)

        self.contentInput = TextEdit(self)
        self.contentInput.setPlaceholderText("在此输入要投送的正文")
        QScroller.grabGesture(
            self.contentInput.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        self.vBoxLayout.addWidget(self.contentInput)
        self._inlineAIGlow = BusyGlowOverlay(self.contentInput)

        btnLayout = QHBoxLayout()
        self.templateBtn = PushButton(self)
        self.templateBtn.setIcon(FIF.DOCUMENT)
        self.templateBtn.setText("导入")
        self.templateBtn.clicked.connect(self._showTemplateMenu)

        self.aiBtn = PushButton(self)
        self.aiBtn.setIcon(QIcon(str(ASSET_DIR / "deepseek.png")))
        self.aiBtn.setText("AI 整理 Markdown")
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

        self._inlineAIFlushTimer = QTimer(self)
        self._inlineAIFlushTimer.setSingleShot(True)
        self._inlineAIFlushTimer.setInterval(50)
        self._inlineAIFlushTimer.timeout.connect(self._flushInlineAIChunks)
        self._updateMarkdownUi()

        self.broadcastWin = BroadcastWindow()
        self.broadcastWin.editClicked.connect(self._onReturnToEdit)
        self.broadcastWin.closeClicked.connect(self._onReturnToHome)
        self._activeBroadcast = None

    def _saveTitle(self):
        title = self.titleInput.text()
        if title != cfg.broadcastTitle.value:
            cfg.set(cfg.broadcastTitle, title)

    def _onMarkdownStateChanged(self, state):
        cfg.set(
            cfg.broadcastMarkdownEnabled,
            self.markdownCheckBox.isChecked(),
        )
        self._updateMarkdownUi()

    def _onOrganizeStateChanged(self, state):
        cfg.set(
            cfg.organizeMarkdownBeforeBroadcast,
            self.organizeCheckBox.isChecked(),
        )
        self._updateMarkdownUi()

    def _updateMarkdownUi(self):
        markdownEnabled = self.markdownCheckBox.isChecked()
        if markdownEnabled:
            self.contentInput.setPlaceholderText("支持Markdown语法（注意，在该模式下换行要换两次）")
        else:
            self.contentInput.setPlaceholderText("在此输入要投送的正文")
        self.organizeCheckBox.setVisible(markdownEnabled)
        self.aiBtn.setEnabled(markdownEnabled and self._inlineAIRequest is None)
        if self._inlineAIRequest is None:
            organize = markdownEnabled and self.organizeCheckBox.isChecked()
            self.broadcastBtn.setText("整理并投送" if organize else "投送")

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
        if not self._useLastBroadcast():
            return
        self._startBroadcast(
            self.titleInput.text(),
            self.contentInput.toPlainText(),
            self.markdownCheckBox.isChecked(),
        )

    def _setBroadcastInactive(self):
        broadcast = cfg.lastBroadcast.value
        if isinstance(broadcast, dict) and broadcast.get("active") is True:
            cfg.set(cfg.lastBroadcast, {**broadcast, "active": False})

    def _onBroadcast(self):
        self._saveTitle()
        if self._inlineAIRequest is not None:
            self._cancelInlineAIAndBroadcast()
            return

        if (
            self.markdownCheckBox.isChecked()
            and self.organizeCheckBox.isChecked()
            and self.contentInput.toPlainText().strip()
        ):
            self._startInlineAI()
            return

        self._startBroadcast(
            self.titleInput.text(),
            self.contentInput.toPlainText(),
            self.markdownCheckBox.isChecked(),
        )

    def _startBroadcast(self, title, content, isMarkdown):
        QApplication.instance().setQuitOnLastWindowClosed(False)
        self._activeBroadcast = {
            "title": title,
            "content": content,
            "isMarkdown": isMarkdown,
        }
        cfg.set(cfg.lastBroadcast, {**self._activeBroadcast, "active": True})
        self.broadcastWin.setContent(
            self._activeBroadcast["title"],
            self._activeBroadcast["content"],
            self._activeBroadcast["isMarkdown"],
        )
        self.broadcastWin.startBroadcast()
        self.window().hide()

    def _startInlineAI(self):
        snapshot = {
            "title": self.titleInput.text(),
            "content": self.contentInput.toPlainText(),
            "isMarkdown": True,
        }
        request = _AIMarkdownRequest(snapshot["content"], self)
        request.chunkReceived.connect(
            lambda chunk, current=request: self._appendInlineAIChunk(
                current, chunk
            )
        )
        request.conversionFinished.connect(
            lambda remaining, limit, cost, current=request: (
                self._onInlineAIFinished(current, remaining, limit, cost)
            )
        )
        request.conversionFailed.connect(
            lambda message, remaining, limit, cost, current=request: (
                self._onInlineAIFailed(
                    current, message, remaining, limit, cost
                )
            )
        )
        request.stopped.connect(request.deleteLater)

        self._inlineAIRequest = request
        self._inlineAISnapshot = snapshot
        self._inlineAIPendingChunks.clear()
        self.contentInput.clear()
        self.contentInput.setReadOnly(True)
        for widget in (
            self.backBtn,
            self.titleInput,
            self.templateBtn,
            self.aiBtn,
            self.organizeCheckBox,
            self.markdownCheckBox,
        ):
            widget.setEnabled(False)
        self.broadcastBtn.setText("取消")
        self._inlineAIGlow.start()
        request.start()

    def _appendInlineAIChunk(self, request, chunk):
        if request is not self._inlineAIRequest:
            return
        self._inlineAIPendingChunks.append(chunk)
        if not self._inlineAIFlushTimer.isActive():
            self._inlineAIFlushTimer.start()

    def _flushInlineAIChunks(self):
        if not self._inlineAIPendingChunks:
            return
        chunk = "".join(self._inlineAIPendingChunks)
        self._inlineAIPendingChunks.clear()
        self.contentInput.moveCursor(QTextCursor.MoveOperation.End)
        self.contentInput.insertPlainText(chunk)
        self.contentInput.ensureCursorVisible()

    def _onInlineAIFinished(self, request, remaining, limit, cost):
        if request is not self._inlineAIRequest:
            return
        result = request.resultText()
        if not result.strip():
            self._onInlineAIFailed(
                request,
                "AI 没有返回内容，请重试。",
                remaining,
                limit,
                cost,
            )
            return

        snapshot = self._inlineAISnapshot
        self._finishInlineAI()
        self.contentInput.setPlainText(result)
        self._startBroadcast(snapshot["title"], result, snapshot["isMarkdown"])

    def _onInlineAIFailed(self, request, message, remaining, limit, cost):
        if request is not self._inlineAIRequest:
            return
        snapshot = self._inlineAISnapshot
        self._finishInlineAI()
        self.contentInput.setPlainText(snapshot["content"])
        dialog = MessageBox("整理失败", message, self.window())
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _cancelInlineAIAndBroadcast(self):
        request = self._inlineAIRequest
        snapshot = self._inlineAISnapshot
        if request is None or snapshot is None:
            return
        self._finishInlineAI()
        request.cancel()
        self.contentInput.setPlainText(snapshot["content"])
        self._startBroadcast(
            snapshot["title"],
            snapshot["content"],
            snapshot["isMarkdown"],
        )

    def _finishInlineAI(self):
        self._inlineAIRequest = None
        self._inlineAISnapshot = None
        self._inlineAIFlushTimer.stop()
        self._inlineAIPendingChunks.clear()
        self._inlineAIGlow.stop()
        self.contentInput.setReadOnly(False)
        for widget in (
            self.backBtn,
            self.titleInput,
            self.templateBtn,
            self.organizeCheckBox,
            self.markdownCheckBox,
        ):
            widget.setEnabled(True)
        self._updateMarkdownUi()

    def shutdown(self):
        self._saveTitle()
        request = self._inlineAIRequest
        if request is None:
            return
        self._finishInlineAI()
        request.cancel()

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
        self.contentInput.clear()
        self._activeBroadcast = None
        if showMainWindow:
            self.window().show(); self.window().raise_(); self.window().activateWindow()
        self.backSignal.emit()

    def _onBack(self):
        if self.contentInput.toPlainText().strip():
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
        self._saveTitle()
        self.contentInput.clear()
        self.backSignal.emit()

    def hideEvent(self, event):
        self._saveTitle()
        super().hideEvent(event)
