from copy import deepcopy
from threading import RLock
from time import monotonic

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CardWidget,
    FlowLayout,
    IconWidget,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    RoundMenu,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
    qconfig,
    setCustomStyleSheet,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.home_cards import (
    ActionSequenceWorker,
    iconForData,
    normalizeCustomCards,
    normalizePinnedCards,
    removeCachedIcon,
)
from app.config.cfg import DEFAULT_HOME_CARDS, cfg
from app.view.components.banner_widget import BannerWidget
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import LabelElideFilter
from app.view.components.tool_tip import setFluentToolTip

DEFAULT_CARD_INFO = {
    "全屏投送": (FIF.FULL_SCREEN, "将信息以大字全屏展示"),
    "考试倒计时": (FIF.CALENDAR, "设定考试时长并全屏显示倒计时"),
    "全屏时钟": (FIF.STOP_WATCH, "全屏显示当前系统时间"),
    "定时播报": (FIF.MEGAPHONE, "设置每日定点语音播报时间或播放音频"),
    "自动任务": (FIF.HISTORY, "按时间或软件行为执行主页卡片和自定义动作"),
    "定时关机": (FIF.POWER_BUTTON, "设置指定时间提示或自动关闭计算机"),
}


class ActionCard(CardWidget):
    dragStarted = Signal(object, QPoint)
    dragMoved = Signal(object, QPoint)
    dragFinished = Signal(object)

    def __init__(self, icon, title, content, parent=None):
        # CardWidget 构造期间可能进入 event()，拖动状态需先初始化。
        self._editing = False
        self._dragging = False
        self._drag_position = QPoint()
        self._press_position = None
        self._editable = False
        self._touch_button = None
        super().__init__(parent)
        self.setFixedSize(210, 120)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setClickEnabled(True)

        qconfig.themeColor.valueChanged.connect(self.update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 12, 16)
        top_layout = QHBoxLayout()
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(18, 18)
        title_label = TitleLabel(title, self)
        title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        setFluentToolTip(title_label, title)
        self.iconWidget = icon_widget
        self.titleLabel = title_label
        self.contentLabel = BodyLabel(content, self)
        self.contentLabel.setWordWrap(True)
        self.contentLabel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.contentLabel.setFixedHeight(
            self.contentLabel.fontMetrics().lineSpacing() * 2
        )
        setFluentToolTip(self.contentLabel, content)
        self._titleElideFilter = LabelElideFilter(self, maximumLines=1)
        self._descriptionElideFilter = LabelElideFilter(self, maximumLines=2)
        self.titleLabel.installEventFilter(self._titleElideFilter)
        self.contentLabel.installEventFilter(self._descriptionElideFilter)
        self.editButton = ToolButton(FIF.EDIT, self)
        self.editButton.setFixedSize(24, 24)
        setFluentToolTip(self.editButton, "编辑主页卡片")
        self.editButton.setAccessibleName("编辑主页卡片")
        self.editButton.hide()
        self.deleteButton = ToolButton(FIF.DELETE, self)
        self.deleteButton.setFixedSize(26, 26)
        self.deleteButton.setEnabled(False)
        setFluentToolTip(self.deleteButton, "删除主页卡片")
        self.deleteButton.setAccessibleName(f"删除{title}")
        deleteButtonStyle = """
            ToolButton {
                border: none;
                border-radius: 13px;
                background: #d13438;
            }
            ToolButton:disabled {
                background: rgba(128, 128, 128, 0.35);
            }
        """
        setCustomStyleSheet(self.deleteButton, deleteButtonStyle, deleteButtonStyle)
        self.deleteButton.hide()
        top_layout.addWidget(icon_widget)
        top_layout.addWidget(title_label, 1)
        top_layout.addWidget(self.editButton)
        top_layout.addWidget(self.deleteButton)
        layout.addLayout(top_layout)
        layout.addWidget(self.contentLabel)
        layout.addStretch(1)

    def sizeHint(self):
        # FlowLayout uses sizeHint instead of the fixed geometry when it
        # calculates rows; keep the card's compact dimensions authoritative.
        return QSize(210, 120)

    def setRemovable(self, removable: bool) -> None:
        self.deleteButton.setEnabled(removable)
        self.deleteButton.setToolTip("删除主页卡片" if removable else "系统卡片不可删除")

    def setEditable(self, editable: bool) -> None:
        self._editable = editable
        self.editButton.setVisible(editable and self._editing)

    def setCardData(self, icon, title: str, content: str) -> None:
        self.iconWidget.setIcon(icon)
        self.titleLabel.setText(title)
        self.titleLabel.setToolTip(title)
        self.contentLabel.setText(content)
        self.contentLabel.setToolTip(content)

    def setEditing(self, editing):
        self._editing = editing
        self._dragging = False
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, editing)
        self.deleteButton.setVisible(editing)
        self.editButton.setVisible(editing and self._editable)
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if editing
            else Qt.CursorShape.PointingHandCursor
        )
        self.update()

    def _start_dragging(self, global_position):
        self._dragging = True
        self._drag_position = global_position
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.dragStarted.emit(self, global_position)

    def _finish_dragging(self):
        if not self._dragging:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.dragFinished.emit(self)

    def _touchButtonAt(self, position):
        buttons = [
            button
            for button in (self.editButton, self.deleteButton)
            if not button.isHidden()
            and button.isEnabled()
            and button.geometry().adjusted(-8, -8, 8, 8).contains(position)
        ]
        return min(
            buttons,
            key=lambda button: (
                button.geometry().center() - position
            ).manhattanLength(),
            default=None,
        )

    def event(self, event):
        if self._editing and event.type() == QEvent.Type.TouchBegin:
            point = event.points()[0]
            self._touch_button = self._touchButtonAt(
                point.position().toPoint()
            )
            if self._touch_button is not None:
                self._touch_button.setDown(True)
                event.accept()
                return True
            self._start_dragging(point.globalPosition().toPoint())
            event.accept()
            return True
        if self._editing and event.type() == QEvent.Type.TouchUpdate:
            if self._touch_button is not None and event.points():
                self._touch_button.setDown(
                    self._touchButtonAt(
                        event.points()[0].position().toPoint()
                    )
                    is self._touch_button
                )
                event.accept()
                return True
            if self._dragging and event.points():
                position = event.points()[0].globalPosition().toPoint()
                if position == self._drag_position:
                    event.accept()
                    return True
                self._drag_position = position
                self.dragMoved.emit(
                    self,
                    position,
                )
            event.accept()
            return True
        if self._editing and event.type() in (
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        ):
            if self._touch_button is not None:
                button = self._touch_button
                self._touch_button = None
                shouldClick = (
                    event.type() == QEvent.Type.TouchEnd and button.isDown()
                )
                button.setDown(False)
                if shouldClick:
                    button.click()
                event.accept()
                return True
            self._finish_dragging()
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            self._press_position = None
            event.accept()
            return
        if self._editing and event.button() == Qt.MouseButton.LeftButton:
            self._start_dragging(event.globalPosition().toPoint())
            event.accept()
            return
        self._press_position = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            position = event.globalPosition().toPoint()
            if position != self._drag_position:
                self._drag_position = position
                self.dragMoved.emit(self, position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            self._press_position = None
            self.isPressed = False
            self._updateBackgroundColor()
            event.accept()
            return
        if self._editing:
            self._finish_dragging()
            event.accept()
            return
        release_position = event.globalPosition().toPoint()
        should_click = (
            self._press_position is not None
            and self.rect().contains(event.position().toPoint())
            and (release_position - self._press_position).manhattanLength()
            < QApplication.startDragDistance()
        )
        self._press_position = None
        if not should_click:
            self.isPressed = False
            self._updateBackgroundColor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = (
            qconfig.themeColor.value
            if self._editing or self.isHover
            else QColor(128, 128, 128, 55)
        )
        width = 2 if self._editing or self.isHover else 1
        painter.setPen(QPen(color, width))
        inset = width / 2 + 1
        painter.drawRoundedRect(
            QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2),
            10,
            10,
        )


