from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QScroller,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBoxBase,
    PlainTextEdit,
    PushButton,
    SearchLineEdit,
    SimpleCardWidget,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.home_cards import (
    ACTION_TYPES,
    HomeCardError,
    extractIconImages,
    iconForData,
    newId,
    normalizeAction,
    saveIconImage,
    validateAction,
)
from app.view.components.icon_grid import IconGrid, IconGridItem
from app.view.components.scroll_area import ScrollArea
from app.view.components.tool_tip import setFluentToolTip

ACTION_LABELS = {
    "program": "直接启动程序",
    "shell": "执行 Shell 命令",
    "url": "打开网页",
    "path": "打开文件或文件夹",
    "delay": "等待",
}


def _dialogHost(widget):
    window = widget.window()
    return window.parentWidget() or window


def _disposeDialog(dialog):
    # Nested editors can be reopened before the next event-loop turn.
    dialog.deleteLater()
    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)


class _ResponsiveMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        self._preferredWidth = 0
        self._preferredHeight = 0
        self._closing = False
        super().__init__(parent)
        self.buttonLayout.setContentsMargins(24, 16, 24, 16)

    def setPreferredSize(self, width, height):
        self._preferredWidth = width
        self._preferredHeight = height
        self._updatePanelSize(self.size())

    def _updatePanelSize(self, size):
        if not self._preferredWidth or size.width() <= 0:
            return
        self.widget.setFixedSize(
            min(self._preferredWidth, max(0, size.width() - 32)),
            min(self._preferredHeight, max(0, size.height() - 16)),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updatePanelSize(event.size())

    def done(self, code):
        if self._closing:
            return
        self._closing = True
        self.buttonGroup.setEnabled(False)
        for scrollArea in self.findChildren(ScrollArea):
            viewport = scrollArea.viewport()
            QScroller.scroller(viewport).stop()
            QScroller.ungrabGesture(viewport)
        super().done(code)


class DragHandleButton(ToolButton):
    dragStarted = Signal(QPoint)
    dragMoved = Signal(QPoint)
    dragFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(FIF.MOVE)
        self.setFixedSize(44, 44)
        setFluentToolTip(self, "拖动调整动作顺序")
        self.setAccessibleName("拖动调整动作顺序")
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._pressPosition = None
        self._dragging = False

    def _begin(self, position: QPoint):
        self._pressPosition = position
        self._dragging = False

    def _move(self, position: QPoint):
        if self._pressPosition is None:
            return
        if not self._dragging:
            if (position - self._pressPosition).manhattanLength() < QApplication.startDragDistance():
                return
            self._dragging = True
            self.dragStarted.emit(self._pressPosition)
        self.dragMoved.emit(position)

    def _finish(self):
        if self._dragging:
            self.dragFinished.emit()
        self._pressPosition = None
        self._dragging = False

    def event(self, event):
        if event.type() == QEvent.Type.FocusOut:
            self._finish()
            return super().event(event)
        if event.type() == QEvent.Type.TouchBegin and event.points():
            self._begin(event.points()[0].globalPosition().toPoint())
            event.accept()
            return True
        if event.type() == QEvent.Type.TouchUpdate and event.points():
            self._move(event.points()[0].globalPosition().toPoint())
            event.accept()
            return True
        if event.type() in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            self._finish()
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._move(event.globalPosition().toPoint())
        if self._pressPosition is not None:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pressPosition is not None:
            self._finish()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ActionRow(CardWidget):
    editRequested = Signal()
    deleteRequested = Signal()
    bodyTouchStarted = Signal(QPoint)
    bodyTouchMoved = Signal(QPoint)
    bodyTouchFinished = Signal()

    def __init__(self, action: dict, parent=None):
        super().__init__(parent)
        self.action = normalizeAction(action) or {"id": newId(), "type": "delay", "seconds": 1}
        self.dragHandle = DragHandleButton(self)
        self.summary = StrongBodyLabel(self)
        self.detail = CaptionLabel(self)
        self.summary.setWordWrap(False)
        self.detail.setWordWrap(False)
        self.summary.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.detail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.detail.setStyleSheet("color: gray;")
        self.editButton = ToolButton(FIF.EDIT, self)
        self.deleteButton = ToolButton(FIF.DELETE, self)
        for button, name in (
            (self.editButton, "编辑动作"),
            (self.deleteButton, "删除动作"),
        ):
            button.setFixedSize(44, 44)
            setFluentToolTip(button, name)
            button.setAccessibleName(name)
        self.editButton.clicked.connect(self.editRequested)
        self.deleteButton.clicked.connect(self.deleteRequested)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(12)
        self._layout.addWidget(self.dragHandle)
        textLayout = QVBoxLayout()
        textLayout.setContentsMargins(0, 0, 0, 0)
        textLayout.addWidget(self.summary)
        textLayout.addWidget(self.detail)
        self._layout.addLayout(textLayout, 1)
        self._layout.addWidget(self.editButton)
        self._layout.addWidget(self.deleteButton)
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._bodyTouching = False
        self.setData(self.action)

    def setData(self, action: dict):
        self.action = normalizeAction(action) or self.action
        actionType = self.action["type"]
        self.summary.setText(ACTION_LABELS[actionType])
        if actionType == "program":
            detail = self.action["target"] or "未设置程序"
        elif actionType == "shell":
            detail = self.action["command"] or "未设置命令"
        elif actionType in {"url", "path"}:
            detail = self.action["target"] or "未设置目标"
        else:
            detail = f"{self.action['seconds']} 秒"
        self.detail.setText(detail)
        setFluentToolTip(self.detail, detail)

    def mousePressEvent(self, event):
        event.ignore()

    def event(self, event):
        if event.type() == QEvent.Type.TouchBegin and event.points():
            self._bodyTouching = True
            self.bodyTouchStarted.emit(event.points()[0].globalPosition().toPoint())
            event.accept()
            return True
        if event.type() == QEvent.Type.TouchUpdate and event.points() and self._bodyTouching:
            self.bodyTouchMoved.emit(event.points()[0].globalPosition().toPoint())
            event.accept()
            return True
        if event.type() in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            if self._bodyTouching:
                self.bodyTouchFinished.emit()
            self._bodyTouching = False
            event.accept()
            return True
        return super().event(event)

    def mouseMoveEvent(self, event):
        event.ignore()

    def mouseReleaseEvent(self, event):
        event.ignore()


class ActionListWidget(QWidget):
    orderChanged = Signal()

    def __init__(self, actions=None, parent=None):
        super().__init__(parent)
        self.rows = []
        self._dragRow = None
        self._dragChanged = False
        self._scrollArea = None
        self._indicator = QFrame(self)
        self._indicator.setFixedHeight(3)
        self._indicator.setStyleSheet("background: #4cc2ff; border-radius: 1px;")
        self._indicator.hide()
        self._autoScrollTimer = QTimer(self)
        self._autoScrollTimer.setInterval(50)
        self._autoScrollTimer.timeout.connect(self._autoScroll)
        self._dragPosition = QPoint()
        self._bodyTouchPosition = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        for action in actions or []:
            self.addAction(action)

    def setScrollArea(self, scrollArea):
        self._scrollArea = scrollArea

    def addAction(self, action):
        row = ActionRow(action, self)
        row.editRequested.connect(lambda row=row: self._editRow(row))
        row.deleteRequested.connect(lambda row=row: self._deleteRow(row))
        row.bodyTouchStarted.connect(self._startBodyScroll)
        row.bodyTouchMoved.connect(self._moveBodyScroll)
        row.bodyTouchFinished.connect(self._finishBodyScroll)
        row.dragHandle.dragStarted.connect(lambda position, row=row: self._startDrag(row, position))
        row.dragHandle.dragMoved.connect(self._moveDrag)
        row.dragHandle.dragFinished.connect(self._finishDrag)
        self.rows.append(row)
        self._layout.addWidget(row)
        row.show()

    def actions(self) -> list[dict]:
        return [deepcopy(row.action) for row in self.rows]

    def _editRow(self, row):
        dialog = ActionEditorDialog(row.action, _dialogHost(self))
        try:
            if not dialog.exec():
                return
            action = dialog.getData()
        finally:
            _disposeDialog(dialog)
        row.setData(action)
        self.orderChanged.emit()

    def _deleteRow(self, row):
        self.rows.remove(row)
        self._layout.removeWidget(row)
        row.deleteLater()
        self.orderChanged.emit()

    def _startBodyScroll(self, position):
        if self._dragRow is None:
            self._bodyTouchPosition = position

    def _moveBodyScroll(self, position):
        if self._bodyTouchPosition is None or self._scrollArea is None:
            return
        delta = position.y() - self._bodyTouchPosition.y()
        if delta:
            bar = self._scrollArea.verticalScrollBar()
            bar.setValue(bar.value() - delta)
            self._bodyTouchPosition = position

    def _finishBodyScroll(self):
        self._bodyTouchPosition = None

    def _startDrag(self, row, position):
        self._dragRow = row
        self._dragChanged = False
        self._dragPosition = position
        effect = row.graphicsEffect()
        if effect is None:
            from PySide6.QtWidgets import QGraphicsOpacityEffect

            effect = QGraphicsOpacityEffect(row)
            row.setGraphicsEffect(effect)
        effect.setOpacity(0.35)
        self._indicator.show()
        self._autoScrollTimer.start()
        self._moveDrag(position)

    def _moveDrag(self, position):
        if self._dragRow is None:
            return
        self._dragPosition = position
        localY = self.mapFromGlobal(position).y()
        remaining = [row for row in self.rows if row is not self._dragRow]
        targetIndex = sum(localY > row.geometry().center().y() for row in remaining)
        currentIndex = self.rows.index(self._dragRow)
        if targetIndex != currentIndex:
            self.rows.remove(self._dragRow)
            self.rows.insert(targetIndex, self._dragRow)
            self._layout.removeWidget(self._dragRow)
            self._layout.insertWidget(targetIndex, self._dragRow)
            self._dragChanged = True
        if targetIndex < len(remaining):
            y = remaining[targetIndex].geometry().top() - 2
        elif remaining:
            y = remaining[-1].geometry().bottom() + 2
        else:
            y = 0
        self._indicator.setGeometry(4, max(0, y), max(1, self.width() - 8), 3)
        self._indicator.raise_()

    def _autoScroll(self):
        if self._dragRow is None or self._scrollArea is None:
            return
        viewport = self._scrollArea.viewport()
        position = viewport.mapFromGlobal(self._dragPosition)
        margin = 60
        step = 14
        if position.y() < margin:
            bar = self._scrollArea.verticalScrollBar()
            bar.setValue(max(bar.minimum(), bar.value() - step))
        elif position.y() > viewport.height() - margin:
            bar = self._scrollArea.verticalScrollBar()
            bar.setValue(min(bar.maximum(), bar.value() + step))

    def _finishDrag(self):
        if self._dragRow is None:
            return
        effect = self._dragRow.graphicsEffect()
        if effect:
            effect.setOpacity(1.0)
            self._dragRow.setGraphicsEffect(None)
        self._indicator.hide()
        self._autoScrollTimer.stop()
        changed = self._dragChanged
        self._dragRow = None
        self._dragChanged = False
        if changed:
            self.orderChanged.emit()

    def hideEvent(self, event):
        self._finishDrag()
        self._finishBodyScroll()
        super().hideEvent(event)


def _showError(parent, title, message):
    InfoBar.error(
        title,
        message,
        duration=3000,
        position=InfoBarPosition.TOP,
        parent=parent,
    )


class ActionSequenceEditor(QWidget):
    changed = Signal()

    def __init__(self, actions=None, parent=None):
        super().__init__(parent)
        self.actionList = ActionListWidget(actions, self)
        self.addActionButton = PushButton(FIF.ADD, "添加动作", self)
        self.addActionButton.clicked.connect(self.addAction)
        self.actionList.orderChanged.connect(self.changed.emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.actionList)
        layout.addWidget(self.addActionButton)

    def setScrollArea(self, scrollArea):
        self.actionList.setScrollArea(scrollArea)

    def actions(self) -> list[dict]:
        return self.actionList.actions()

    def validate(self, noticeParent) -> bool:
        actions = self.actions()
        if not actions:
            _showError(noticeParent, "无法保存", "至少添加一个动作")
            return False
        for action in actions:
            error = validateAction(action)
            if error:
                _showError(noticeParent, "动作无效", error)
                return False
        return True

    def addAction(self):
        dialog = ActionEditorDialog(parent=_dialogHost(self))
        try:
            if not dialog.exec():
                return
            action = dialog.getData()
        finally:
            _disposeDialog(dialog)
        self.actionList.addAction(action)
        self.changed.emit()


class ActionEditorDialog(_ResponsiveMessageBox):
    def __init__(self, action=None, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("配置动作", self)
        self.descriptionLabel = CaptionLabel("选择动作类型，并填写执行所需的信息。", self)
        self.typeCombo = ComboBox(self)
        for actionType in ACTION_TYPES:
            self.typeCombo.addItem(ACTION_LABELS[actionType])
        self.stack = QStackedWidget(self)
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.scrollArea.setMinimumHeight(100)
        self.scrollArea.setMaximumHeight(360)
        self.scrollArea.setWidget(self.stack)
        self._pages = {}
        self._widgets = {}
        self._buildPages()
        self.typeCombo.currentIndexChanged.connect(self._onTypeChanged)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descriptionLabel)
        self.viewLayout.addWidget(self.typeCombo)
        self.viewLayout.addWidget(self.scrollArea)
        self.setPreferredSize(620, 560)
        self._action = normalizeAction(action) if action else None
        self._load(self._action)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def _formPage(self):
        page = QWidget(self.stack)
        page.setStyleSheet("background: transparent;")
        layout = QFormLayout(page)
        layout.setContentsMargins(0, 12, 0, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(14)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        return page, layout

    def _lineWithBrowse(self, title, filterText):
        line = LineEdit(self)
        button = PushButton(FIF.FOLDER, "选择", self)
        button.clicked.connect(
            lambda: self._chooseFile(line, title, filterText)
        )
        wrapper = QWidget(self)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line, 1)
        row.addWidget(button)
        return wrapper, line

    def _buildPages(self):
        page, form = self._formPage()
        targetWrapper, target = self._lineWithBrowse("选择程序", "Programs (*.exe *.com *.bat *.cmd);;All files (*.*)")
        arguments = LineEdit(self)
        arguments.setPlaceholderText("可选，例如 --profile default")
        workingWrapper, workingDir = self._lineWithBrowse("选择工作目录", "All files (*.*)")
        wait = CheckBox("等待程序结束后继续", self)
        form.addRow("程序或命令", targetWrapper)
        form.addRow("参数", arguments)
        form.addRow("工作目录", workingWrapper)
        form.addRow("执行方式", wait)
        self._pages["program"] = page
        self._widgets["program"] = (target, arguments, workingDir, wait)
        self.stack.addWidget(page)

        page, form = self._formPage()
        command = PlainTextEdit(self)
        command.setPlaceholderText("输入 Windows Shell 命令")
        command.setFixedHeight(110)
        shellWrapper, shellWorkingDir = self._lineWithBrowse("选择工作目录", "All files (*.*)")
        shellWait = CheckBox("等待命令结束后继续", self)
        showConsole = CheckBox("显示控制台窗口", self)
        warning = BodyLabel("Shell 命令会直接在本机执行，请确认内容可信。", self)
        warning.setStyleSheet("color: #d13438;")
        form.addRow("命令", command)
        form.addRow("工作目录", shellWrapper)
        form.addRow("执行方式", shellWait)
        form.addRow("窗口", showConsole)
        form.addRow("提示", warning)
        self._pages["shell"] = page
        self._widgets["shell"] = (command, shellWorkingDir, shellWait, showConsole)
        self.stack.addWidget(page)

        page, form = self._formPage()
        url = LineEdit(self)
        url.setPlaceholderText("例如 https://example.com")
        form.addRow("网页地址", url)
        self._pages["url"] = page
        self._widgets["url"] = (url,)
        self.stack.addWidget(page)

        page, form = self._formPage()
        path = LineEdit(self)
        fileButton = PushButton(FIF.FOLDER, "文件", self)
        folderButton = PushButton(FIF.FOLDER, "文件夹", self)
        fileButton.clicked.connect(lambda: self._chooseFile(path, "选择文件", "All files (*.*)"))
        folderButton.clicked.connect(lambda: self._chooseFolder(path))
        buttons = QWidget(self)
        buttonsLayout = QHBoxLayout(buttons)
        buttonsLayout.setContentsMargins(0, 0, 0, 0)
        buttonsLayout.addWidget(path, 1)
        buttonsLayout.addWidget(fileButton)
        buttonsLayout.addWidget(folderButton)
        form.addRow("目标", buttons)
        self._pages["path"] = page
        self._widgets["path"] = (path,)
        self.stack.addWidget(page)

        page, form = self._formPage()
        seconds = SpinBox(self)
        seconds.setRange(1, 86400)
        seconds.setSuffix(" 秒")
        form.addRow("等待时间", seconds)
        self._pages["delay"] = page
        self._widgets["delay"] = (seconds,)
        self.stack.addWidget(page)

    def _chooseFile(self, line, title, filterText):
        path, _ = QFileDialog.getOpenFileName(self, title, "", filterText)
        if path:
            line.setText(path)

    def _chooseFolder(self, line):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            line.setText(path)

    def _onTypeChanged(self, index):
        actionType = ACTION_TYPES[index]
        self.stack.setCurrentWidget(self._pages[actionType])

    def _load(self, action):
        actionType = action["type"] if action else "program"
        self.typeCombo.setCurrentIndex(max(0, ACTION_TYPES.index(actionType)))
        if not action:
            return
        widgets = self._widgets[actionType]
        if actionType == "program":
            widgets[0].setText(action["target"])
            widgets[1].setText(action["arguments"])
            widgets[2].setText(action["working_dir"])
            widgets[3].setChecked(action["wait"])
        elif actionType == "shell":
            widgets[0].setPlainText(action["command"])
            widgets[1].setText(action["working_dir"])
            widgets[2].setChecked(action["wait"])
            widgets[3].setChecked(action["show_console"])
        elif actionType in {"url", "path"}:
            widgets[0].setText(action["target"])
        else:
            widgets[0].setValue(action["seconds"])

    def getData(self) -> dict:
        actionType = ACTION_TYPES[self.typeCombo.currentIndex()]
        oldId = self._action.get("id") if self._action else newId()
        widgets = self._widgets[actionType]
        if actionType == "program":
            return {"id": oldId, "type": actionType, "target": widgets[0].text().strip(), "arguments": widgets[1].text(), "working_dir": widgets[2].text().strip(), "wait": widgets[3].isChecked()}
        if actionType == "shell":
            return {"id": oldId, "type": actionType, "command": widgets[0].toPlainText().strip(), "working_dir": widgets[1].text().strip(), "wait": widgets[2].isChecked(), "show_console": widgets[3].isChecked()}
        if actionType in {"url", "path"}:
            return {"id": oldId, "type": actionType, "target": widgets[0].text().strip()}
        return {"id": oldId, "type": actionType, "seconds": widgets[0].value()}

    def validate(self) -> bool:
        error = validateAction(self.getData())
        if error:
            _showError(self, "动作无效", error)
            return False
        return True


class IconPickerDialog(_ResponsiveMessageBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("选择图标", self)
        self.descriptionLabel = CaptionLabel(
            "从图标库、图片文件或 Windows 图标资源中选择。", self
        )
        self.sourceCombo = ComboBox(self)
        self.sourceCombo.addItem("QWF 图标库")
        self.sourceCombo.addItem("图片文件")
        self.sourceCombo.addItem("ICO / EXE / DLL")
        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("搜索图标名称")
        self.browseButton = PushButton(FIF.FOLDER, "选择文件", self)
        self.browseButton.setMinimumWidth(180)
        self.previewIcon = IconWidget(FIF.APPLICATION, self)
        self.previewIcon.setFixedSize(40, 40)
        self.previewLabel = CaptionLabel("APPLICATION", self)
        self.previewCard = SimpleCardWidget(self)
        self.previewCard.setFixedHeight(72)
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.scrollArea.setMinimumHeight(100)
        self.scrollArea.setMaximumHeight(620)
        self.contentWidget = QWidget(self.scrollArea)
        self.contentWidget.setStyleSheet("background: transparent;")
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setContentsMargins(4, 4, 4, 4)
        self.contentLayout.setSpacing(12)
        self.gridWidget = IconGrid(self.contentWidget)
        self.scrollArea.setWidget(self.contentWidget)
        self._selected = {"type": "fluent", "name": "APPLICATION"}
        self._externalImage = None
        self._externalImages = []
        self.sourceCombo.currentIndexChanged.connect(self._sourceChanged)
        self.gridWidget.iconClicked.connect(self._onIconClicked)
        self.searchEdit.textChanged.connect(self._filterIcons)
        self.browseButton.clicked.connect(self._browse)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.searchEdit, 1)
        toolbar.addWidget(self.browseButton)
        previewLayout = QHBoxLayout(self.previewCard)
        previewLayout.setContentsMargins(16, 12, 16, 12)
        previewLayout.setSpacing(12)
        previewLayout.addWidget(self.previewIcon)
        previewLayout.addWidget(self.previewLabel)
        previewLayout.addStretch(1)
        self.contentLayout.addWidget(self.titleLabel)
        self.contentLayout.addWidget(self.descriptionLabel)
        self.contentLayout.addWidget(self.sourceCombo)
        self.contentLayout.addLayout(toolbar)
        self.contentLayout.addWidget(self.previewCard)
        self.contentLayout.addWidget(self.gridWidget)
        self.viewLayout.addWidget(self.scrollArea)
        self.setPreferredSize(720, 700)
        self.yesButton.setText("选择")
        self.cancelButton.setText("取消")
        self._sourceChanged()

    def _renderFluentIcons(self):
        self._externalImages = []
        self.gridWidget.setItems(
            [
                IconGridItem(name, icon, name)
                for name, icon in FIF.__members__.items()
            ]
        )
        self.gridWidget.setFilterText(self.searchEdit.text())
        self._refreshGridLayout()
        name = self._selected.get("name", "APPLICATION")
        self._selectFluent(name if name in FIF.__members__ else "APPLICATION")

    def _clearGrid(self):
        self._externalImages = []
        self.gridWidget.setItems([])

    def _refreshGridLayout(self):
        width = max(1, self.scrollArea.viewport().width() - 8)
        self.gridWidget.setFixedHeight(self.gridWidget.heightForWidth(width))
        self.contentWidget.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "gridWidget"):
            self.widget.layout().activate()
            self._refreshGridLayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._refreshGridLayout()

    def _sourceChanged(self):
        index = self.sourceCombo.currentIndex()
        fluent = index == 0
        self.searchEdit.setVisible(fluent)
        self.browseButton.setVisible(not fluent)
        if fluent:
            self._renderFluentIcons()
        else:
            self._clearGrid()
            self.browseButton.setText(
                "选择图片" if index == 1 else "选择 ICO / EXE / DLL"
            )
            self._refreshGridLayout()

    def _filterIcons(self, text):
        self.gridWidget.setFilterText(text)
        self._refreshGridLayout()

    def _onIconClicked(self, index):
        if self._externalImages:
            self._selectImage(self._externalImages[index], index)
        else:
            self._selectFluent(self.gridWidget.items()[index].key)

    def _selectFluent(self, name):
        self._selected = {"type": "fluent", "name": name}
        self._externalImage = None
        self.previewIcon.setIcon(getattr(FIF, name, FIF.APPLICATION))
        self.previewLabel.setText(name)
        self.gridWidget.setCheckedIndex(self.gridWidget.indexOfKey(name))

    def _browse(self):
        imageSource = self.sourceCombo.currentIndex() == 1
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片" if imageSource else "选择图标资源",
            "",
            (
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
                if imageSource
                else "图标资源 (*.ico *.exe *.dll)"
            ),
        )
        if not path:
            return
        try:
            images = extractIconImages(path)
        except HomeCardError as error:
            _showError(self, "图标读取失败", str(error))
            return
        self.gridWidget.setItems(
            [
                IconGridItem(str(index), QIcon(QPixmap.fromImage(image)), f"图标 {index + 1}")
                for index, image in enumerate(images)
            ]
        )
        self._externalImages = list(images)
        self._refreshGridLayout()
        self._selectImage(images[0], 0)

    def _selectImage(self, image, index=None):
        self._externalImage = image.copy()
        self._selected = {"type": "image"}
        self.previewIcon.setIcon(QIcon(QPixmap.fromImage(image)))
        self.previewLabel.setText(
            self.gridWidget.items()[index].toolTip if index is not None else "自定义图标"
        )
        self.gridWidget.setCheckedIndex(index)

    def selected(self):
        return deepcopy(self._selected), self._externalImage.copy() if self._externalImage else None


