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
    FlowLayout,
    IconWidget,
    LineEdit,
    MessageBoxBase,
    PlainTextEdit,
    PushButton,
    SearchLineEdit,
    SimpleCardWidget,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    ToggleToolButton,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.home_cards import (
    ACTION_TYPES,
    HomeCardError,
    extract_icon_images,
    icon_for_data,
    new_id,
    normalize_action,
    save_icon_image,
    validate_action,
)
from app.view.components.scroll_area import ScrollArea
from app.view.components.tool_tip import setFluentToolTip

ACTION_LABELS = {
    "program": "直接启动程序",
    "shell": "执行 Shell 命令",
    "url": "打开网页",
    "path": "打开文件或文件夹",
    "delay": "等待",
}


def _dialog_host(widget):
    window = widget.window()
    return window.parentWidget() or window


class _ResponsiveMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        self._preferred_width = 0
        self._preferred_height = 0
        self._closing = False
        super().__init__(parent)
        self.buttonGroup.setFixedHeight(76)
        self.buttonLayout.setContentsMargins(24, 16, 24, 16)
        self.yesButton.setFixedHeight(44)
        self.cancelButton.setFixedHeight(44)

    def setPreferredSize(self, width, height):
        self._preferred_width = width
        self._preferred_height = height
        self._updatePanelSize(self.size())

    def _updatePanelSize(self, size):
        if not self._preferred_width or size.width() <= 0:
            return
        self.widget.setFixedSize(
            min(self._preferred_width, max(0, size.width() - 32)),
            min(self._preferred_height, max(0, size.height() - 16)),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._updatePanelSize(event.size())

    def done(self, code):
        if self._closing:
            return
        self._closing = True
        self.buttonGroup.setEnabled(False)
        for scroll_area in self.findChildren(ScrollArea):
            viewport = scroll_area.viewport()
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
        self._press_position = None
        self._dragging = False

    def _begin(self, position: QPoint):
        self._press_position = position
        self._dragging = False

    def _move(self, position: QPoint):
        if self._press_position is None:
            return
        if not self._dragging:
            if (position - self._press_position).manhattanLength() < QApplication.startDragDistance():
                return
            self._dragging = True
            self.dragStarted.emit(self._press_position)
        self.dragMoved.emit(position)

    def _finish(self):
        if self._dragging:
            self.dragFinished.emit()
        self._press_position = None
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
        if self._press_position is not None:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._press_position is not None:
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
        self.action = normalize_action(action) or {"id": new_id(), "type": "delay", "seconds": 1}
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
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.summary)
        text_layout.addWidget(self.detail)
        self._layout.addLayout(text_layout, 1)
        self._layout.addWidget(self.editButton)
        self._layout.addWidget(self.deleteButton)
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._body_touching = False
        self.setData(self.action)

    def setData(self, action: dict):
        self.action = normalize_action(action) or self.action
        action_type = self.action["type"]
        self.summary.setText(ACTION_LABELS[action_type])
        if action_type == "program":
            detail = self.action["target"] or "未设置程序"
        elif action_type == "shell":
            detail = self.action["command"] or "未设置命令"
        elif action_type in {"url", "path"}:
            detail = self.action["target"] or "未设置目标"
        else:
            detail = f"{self.action['seconds']} 秒"
        self.detail.setText(detail)
        setFluentToolTip(self.detail, detail)

    def mousePressEvent(self, event):
        event.ignore()

    def event(self, event):
        if event.type() == QEvent.Type.TouchBegin and event.points():
            self._body_touching = True
            self.bodyTouchStarted.emit(event.points()[0].globalPosition().toPoint())
            event.accept()
            return True
        if event.type() == QEvent.Type.TouchUpdate and event.points() and self._body_touching:
            self.bodyTouchMoved.emit(event.points()[0].globalPosition().toPoint())
            event.accept()
            return True
        if event.type() in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            if self._body_touching:
                self.bodyTouchFinished.emit()
            self._body_touching = False
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
        self._drag_row = None
        self._drag_changed = False
        self._scroll_area = None
        self._indicator = QFrame(self)
        self._indicator.setFixedHeight(3)
        self._indicator.setStyleSheet("background: #4cc2ff; border-radius: 1px;")
        self._indicator.hide()
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(50)
        self._auto_scroll_timer.timeout.connect(self._autoScroll)
        self._drag_position = QPoint()
        self._body_touch_position = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        for action in actions or []:
            self.addAction(action)

    def setScrollArea(self, scroll_area):
        self._scroll_area = scroll_area

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
        dialog = ActionEditorDialog(row.action, _dialog_host(self))
        try:
            if not dialog.exec():
                return
            action = dialog.getData()
        finally:
            dialog.deleteLater()
        row.setData(action)
        self.orderChanged.emit()

    def _deleteRow(self, row):
        self.rows.remove(row)
        self._layout.removeWidget(row)
        row.deleteLater()
        self.orderChanged.emit()

    def _startBodyScroll(self, position):
        if self._drag_row is None:
            self._body_touch_position = position

    def _moveBodyScroll(self, position):
        if self._body_touch_position is None or self._scroll_area is None:
            return
        delta = position.y() - self._body_touch_position.y()
        if delta:
            bar = self._scroll_area.verticalScrollBar()
            bar.setValue(bar.value() - delta)
            self._body_touch_position = position

    def _finishBodyScroll(self):
        self._body_touch_position = None

    def _startDrag(self, row, position):
        self._drag_row = row
        self._drag_changed = False
        self._drag_position = position
        effect = row.graphicsEffect()
        if effect is None:
            from PySide6.QtWidgets import QGraphicsOpacityEffect

            effect = QGraphicsOpacityEffect(row)
            row.setGraphicsEffect(effect)
        effect.setOpacity(0.35)
        self._indicator.show()
        self._auto_scroll_timer.start()
        self._moveDrag(position)

    def _moveDrag(self, position):
        if self._drag_row is None:
            return
        self._drag_position = position
        local_y = self.mapFromGlobal(position).y()
        remaining = [row for row in self.rows if row is not self._drag_row]
        target_index = sum(local_y > row.geometry().center().y() for row in remaining)
        current_index = self.rows.index(self._drag_row)
        if target_index != current_index:
            self.rows.remove(self._drag_row)
            self.rows.insert(target_index, self._drag_row)
            self._layout.removeWidget(self._drag_row)
            self._layout.insertWidget(target_index, self._drag_row)
            self._drag_changed = True
        if target_index < len(remaining):
            y = remaining[target_index].geometry().top() - 2
        elif remaining:
            y = remaining[-1].geometry().bottom() + 2
        else:
            y = 0
        self._indicator.setGeometry(4, max(0, y), max(1, self.width() - 8), 3)
        self._indicator.raise_()

    def _autoScroll(self):
        if self._drag_row is None or self._scroll_area is None:
            return
        viewport = self._scroll_area.viewport()
        position = viewport.mapFromGlobal(self._drag_position)
        margin = 60
        step = 14
        if position.y() < margin:
            bar = self._scroll_area.verticalScrollBar()
            bar.setValue(max(bar.minimum(), bar.value() - step))
        elif position.y() > viewport.height() - margin:
            bar = self._scroll_area.verticalScrollBar()
            bar.setValue(min(bar.maximum(), bar.value() + step))

    def _finishDrag(self):
        if self._drag_row is None:
            return
        effect = self._drag_row.graphicsEffect()
        if effect:
            effect.setOpacity(1.0)
            self._drag_row.setGraphicsEffect(None)
        self._indicator.hide()
        self._auto_scroll_timer.stop()
        changed = self._drag_changed
        self._drag_row = None
        self._drag_changed = False
        if changed:
            self.orderChanged.emit()

    def hideEvent(self, event):
        self._finishDrag()
        self._finishBodyScroll()
        super().hideEvent(event)