class HomePage(ScrollArea):
    applicationCardRemoved = Signal(object)
    applicationCardClicked = Signal(object)
    homeCardsChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._editing_cards = False
        self._card_order = []
        self._drag_offset = QPoint()
        self._drag_target = None
        self._drag_card = None
        self._drag_position = QPoint()
        self._applicationCardKeys = set()
        self._applicationCardData = {}
        self._customCardKeys = set()
        self._customCardData = {}
        self._customWorkers = {}
        self._cardsLock = RLock()
        self.setObjectName("HomePage")
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(10)

        self.titleWidget = QWidget(self.container)
        self.titleLayout = QVBoxLayout(self.titleWidget)
        self.titleLayout.setContentsMargins(30, 20, 30, 10)
        self.normalTitle = TitleLabel("主页", self.titleWidget)
        self.titleLayout.addWidget(self.normalTitle)
        self.vBoxLayout.addWidget(self.titleWidget)
        self.banner = BannerWidget(self.container)
        self.vBoxLayout.addWidget(self.banner)

        cfg.showBanner.valueChanged.connect(self.updateBannerVisibility)
        self.updateBannerVisibility()

        self.headerLayout = QHBoxLayout()
        self.headerLayout.setContentsMargins(30, 0, 30, 0)
        self.subTitle = SubtitleLabel("常用功能", self.container)
        self.editHint = BodyLabel("拖动卡片调整位置", self.container)
        self.editHint.hide()
        self.addBtn = ToolButton(FIF.ADD, self.container)
        setFluentToolTip(self.addBtn, "新建主页卡片")
        self.addBtn.setAccessibleName("新建主页卡片")
        self.addBtn.hide()
        self.addBtn.clicked.connect(self._showAddMenu)
        self.sortBtn = ToolButton(FIF.EDIT, self.container)
        setFluentToolTip(self.sortBtn, "调整卡片顺序")
        self.sortBtn.setAccessibleName("调整卡片顺序")
        self.addBtn.setFixedSize(self.sortBtn.sizeHint())
        self.sortBtn.clicked.connect(self._toggleCardEditing)
        self.headerLayout.addWidget(self.subTitle)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.editHint)
        self.headerLayout.addWidget(self.addBtn)
        self.headerLayout.addWidget(self.sortBtn)
        self.vBoxLayout.addLayout(self.headerLayout)

        self.cardsWidget = QWidget(self.container)
        self.flowLayout = FlowLayout(self.cardsWidget, needAni=False)
        self.flowLayout.setContentsMargins(20, 10, 20, 20)
        QTimer.singleShot(0, self, self._enableFlowAnimations)
        self.cardsWidget.setStyleSheet("background: transparent;")
        self.vBoxLayout.addWidget(self.cardsWidget)

        self.all_cards = {
            name: ActionCard(icon, name, description, self.cardsWidget)
            for name, (icon, description) in DEFAULT_CARD_INFO.items()
        }
        for name, card in self.all_cards.items():
            card.setRemovable(True)
            card.deleteButton.clicked.connect(
                lambda _checked=False, cardName=name: self._removeDefaultCard(cardName)
            )
            card.dragStarted.connect(self._startCardDrag)
            card.dragMoved.connect(self._moveCard)
            card.dragFinished.connect(self._finishCardDrag)

        customCards = normalizeCustomCards(cfg.customHomeCards.value)
        if customCards != cfg.customHomeCards.value:
            cfg.set(cfg.customHomeCards, customCards)
        for data in customCards:
            self._addCustomCard(data, persist=False)

        self._renderCards()
        self.vBoxLayout.addStretch(1)
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self.container.setStyleSheet("QWidget{background: transparent;}")
        self.dragPreview = QLabel(self.viewport())
        self.dragPreview.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.dragPreview.hide()
        self._dragScrollTimer = QTimer(self)
        self._dragScrollTimer.setInterval(16)
        self._dragScrollTimer.timeout.connect(self._autoScrollCardDrag)

    def _enableFlowAnimations(self):
        if self.flowLayout.needAni:
            return
        self.flowLayout.needAni = True
        for i in range(self.flowLayout.count()):
            w = self.flowLayout.itemAt(i).widget()
            if w and w.property("flowAni") is None:
                self.flowLayout._onWidgetAdded(w)
        self.flowLayout.setAnimation(180, QEasingCurve.Type.OutCubic)

    def homeCardEntries(self) -> list[dict]:
        entries = []
        for key in self._card_order:
            card = self.all_cards.get(key)
            if card is None:
                continue
            if key in DEFAULT_CARD_INFO:
                source = "default"
            elif key in self._customCardKeys:
                source = "custom"
            else:
                source = "application"
            entries.append(
                {
                    "key": key,
                    "source": source,
                    "title": card.titleLabel.text(),
                    "description": card.contentLabel.text(),
                    "icon": card.iconWidget.getIcon(),
                }
            )
        return entries

    def activateHomeCard(self, key: str) -> bool:
        if key not in self._card_order:
            return False
        card = self.all_cards.get(key)
        if card is None:
            return False
        card.clicked.emit()
        return True

    def homeCardEntry(self, key: str) -> dict | None:
        return next(
            (entry for entry in self.homeCardEntries() if entry["key"] == key),
            None,
        )

    def runCustomCard(self, key: str, confirmDuplicate=True) -> bool:
        if not key.startswith("custom:") or key not in self._card_order:
            return False
        return self._runCustomCard(
            key.removeprefix("custom:"),
            confirmDuplicate,
        )

    def setApplicationCards(self, cards) -> list[dict]:
        cards = normalizePinnedCards(cards)
        updatedCards = {
            f"app:{item['app_id']}:{item['preset_id']}": item
            for item in cards
        }
        if list(updatedCards.items()) == list(self._applicationCardData.items()):
            return cards

        for key in self._applicationCardKeys - updatedCards.keys():
            card = self.all_cards.pop(key, None)
            if card is not None:
                card.hide()
                card.deleteLater()
        for key, item in updatedCards.items():
            previous = self._applicationCardData.get(key)
            if previous == item:
                continue
            icon = QIcon(item["icon_path"]) if item.get("icon_path") else QIcon()
            if icon.isNull():
                icon = FIF.APPLICATION
            if key in self.all_cards:
                self.all_cards[key].setCardData(
                    icon,
                    item.get("title", "应用预设"),
                    item.get("description", ""),
                )
                continue
            card = ActionCard(
                icon,
                item.get("title", "应用预设"),
                item.get("description", ""),
                self.cardsWidget,
            )
            card.setRemovable(True)
            card.deleteButton.clicked.connect(
                lambda _checked=False, cardKey=key: self._removeApplicationCard(cardKey)
            )
            card.clicked.connect(
                lambda cardKey=key: self.applicationCardClicked.emit(
                    self._applicationCardData[cardKey]
                )
            )
            card.dragStarted.connect(self._startCardDrag)
            card.dragMoved.connect(self._moveCard)
            card.dragFinished.connect(self._finishCardDrag)
            card.setEditing(self._editing_cards)
            self.all_cards[key] = card
        self._applicationCardKeys = set(updatedCards)
        self._applicationCardData = {
            key: dict(item) for key, item in updatedCards.items()
        }
        self._renderCards()
        return cards

    def _addCustomCard(self, data, persist=True):
        normalized = normalizeCustomCards([data])
        if not normalized:
            return None
        data = normalized[0]
        card_id = data["id"]
        key = f"custom:{card_id}"
        old_card = self.all_cards.pop(key, None)
        if old_card is not None:
            old_card.deleteLater()
        card = ActionCard(
            iconForData(data.get("icon")),
            data["title"],
            data.get("description", ""),
            self.cardsWidget,
        )
        card.setRemovable(True)
        card.setEditable(True)
        card.deleteButton.clicked.connect(
            lambda _checked=False, customId=card_id: self._removeCustomCard(customId)
        )
        card.editButton.clicked.connect(
            lambda _checked=False, customId=card_id: self._editCustomCard(customId)
        )
        card.clicked.connect(
            lambda customId=card_id: self._runCustomCard(customId)
        )
        card.dragStarted.connect(self._startCardDrag)
        card.dragMoved.connect(self._moveCard)
        card.dragFinished.connect(self._finishCardDrag)
        self.all_cards[key] = card
        self._customCardKeys.add(key)
        with self._cardsLock:
            self._customCardData[card_id] = data
        if persist:
            self._saveCustomCards()
        return card

    def _saveCustomCards(self):
        with self._cardsLock:
            cfg.set(cfg.customHomeCards, deepcopy(list(self._customCardData.values())))

    def _activeCardNames(self):
        defaults = set(self._defaultCardNames())
        return defaults | self._customCardKeys | self._applicationCardKeys

    def _defaultCardNames(self):
        value = cfg.visibleDefaultHomeCards.value
        if not isinstance(value, list):
            return list(DEFAULT_HOME_CARDS)
        names = []
        for name in value:
            if isinstance(name, str) and name in DEFAULT_CARD_INFO and name not in names:
                names.append(name)
        return names

    def _saveVisibleDefaults(self, names):
        cfg.set(
            cfg.visibleDefaultHomeCards,
            [name for name in names if isinstance(name, str) and name in DEFAULT_CARD_INFO],
        )

    def shutdown(self):
        workers = [
            worker
            for cardWorkers in self._customWorkers.values()
            for worker in cardWorkers
        ]
        for worker in workers:
            worker.cancel()
        deadline = monotonic() + 1
        for worker in workers:
            worker.wait(max(0, deadline - monotonic()))
            worker.deleteLater()
        self._customWorkers.clear()

    def _showAddMenu(self):
        menu = RoundMenu(parent=self)
        menu.closedSignal.connect(menu.deleteLater)
        defaults = RoundMenu("默认", menu)
        defaults.setIcon(FIF.APPLICATION)
        visible = set(self._defaultCardNames())
        for name, (icon, _description) in DEFAULT_CARD_INFO.items():
            if name in visible:
                continue
            action = Action(icon, name, triggered=lambda _checked=False, cardName=name: self._restoreDefaultCard(cardName))
            defaults.addAction(action)
        if not defaults.actions():
            unavailable = Action(FIF.INFO, "已全部添加")
            unavailable.setEnabled(False)
            defaults.addAction(unavailable)
        menu.addMenu(defaults)
        menu.addAction(
            Action(
                FIF.EDIT,
                "自定义",
                triggered=lambda _checked=False: QTimer.singleShot(
                    0, self._createCustomCard
                ),
            )
        )
        menu.exec(self.addBtn.mapToGlobal(QPoint(0, self.addBtn.height())))

    def _restoreDefaultCard(self, name):
        names = self._defaultCardNames()
        if name not in DEFAULT_CARD_INFO or name in names:
            return
        names.append(name)
        self._saveVisibleDefaults(names)
        card = self.all_cards.get(name)
        if card is not None:
            card.setEditing(self._editing_cards)
        self._renderCards()
        self._saveCardOrder()

    def _removeDefaultCard(self, name):
        names = [item for item in self._defaultCardNames() if item != name]
        self._saveVisibleDefaults(names)
        self._card_order = [item for item in self._card_order if item != name]
        self._saveCardOrder()
        self._renderCards()

    def _createCustomCard(self):
        from app.view.components.home_card_dialog import CustomCardDialog

        dialog = CustomCardDialog(parent=self.window())
        try:
            if not dialog.exec():
                return
            data = dialog.getData()
        finally:
            dialog.deleteLater()
        card = self._addCustomCard(data)
        if card is not None:
            card.setEditing(self._editing_cards)
            self._renderCards()
            self._saveCardOrder()

    def _editCustomCard(self, card_id):
        from app.view.components.home_card_dialog import CustomCardDialog

        with self._cardsLock:
            data = deepcopy(self._customCardData.get(card_id))
        if data is None:
            return
        dialog = CustomCardDialog(data, self.window())
        try:
            if not dialog.exec():
                return
            updated = dialog.getData()
        finally:
            dialog.deleteLater()
        old_icon = data.get("icon")
        new_icon = updated.get("icon")
        if old_icon != new_icon:
            removeCachedIcon(old_icon)
        with self._cardsLock:
            self._customCardData[card_id] = updated
        card = self.all_cards.get(f"custom:{card_id}")
        if card is not None:
            card.setCardData(iconForData(new_icon), updated["title"], updated["description"])
        self._saveCustomCards()
        self._renderCards()

    def _removeCustomCard(self, card_id):
        with self._cardsLock:
            data = deepcopy(self._customCardData.get(card_id))
        if data is None:
            return
        box = MessageBox(
            "删除主页卡片",
            f"确定删除“{data['title']}”吗？",
            self.window(),
        )
        try:
            accepted = box.exec()
        finally:
            box.deleteLater()
        if not accepted:
            return
        for worker in self._customWorkers.get(card_id, []):
            worker.cancel()
        removeCachedIcon(data.get("icon"))
        with self._cardsLock:
            self._customCardData.pop(card_id, None)
        key = f"custom:{card_id}"
        card = self.all_cards.pop(key, None)
        self._customCardKeys.discard(key)
        if card is not None:
            card.deleteLater()
        self._card_order = [item for item in self._card_order if item != key]
        self._saveCustomCards()
        self._saveCardOrder()
        self._renderCards()

    def _getCustomActions(self, card_id):
        with self._cardsLock:
            data = self._customCardData.get(card_id)
            return deepcopy(data["actions"]) if data else None

    def _runCustomCard(self, card_id, confirmDuplicate=True):
        with self._cardsLock:
            if card_id not in self._customCardData:
                return False
        workers = self._customWorkers.setdefault(card_id, [])
        if workers:
            if not confirmDuplicate:
                return False
            box = MessageBox(
                "卡片正在运行",
                "是否再运行一遍该卡片的动作？",
                self.window(),
            )
            try:
                accepted = box.exec()
            finally:
                box.deleteLater()
            if not accepted:
                return False
        worker = ActionSequenceWorker(card_id, self._getCustomActions)
        worker.finished.connect(self._customSequenceFinished)
        workers.append(worker)
        worker.start()
        return True

    def _customSequenceFinished(self, card_id, errors):
        worker = self.sender()
        workers = self._customWorkers.get(card_id, [])
        if worker in workers:
            workers.remove(worker)
        if not workers:
            self._customWorkers.pop(card_id, None)
        if errors:
            showMainWindow = getattr(self.window(), "_showMainWindow", None)
            if callable(showMainWindow):
                showMainWindow()
            InfoBar.error(
                "卡片执行完成但有失败动作",
                "；".join(errors),
                duration=5000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
        if worker is not None:
            worker.deleteLater()

    def _removeApplicationCard(self, key: str) -> None:
        item = self._applicationCardData.get(key)
        card = self.all_cards.pop(key, None)
        self._applicationCardKeys.discard(key)
        self._applicationCardData.pop(key, None)
        if card is None:
            return
        card.deleteLater()
        self._card_order = [name for name in self._card_order if name != key]
        self._saveCardOrder()
        self._renderCards()
        if item is not None:
            self.applicationCardRemoved.emit(item)

    def _renderCards(self):
        active_names = self._activeCardNames()
        saved_order = cfg.homeCardOrder.value
        if not isinstance(saved_order, list):
            saved_order = []
        current_order = [
            name for name in saved_order if isinstance(name, str) and name in active_names
        ]
        for name in self.all_cards:
            if name in active_names and name not in current_order:
                current_order.append(name)
        self._card_order = current_order
        self._layoutCards()
        self.homeCardsChanged.emit(self.homeCardEntries())

    def _layoutCards(self):
        self.flowLayout.removeAllWidgets()
        for name, card in self.all_cards.items():
            card.setVisible(name in self._card_order)
        for name in self._card_order:
            card = self.all_cards[name]
            self.flowLayout.addWidget(card)
            card.show()
        self.flowLayout.invalidate()
        self.cardsWidget.updateGeometry()
        self.vBoxLayout.invalidate()
        self.vBoxLayout.activate()

    def _toggleCardEditing(self):
        self._editing_cards = not self._editing_cards
        self.editHint.setVisible(self._editing_cards)
        self.addBtn.setVisible(self._editing_cards)
        self.sortBtn.setIcon(FIF.ACCEPT if self._editing_cards else FIF.EDIT)
        self.sortBtn.setToolTip(
            "完成调整" if self._editing_cards else "调整卡片顺序"
        )
        self.sortBtn.setAccessibleName(self.sortBtn.toolTip())
        for card in self.all_cards.values():
            card.setEditing(self._editing_cards)

        # 编辑态由排序手势独占触控：卡片自己吃掉 TouchBegin，页面只调高拖动阈值、
        # 不释放手势——抓了又放会在 Qt 的手势管理器里留下残留，之后创建窗口时崩溃。
        self.setTouchScrollSuppressed(self._editing_cards)
        if not self._editing_cards:
            self._saveCardOrder()

    def _startCardDrag(self, card, global_position):
        self._drag_target = None
        self._drag_card = card
        self._drag_position = QPoint(global_position)
        self._drag_offset = global_position - card.mapToGlobal(QPoint())
        self.dragPreview.setPixmap(card.grab())
        self.dragPreview.resize(card.size())
        self._moveDragPreview(global_position)
        self.dragPreview.show()
        self.dragPreview.raise_()
        effect = QGraphicsOpacityEffect(card)
        effect.setOpacity(0.2)
        card.setGraphicsEffect(effect)
        self._dragScrollTimer.start()

    def _moveDragPreview(self, global_position):
        self.dragPreview.move(
            self.viewport().mapFromGlobal(global_position - self._drag_offset)
        )

    def _moveCard(self, card, global_position):
        self._drag_card = card
        self._drag_position = QPoint(global_position)
        self._moveDragPreview(global_position)
        self._reorderCardAt(card, global_position)

    def _reorderCardAt(self, card, global_position):
        position = self.cardsWidget.mapFromGlobal(global_position)
        hit_margin = 32
        target = min(
            (
                other
                for other in (self.all_cards[name] for name in self._card_order)
                if other is not card
                and other.geometry()
                .adjusted(-hit_margin, -hit_margin, hit_margin, hit_margin)
                .contains(position)
            ),
            key=lambda other: (
                other.geometry().center() - position
            ).manhattanLength(),
            default=None,
        )
        if target is None:
            self._drag_target = None
            return
        if target is self._drag_target:
            return
        self._drag_target = target

        card_name = next(
            name for name, value in self.all_cards.items() if value is card
        )
        target_name = next(
            name for name, value in self.all_cards.items() if value is target
        )
        from_index = self._card_order.index(card_name)
        to_index = self._card_order.index(target_name)
        self._card_order.pop(from_index)
        self._card_order.insert(to_index, card_name)
        # FlowLayout 的公开插入接口会二次移除同布局控件，需同步移动现有动画项。
        item = self.flowLayout._items.pop(from_index)
        animation = self.flowLayout._anis.pop(from_index)
        self.flowLayout._items.insert(to_index, item)
        self.flowLayout._anis.insert(to_index, animation)
        self.flowLayout.setGeometry(self.flowLayout.geometry())

    def _autoScrollCardDrag(self):
        if self._drag_card is None:
            return
        position = self.viewport().mapFromGlobal(self._drag_position)
        edge = min(72, max(28, self.viewport().height() // 4))
        if position.y() < edge:
            distance = position.y() - edge
        elif position.y() > self.viewport().height() - edge:
            distance = position.y() - (self.viewport().height() - edge)
        else:
            return

        scrollBar = self.verticalScrollBar()
        step = max(-18, min(18, distance // 4))
        previous = scrollBar.value()
        scrollBar.setValue(previous + step)
        if scrollBar.value() != previous:
            self._moveDragPreview(self._drag_position)
            self._reorderCardAt(self._drag_card, self._drag_position)

    def _finishCardDrag(self, card):
        self._dragScrollTimer.stop()
        self._drag_card = None
        self.dragPreview.hide()
        card.setGraphicsEffect(None)
        self._saveCardOrder()
        self.homeCardsChanged.emit(self.homeCardEntries())

    def _saveCardOrder(self):
        if cfg.homeCardOrder.value != self._card_order:
            cfg.set(cfg.homeCardOrder, list(self._card_order))

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def updateBannerVisibility(self):
        if cfg.showBanner.value:
            self.titleWidget.hide()
            self.banner.show()
        else:
            self.banner.hide()
            self.titleWidget.show()
