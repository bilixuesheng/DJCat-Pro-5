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
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FlowLayout,
    LineEdit,
    MessageBoxBase,
    PlainTextEdit,
    PushButton,
    SearchLineEdit,
    ScrollArea,
    SpinBox,
    SubtitleLabel,
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


ACTION_LABELS = {
    "program": "直接启动程序",
    "shell": "执行 Shell 命令",
    "url": "打开网页",
    "path": "打开文件或文件夹",
    "delay": "等待",
}


class DragHandleButton(ToolButton):
    dragStarted = Signal(QPoint)
    dragMoved = Signal(QPoint)
    dragFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(FIF.MOVE)
        self.setFixedSize(44, 44)
        self.setToolTip("拖动调整动作顺序")
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
        self.summary = SubtitleLabel(self)
        self.detail = BodyLabel(self)
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
            button.setToolTip(name)
            button.setAccessibleName(name)
        self.editButton.clicked.connect(self.editRequested)
        self.deleteButton.clicked.connect(self.deleteRequested)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(8)
        self._layout.addWidget(self.dragHandle)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(self.summary)
        text_layout.addWidget(self.detail)
        self._layout.addLayout(text_layout, 1)
        self._layout.addWidget(self.editButton)
        self._layout.addWidget(self.deleteButton)
        self.setMinimumHeight(68)
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
        self.detail.setToolTip(detail)

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
        dialog = ActionEditorDialog(row.action, self.window())
        if dialog.exec():
            row.setData(dialog.getData())
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


class ActionEditorDialog(MessageBoxBase):
    def __init__(self, action=None, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("配置动作", self)
        self.typeCombo = ComboBox(self)
        for action_type in ACTION_TYPES:
            self.typeCombo.addItem(ACTION_LABELS[action_type])
        self.stack = QStackedWidget(self)
        self._pages = {}
        self._widgets = {}
        self._buildPages()
        self.typeCombo.currentIndexChanged.connect(self._onTypeChanged)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.typeCombo)
        self.viewLayout.addWidget(self.stack)
        self.widget.setMinimumWidth(560)
        self._action = normalize_action(action) if action else None
        self._load(self._action)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

    def _form_page(self):
        page = QWidget(self.stack)
        layout = QFormLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setVerticalSpacing(10)
        return page, layout

    def _line_with_browse(self, title, filter_text):
        line = LineEdit(self)
        button = PushButton(FIF.FOLDER, "选择", self)
        button.setMinimumHeight(40)
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
        url.setPlaceholderText("例如 https://example.com")
        form.addRow("网页地址", url)
        self._pages["url"] = page
        self._widgets["url"] = (url,)
        self.stack.addWidget(page)

        page, form = self._form_page()
        path = LineEdit(self)
        file_button = PushButton(FIF.FOLDER, "文件", self)
        folder_button = PushButton(FIF.FOLDER, "文件夹", self)
        file_button.setMinimumHeight(40)
        folder_button.setMinimumHeight(40)
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


class IconPickerDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("选择图标", self)
        self.sourceCombo = ComboBox(self)
        self.sourceCombo.addItem("QWF 图标库")
        self.sourceCombo.addItem("图片 / ICO / EXE / DLL")
        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("搜索图标名称")
        self.browseButton = PushButton(FIF.FOLDER, "选择文件", self)
        self.browseButton.setMinimumHeight(40)
        self.scrollArea = ScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setMinimumWidth(620)
        self.scrollArea.setMinimumHeight(300)
        self.gridWidget = QWidget(self.scrollArea)
        self.gridWidget.setMinimumWidth(600)
        self.grid = FlowLayout(self.gridWidget, needAni=False)
        self.grid.setContentsMargins(8, 8, 8, 8)
        self.scrollArea.setWidget(self.gridWidget)
        self._buttons = []
        self._selected = {"type": "fluent", "name": "APPLICATION"}
        self._external_image = None
        self.sourceCombo.currentIndexChanged.connect(self._sourceChanged)
        self.searchEdit.textChanged.connect(self._filterIcons)
        self.browseButton.clicked.connect(self._browse)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.sourceCombo)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.searchEdit, 1)
        toolbar.addWidget(self.browseButton)
        self.viewLayout.addLayout(toolbar)
        self.viewLayout.addWidget(self.scrollArea)
        self.widget.setMinimumWidth(650)
        self.yesButton.setText("选择")
        self.cancelButton.setText("取消")
        self._renderFluentIcons()
        self._sourceChanged()

    def _renderFluentIcons(self):
        self._clearGrid()
        for name, icon in FIF.__members__.items():
            button = ToolButton(icon, self.gridWidget)
            button.setFixedSize(52, 52)
            button.setCheckable(True)
            button.setToolTip(name)
            button.setAccessibleName(name)
            button.clicked.connect(lambda _checked=False, name=name: self._selectFluent(name))
            self.grid.addWidget(button)
            self._buttons.append(button)

    def _clearGrid(self):
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()

    def _sourceChanged(self):
        source = "fluent" if self.sourceCombo.currentIndex() == 0 else "file"
        fluent = source == "fluent"
        self.searchEdit.setVisible(fluent)
        self.browseButton.setVisible(not fluent)
        if fluent:
            self._renderFluentIcons()
        else:
            self._clearGrid()

    def _filterIcons(self, text):
        query = text.strip().lower()
        for button in self._buttons:
            button.setVisible(not query or query in button.toolTip().lower())

    def _selectFluent(self, name):
        self._selected = {"type": "fluent", "name": name}
        self._external_image = None
        for button in self._buttons:
            button.setChecked(button.toolTip() == name)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择图标文件",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;Icons and binaries (*.ico *.exe *.dll);;All files (*.*)",
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
            button = ToolButton(QIcon(QPixmap.fromImage(image)), self.gridWidget)
            button.setFixedSize(52, 52)
            button.setCheckable(True)
            button.setToolTip(f"图标 {index + 1}")
            button.clicked.connect(
                lambda _checked=False, image=image, button=button: self._selectImage(image, button)
            )
            self.grid.addWidget(button)
            self._buttons.append(button)
        self._selectImage(images[0], self._buttons[0])

    def _selectImage(self, image, selected_button=None):
        self._external_image = image.copy()
        self._selected = {"type": "image"}
        for button in self._buttons:
            button.setChecked(button is selected_button)

    def selected(self):
        return deepcopy(self._selected), self._external_image.copy() if self._external_image else None