class ActionEditorDialog(_ResponsiveMessageBox):
    def __init__(self, action=None, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("配置动作", self)
        self.descriptionLabel = CaptionLabel("选择动作类型，并填写执行所需的信息。", self)
        self.typeCombo = ComboBox(self)
        self.typeCombo.setFixedHeight(44)
        for action_type in ACTION_TYPES:
            self.typeCombo.addItem(ACTION_LABELS[action_type])
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
        self._action = normalize_action(action) if action else None
        self._load(self._action)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def _form_page(self):
        page = QWidget(self.stack)
        page.setStyleSheet("background: transparent;")
        layout = QFormLayout(page)
        layout.setContentsMargins(0, 12, 0, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(14)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        return page, layout

    def _line_with_browse(self, title, filter_text):
        line = LineEdit(self)
        button = PushButton(FIF.FOLDER, "选择", self)
        line.setFixedHeight(44)
        button.setFixedHeight(44)
        button.clicked.connect(
            lambda: self._choose_file(line, title, filter_text)
        )
        wrapper = QWidget(self)
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(line, 1)
        row.addWidget(button)
        return wrapper, line

    def _buildPages(self):
        page, form = self._form_page()
        target_wrapper, target = self._line_with_browse("选择程序", "Programs (*.exe *.com *.bat *.cmd);;All files (*.*)")
        arguments = LineEdit(self)
        arguments.setFixedHeight(44)
        arguments.setPlaceholderText("可选，例如 --profile default")
        working_wrapper, working_dir = self._line_with_browse("选择工作目录", "All files (*.*)")
        wait = CheckBox("等待程序结束后继续", self)
        form.addRow("程序或命令", target_wrapper)
        form.addRow("参数", arguments)
        form.addRow("工作目录", working_wrapper)
        form.addRow("执行方式", wait)
        self._pages["program"] = page
        self._widgets["program"] = (target, arguments, working_dir, wait)
        self.stack.addWidget(page)

        page, form = self._form_page()
        command = PlainTextEdit(self)
        command.setPlaceholderText("输入 Windows Shell 命令")
        command.setFixedHeight(110)
        shell_wrapper, shell_working_dir = self._line_with_browse("选择工作目录", "All files (*.*)")
        shell_wait = CheckBox("等待命令结束后继续", self)
        show_console = CheckBox("显示控制台窗口", self)
        warning = BodyLabel("Shell 命令会直接在本机执行，请确认内容可信。", self)
        warning.setStyleSheet("color: #d13438;")
        form.addRow("命令", command)
        form.addRow("工作目录", shell_wrapper)
        form.addRow("执行方式", shell_wait)
        form.addRow("窗口", show_console)
        form.addRow("提示", warning)
        self._pages["shell"] = page
        self._widgets["shell"] = (command, shell_working_dir, shell_wait, show_console)
        self.stack.addWidget(page)

        page, form = self._form_page()
        url = LineEdit(self)
        url.setFixedHeight(44)
        url.setPlaceholderText("例如 https://example.com")
        form.addRow("网页地址", url)
        self._pages["url"] = page
        self._widgets["url"] = (url,)
        self.stack.addWidget(page)

        page, form = self._form_page()
        path = LineEdit(self)
        file_button = PushButton(FIF.FOLDER, "文件", self)
        folder_button = PushButton(FIF.FOLDER, "文件夹", self)
        path.setFixedHeight(44)
        file_button.setFixedHeight(44)
        folder_button.setFixedHeight(44)
        file_button.clicked.connect(lambda: self._choose_file(path, "选择文件", "All files (*.*)"))
        folder_button.clicked.connect(lambda: self._choose_folder(path))
        buttons = QWidget(self)
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addWidget(path, 1)
        buttons_layout.addWidget(file_button)
        buttons_layout.addWidget(folder_button)
        form.addRow("目标", buttons)
        self._pages["path"] = page
        self._widgets["path"] = (path,)
        self.stack.addWidget(page)

        page, form = self._form_page()
        seconds = SpinBox(self)
        seconds.setFixedHeight(44)
        seconds.setRange(1, 86400)
        seconds.setSuffix(" 秒")
        form.addRow("等待时间", seconds)
        self._pages["delay"] = page
        self._widgets["delay"] = (seconds,)
        self.stack.addWidget(page)

    def _choose_file(self, line, title, filter_text):
        path, _ = QFileDialog.getOpenFileName(self, title, "", filter_text)
        if path:
            line.setText(path)

    def _choose_folder(self, line):
        path = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if path:
            line.setText(path)

    def _onTypeChanged(self, index):
        action_type = ACTION_TYPES[index]
        self.stack.setCurrentWidget(self._pages[action_type])

    def _load(self, action):
        action_type = action["type"] if action else "program"
        self.typeCombo.setCurrentIndex(max(0, ACTION_TYPES.index(action_type)))
        if not action:
            return
        widgets = self._widgets[action_type]
        if action_type == "program":
            widgets[0].setText(action["target"])
            widgets[1].setText(action["arguments"])
            widgets[2].setText(action["working_dir"])
            widgets[3].setChecked(action["wait"])
        elif action_type == "shell":
            widgets[0].setPlainText(action["command"])
            widgets[1].setText(action["working_dir"])
            widgets[2].setChecked(action["wait"])
            widgets[3].setChecked(action["show_console"])
        elif action_type in {"url", "path"}:
            widgets[0].setText(action["target"])
        else:
            widgets[0].setValue(action["seconds"])

    def getData(self) -> dict:
        action_type = ACTION_TYPES[self.typeCombo.currentIndex()]
        old_id = self._action.get("id") if self._action else new_id()
        widgets = self._widgets[action_type]
        if action_type == "program":
            return {"id": old_id, "type": action_type, "target": widgets[0].text().strip(), "arguments": widgets[1].text(), "working_dir": widgets[2].text().strip(), "wait": widgets[3].isChecked()}
        if action_type == "shell":
            return {"id": old_id, "type": action_type, "command": widgets[0].toPlainText().strip(), "working_dir": widgets[1].text().strip(), "wait": widgets[2].isChecked(), "show_console": widgets[3].isChecked()}
        if action_type in {"url", "path"}:
            return {"id": old_id, "type": action_type, "target": widgets[0].text().strip()}
        return {"id": old_id, "type": action_type, "seconds": widgets[0].value()}

    def validate(self) -> bool:
        error = validate_action(self.getData())
        if error:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.error("动作无效", error, duration=3000, position=InfoBarPosition.TOP, parent=self)
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
        self.sourceCombo.setFixedHeight(44)
        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("搜索图标名称")
        self.searchEdit.setFixedHeight(44)
        self.browseButton = PushButton(FIF.FOLDER, "选择文件", self)
        self.browseButton.setFixedHeight(44)
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
        self.gridWidget = QWidget(self.contentWidget)
        self.gridWidget.setStyleSheet("background: transparent;")
        self.gridWidget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.grid = FlowLayout(self.gridWidget, needAni=False, isTight=True)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.scrollArea.setWidget(self.contentWidget)
        self._buttons = []
        self._selected = {"type": "fluent", "name": "APPLICATION"}
        self._external_image = None
        self.sourceCombo.currentIndexChanged.connect(self._sourceChanged)
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
        self._clearGrid()
        for name, icon in FIF.__members__.items():
            button = ToggleToolButton(icon, self.gridWidget)
            button.setFixedSize(56, 56)
            setFluentToolTip(button, name)
            button.setAccessibleName(name)
            button.clicked.connect(lambda _checked=False, name=name: self._selectFluent(name))
            self.grid.addWidget(button)
            self._buttons.append(button)
        self._refreshGridLayout()
        name = self._selected.get("name", "APPLICATION")
        self._selectFluent(name if name in FIF.__members__ else "APPLICATION")

    def _clearGrid(self):
        self.grid.removeAllWidgets()
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()

    def _refreshGridLayout(self):
        self.grid.invalidate()
        width = max(1, self.scrollArea.viewport().width() - 8)
        self.gridWidget.setFixedHeight(self.grid.heightForWidth(width))
        self.gridWidget.updateGeometry()
        self.contentWidget.updateGeometry()
        self.grid.activate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "grid"):
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
        query = text.strip().lower()
        for button in self._buttons:
            button.setVisible(not query or query in button.toolTip().lower())
        self._refreshGridLayout()

    def _selectFluent(self, name):
        self._selected = {"type": "fluent", "name": name}
        self._external_image = None
        self.previewIcon.setIcon(getattr(FIF, name, FIF.APPLICATION))
        self.previewLabel.setText(name)
        for button in self._buttons:
            button.setChecked(button.toolTip() == name)

    def _browse(self):
        image_source = self.sourceCombo.currentIndex() == 1
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图片" if image_source else "选择图标资源",
            "",
            (
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)"
                if image_source
                else "图标资源 (*.ico *.exe *.dll)"
            ),
        )
        if not path:
            return
        try:
            images = extract_icon_images(path)
        except HomeCardError as error:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.error("图标读取失败", str(error), duration=3000, position=InfoBarPosition.TOP, parent=self)
            return
        self._clearGrid()
        for index, image in enumerate(images):
            button = ToggleToolButton(
                QIcon(QPixmap.fromImage(image)), self.gridWidget
            )
            button.setFixedSize(56, 56)
            setFluentToolTip(button, f"图标 {index + 1}")
            button.clicked.connect(
                lambda _checked=False, image=image, button=button: self._selectImage(image, button)
            )
            self.grid.addWidget(button)
            self._buttons.append(button)
        self._refreshGridLayout()
        self._selectImage(images[0], self._buttons[0])

    def _selectImage(self, image, selected_button=None):
        self._external_image = image.copy()
        self._selected = {"type": "image"}
        self.previewIcon.setIcon(QIcon(QPixmap.fromImage(image)))
        self.previewLabel.setText(
            selected_button.toolTip() if selected_button else "自定义图标"
        )
        for button in self._buttons:
            button.setChecked(button is selected_button)

    def selected(self):
        return deepcopy(self._selected), self._external_image.copy() if self._external_image else None