class CustomCardDialog(_ResponsiveMessageBox):
    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        data = deepcopy(data) if isinstance(data, dict) else {}
        self.cardId = data.get("id") or newId()
        self._icon = deepcopy(data.get("icon") or {"type": "fluent", "name": "APPLICATION"})
        self._stagedImage = None
        self.titleLabel = SubtitleLabel("编辑主页卡片" if data else "新建主页卡片", self)
        self.descriptionLabel = CaptionLabel(
            "设置卡片的显示信息，以及点击后依次执行的动作。", self
        )
        self.titleEdit = LineEdit(self)
        self.titleEdit.setMaxLength(40)
        self.titleEdit.setPlaceholderText("例如：打开课程表")
        self.descriptionEdit = LineEdit(self)
        self.descriptionEdit.setMaxLength(120)
        self.descriptionEdit.setPlaceholderText("简短说明卡片用途")
        self.iconPreview = IconWidget(iconForData(self._icon), self)
        self.iconPreview.setFixedSize(40, 40)
        setFluentToolTip(self.iconPreview, "当前图标")
        self.iconCard = SimpleCardWidget(self)
        self.iconCard.setMinimumHeight(76)
        iconTitle = StrongBodyLabel("卡片图标", self.iconCard)
        iconDescription = CaptionLabel("选择一个容易识别的图标", self.iconCard)
        self.iconSelectButton = PushButton(FIF.PALETTE, "选择图标", self)
        self.iconSelectButton.clicked.connect(self._chooseIcon)
        iconCardLayout = QHBoxLayout(self.iconCard)
        iconCardLayout.setContentsMargins(16, 12, 16, 12)
        iconCardLayout.setSpacing(12)
        iconTextLayout = QVBoxLayout()
        iconTextLayout.setContentsMargins(0, 0, 0, 0)
        iconTextLayout.setSpacing(2)
        iconTextLayout.addWidget(iconTitle)
        iconTextLayout.addWidget(iconDescription)
        iconCardLayout.addWidget(self.iconPreview)
        iconCardLayout.addLayout(iconTextLayout, 1)
        iconCardLayout.addWidget(self.iconSelectButton)
        initialActions = data.get("actions") if data else None
        if not initialActions:
            initialActions = [{"id": newId(), "type": "program", "target": "", "arguments": "", "working_dir": "", "wait": False}]
        self.actionEditor = ActionSequenceEditor(initialActions, self)
        self.actionList = self.actionEditor.actionList
        self.addActionButton = self.actionEditor.addActionButton
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.scrollArea.setMinimumHeight(100)
        self.scrollArea.setMaximumHeight(560)
        self.form = QWidget(self.scrollArea)
        self.form.setStyleSheet("background: transparent;")
        formLayout = QVBoxLayout(self.form)
        formLayout.setContentsMargins(6, 6, 6, 6)
        formLayout.setSpacing(10)
        formLayout.addWidget(StrongBodyLabel("标题", self.form))
        formLayout.addWidget(self.titleEdit)
        formLayout.addWidget(StrongBodyLabel("简介", self.form))
        formLayout.addWidget(self.descriptionEdit)
        formLayout.addSpacing(4)
        formLayout.addWidget(self.iconCard)
        formLayout.addSpacing(10)
        formLayout.addWidget(StrongBodyLabel("动作列表", self.form))
        formLayout.addWidget(
            CaptionLabel(
                "触摸正文可滚动；从每行动作左侧的手柄拖动排序。",
                self.form,
            )
        )
        formLayout.addWidget(self.actionEditor)
        self.scrollArea.setWidget(self.form)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descriptionLabel)
        self.viewLayout.addWidget(self.scrollArea)
        self.setPreferredSize(720, 700)
        self.titleEdit.setText(str(data.get("title", "")))
        self.descriptionEdit.setText(str(data.get("description", "")))
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.actionEditor.setScrollArea(self.scrollArea)

    def _chooseIcon(self):
        dialog = IconPickerDialog(_dialogHost(self))
        try:
            if not dialog.exec():
                return
            selected, image = dialog.selected()
        finally:
            _disposeDialog(dialog)
        if selected["type"] == "fluent":
            self._icon = selected
            self._stagedImage = None
            self.iconPreview.setIcon(iconForData(self._icon))
        else:
            self._stagedImage = image
            self._icon = {"type": "image"}
            self.iconPreview.setIcon(QIcon(QPixmap.fromImage(image)))

    def _addAction(self):
        self.actionEditor.addAction()

    def validate(self) -> bool:
        title = self.titleEdit.text().strip()
        if not title:
            _showError(self, "无法保存", "请输入卡片标题")
            return False
        if not self.actionEditor.validate(self):
            return False
        if self._stagedImage is not None:
            try:
                self._icon = {"type": "file", "file": saveIconImage(self._stagedImage)}
                self._stagedImage = None
            except HomeCardError as error:
                _showError(self, "无法保存图标", str(error))
                return False
        return True

    def getData(self) -> dict:
        return {
            "id": self.cardId,
            "title": self.titleEdit.text().strip(),
            "description": self.descriptionEdit.text().strip(),
            "icon": deepcopy(self._icon),
            "actions": self.actionList.actions(),
        }


__all__ = ["ActionSequenceEditor", "CustomCardDialog"]