class CustomCardDialog(MessageBoxBase):
    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        data = deepcopy(data) if isinstance(data, dict) else {}
        self.cardId = data.get("id") or new_id()
        self._icon = deepcopy(data.get("icon") or {"type": "fluent", "name": "APPLICATION"})
        self._staged_image = None
        self.titleLabel = SubtitleLabel("编辑主页卡片" if data else "新建主页卡片", self)
        self.titleEdit = LineEdit(self)
        self.titleEdit.setMaxLength(40)
        self.titleEdit.setPlaceholderText("例如：打开课程表")
        self.descriptionEdit = LineEdit(self)
        self.descriptionEdit.setMaxLength(120)
        self.descriptionEdit.setPlaceholderText("简短说明卡片用途")
        self.iconButton = ToolButton(self)
        self.iconButton.setFixedSize(56, 56)
        self.iconButton.setIcon(icon_for_data(self._icon))
        self.iconButton.setToolTip("当前图标")
        self.iconSelectButton = PushButton(FIF.PALETTE, "选择图标", self)
        self.iconSelectButton.setMinimumHeight(44)
        self.iconSelectButton.clicked.connect(self._chooseIcon)
        initial_actions = data.get("actions") if data else None
        if not initial_actions:
            initial_actions = [{"id": new_id(), "type": "program", "target": "", "arguments": "", "working_dir": "", "wait": False}]
        self.actionList = ActionListWidget(initial_actions, self)
        self.addActionButton = PushButton(FIF.ADD, "添加动作", self)
        self.addActionButton.setMinimumHeight(44)
        self.addActionButton.clicked.connect(self._addAction)
        self.scrollArea = ScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setMinimumWidth(620)
        self.scrollArea.setMinimumHeight(300)
        self.form = QWidget(self.scrollArea)
        self.form.setMinimumWidth(600)
        form_layout = QVBoxLayout(self.form)
        form_layout.setContentsMargins(4, 4, 4, 4)
        fields = QFormLayout()
        fields.setVerticalSpacing(10)
        fields.addRow("标题", self.titleEdit)
        fields.addRow("简介", self.descriptionEdit)
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.iconButton)
        icon_row.addWidget(self.iconSelectButton)
        icon_row.addStretch(1)
        fields.addRow("图标", icon_row)
        form_layout.addLayout(fields)
        form_layout.addWidget(SubtitleLabel("动作列表", self.form))
        form_layout.addWidget(BodyLabel("正文区域可滚动；请从每行左侧的移动手柄拖动排序。", self.form))
        form_layout.addWidget(self.actionList)
        form_layout.addWidget(self.addActionButton)
        self.scrollArea.setWidget(self.form)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.scrollArea)
        self.widget.setMinimumWidth(680)
        self.titleEdit.setText(str(data.get("title", "")))
        self.descriptionEdit.setText(str(data.get("description", "")))
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")
        self.actionList.setScrollArea(self.scrollArea)

    def _chooseIcon(self):
        dialog = IconPickerDialog(self)
        if not dialog.exec():
            return
        selected, image = dialog.selected()
        if selected["type"] == "fluent":
            self._icon = selected
            self._staged_image = None
            self.iconButton.setIcon(icon_for_data(self._icon))
        else:
            self._staged_image = image
            self._icon = {"type": "image"}
            self.iconButton.setIcon(QIcon(QPixmap.fromImage(image)))

    def _addAction(self):
        dialog = ActionEditorDialog(parent=self)
        if dialog.exec():
            self.actionList.addAction(dialog.getData())

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