class CustomCardDialog(_ResponsiveMessageBox):
    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        data = deepcopy(data) if isinstance(data, dict) else {}
        self.cardId = data.get("id") or new_id()
        self._icon = deepcopy(data.get("icon") or {"type": "fluent", "name": "APPLICATION"})
        self._staged_image = None
        self.titleLabel = SubtitleLabel("编辑主页卡片" if data else "新建主页卡片", self)
        self.descriptionLabel = CaptionLabel(
            "设置卡片的显示信息，以及点击后依次执行的动作。", self
        )
        self.titleEdit = LineEdit(self)
        self.titleEdit.setFixedHeight(44)
        self.titleEdit.setMaxLength(40)
        self.titleEdit.setPlaceholderText("例如：打开课程表")
        self.descriptionEdit = LineEdit(self)
        self.descriptionEdit.setFixedHeight(44)
        self.descriptionEdit.setMaxLength(120)
        self.descriptionEdit.setPlaceholderText("简短说明卡片用途")
        self.iconPreview = IconWidget(icon_for_data(self._icon), self)
        self.iconPreview.setFixedSize(40, 40)
        setFluentToolTip(self.iconPreview, "当前图标")
        self.iconCard = SimpleCardWidget(self)
        self.iconCard.setMinimumHeight(76)
        icon_title = StrongBodyLabel("卡片图标", self.iconCard)
        icon_description = CaptionLabel("选择一个容易识别的图标", self.iconCard)
        self.iconSelectButton = PushButton(FIF.PALETTE, "选择图标", self)
        self.iconSelectButton.setFixedHeight(44)
        self.iconSelectButton.clicked.connect(self._chooseIcon)
        icon_card_layout = QHBoxLayout(self.iconCard)
        icon_card_layout.setContentsMargins(16, 12, 16, 12)
        icon_card_layout.setSpacing(12)
        icon_text_layout = QVBoxLayout()
        icon_text_layout.setContentsMargins(0, 0, 0, 0)
        icon_text_layout.setSpacing(2)
        icon_text_layout.addWidget(icon_title)
        icon_text_layout.addWidget(icon_description)
        icon_card_layout.addWidget(self.iconPreview)
        icon_card_layout.addLayout(icon_text_layout, 1)
        icon_card_layout.addWidget(self.iconSelectButton)
        initial_actions = data.get("actions") if data else None
        if not initial_actions:
            initial_actions = [{"id": new_id(), "type": "program", "target": "", "arguments": "", "working_dir": "", "wait": False}]
        self.actionList = ActionListWidget(initial_actions, self)
        self.addActionButton = PushButton(FIF.ADD, "添加动作", self)
        self.addActionButton.setFixedHeight(44)
        self.addActionButton.clicked.connect(self._addAction)
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.scrollArea.setMinimumHeight(100)
        self.scrollArea.setMaximumHeight(560)
        self.form = QWidget(self.scrollArea)
        self.form.setStyleSheet("background: transparent;")
        form_layout = QVBoxLayout(self.form)
        form_layout.setContentsMargins(6, 6, 6, 6)
        form_layout.setSpacing(10)
        form_layout.addWidget(StrongBodyLabel("标题", self.form))
        form_layout.addWidget(self.titleEdit)
        form_layout.addWidget(StrongBodyLabel("简介", self.form))
        form_layout.addWidget(self.descriptionEdit)
        form_layout.addSpacing(4)
        form_layout.addWidget(self.iconCard)
        form_layout.addSpacing(10)
        form_layout.addWidget(StrongBodyLabel("动作列表", self.form))
        form_layout.addWidget(
            CaptionLabel(
                "触摸正文可滚动；从每行动作左侧的手柄拖动排序。",
                self.form,
            )
        )
        form_layout.addWidget(self.actionList)
        form_layout.addWidget(self.addActionButton)
        self.scrollArea.setWidget(self.form)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descriptionLabel)
        self.viewLayout.addWidget(self.scrollArea)
        self.setPreferredSize(720, 700)
        self.titleEdit.setText(str(data.get("title", "")))
        self.descriptionEdit.setText(str(data.get("description", "")))
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.actionList.setScrollArea(self.scrollArea)

    def _chooseIcon(self):
        dialog = IconPickerDialog(_dialog_host(self))
        try:
            if not dialog.exec():
                return
            selected, image = dialog.selected()
        finally:
            dialog.deleteLater()
        if selected["type"] == "fluent":
            self._icon = selected
            self._staged_image = None
            self.iconPreview.setIcon(icon_for_data(self._icon))
        else:
            self._staged_image = image
            self._icon = {"type": "image"}
            self.iconPreview.setIcon(QIcon(QPixmap.fromImage(image)))

    def _addAction(self):
        dialog = ActionEditorDialog(parent=_dialog_host(self))
        try:
            if not dialog.exec():
                return
            action = dialog.getData()
        finally:
            dialog.deleteLater()
        self.actionList.addAction(action)

    def validate(self) -> bool:
        title = self.titleEdit.text().strip()
        if not title:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.error("无法保存", "请输入卡片标题", duration=3000, position=InfoBarPosition.TOP, parent=self)
            return False
        actions = self.actionList.actions()
        if not actions:
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.error("无法保存", "至少添加一个动作", duration=3000, position=InfoBarPosition.TOP, parent=self)
            return False
        for action in actions:
            error = validate_action(action)
            if error:
                from qfluentwidgets import InfoBar, InfoBarPosition

                InfoBar.error("动作无效", error, duration=3000, position=InfoBarPosition.TOP, parent=self)
                return False
        if self._staged_image is not None:
            try:
                self._icon = {"type": "file", "file": save_icon_image(self._staged_image)}
                self._staged_image = None
            except HomeCardError as error:
                from qfluentwidgets import InfoBar, InfoBarPosition

                InfoBar.error("无法保存图标", str(error), duration=3000, position=InfoBarPosition.TOP, parent=self)
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


__all__ = ["CustomCardDialog"]
