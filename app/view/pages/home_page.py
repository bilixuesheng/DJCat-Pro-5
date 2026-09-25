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
        self._dragPosition = QPoint()
        self._pressPosition = None
        self._editable = False
        self._touchButton = None
        super().__init__(parent)
        self.setFixedSize(210, 120)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setClickEnabled(True)

        qconfig.themeColor.valueChanged.connect(self.update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 12, 16)
        topLayout = QHBoxLayout()
        iconWidget = IconWidget(icon, self)
        iconWidget.setFixedSize(18, 18)
        titleLabel = TitleLabel(title, self)
        titleLabel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        setFluentToolTip(titleLabel, title)
        self.iconWidget = iconWidget
        self.titleLabel = titleLabel
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
        topLayout.addWidget(iconWidget)
        topLayout.addWidget(titleLabel, 1)
        topLayout.addWidget(self.editButton)
        topLayout.addWidget(self.deleteButton)
        layout.addLayout(topLayout)
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

    def _startDragging(self, globalPosition):
        self._dragging = True
        self._dragPosition = globalPosition
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.dragStarted.emit(self, globalPosition)

    def _finishDragging(self):
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
            self._touchButton = self._touchButtonAt(
                point.position().toPoint()
            )
            if self._touchButton is not None:
                self._touchButton.setDown(True)
                event.accept()
                return True
            self._startDragging(point.globalPosition().toPoint())
            event.accept()
            return True
        if self._editing and event.type() == QEvent.Type.TouchUpdate:
            if self._touchButton is not None and event.points():
                self._touchButton.setDown(
                    self._touchButtonAt(
                        event.points()[0].position().toPoint()
                    )
                    is self._touchButton
                )
                event.accept()
                return True
            if self._dragging and event.points():
                position = event.points()[0].globalPosition().toPoint()
                if position == self._dragPosition:
                    event.accept()
                    return True
                self._dragPosition = position
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
            if self._touchButton is not None:
                button = self._touchButton
                self._touchButton = None
                shouldClick = (
                    event.type() == QEvent.Type.TouchEnd and button.isDown()
                )
                button.setDown(False)
                if shouldClick:
                    button.click()
                event.accept()
                return True
            self._finishDragging()
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            self._pressPosition = None
            event.accept()
            return
        if self._editing and event.button() == Qt.MouseButton.LeftButton:
            self._startDragging(event.globalPosition().toPoint())
            event.accept()
            return
        self._pressPosition = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            position = event.globalPosition().toPoint()
            if position != self._dragPosition:
                self._dragPosition = position
                self.dragMoved.emit(self, position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            self._pressPosition = None
            self.isPressed = False
            self._updateBackgroundColor()
            event.accept()
            return
        if self._editing:
            self._finishDragging()
            event.accept()
            return
        releasePosition = event.globalPosition().toPoint()
        shouldClick = (
            self._pressPosition is not None
            and self.rect().contains(event.position().toPoint())
            and (releasePosition - self._pressPosition).manhattanLength()
            < QApplication.startDragDistance()
        )
        self._pressPosition = None
        if not shouldClick:
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
        self._editingCards = False
        self._cardOrder = []
        self._dragOffset = QPoint()
        self._dragTarget = None
        self._dragCard = None
        self._dragPosition = QPoint()
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

        self.allCards = {
            name: ActionCard(icon, name, description, self.cardsWidget)
            for name, (icon, description) in DEFAULT_CARD_INFO.items()
        }
        for name, card in self.allCards.items():
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
        for key in self._cardOrder:
            card = self.allCards.get(key)
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
        if key not in self._cardOrder:
            return False
        card = self.allCards.get(key)
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
        if not key.startswith("custom:") or key not in self._cardOrder:
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
            card = self.allCards.pop(key, None)
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
            if key in self.allCards:
                self.allCards[key].setCardData(
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
            card.setEditing(self._editingCards)
            self.allCards[key] = card
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
        cardId = data["id"]
        key = f"custom:{cardId}"
        oldCard = self.allCards.pop(key, None)
        if oldCard is not None:
            oldCard.deleteLater()
        card = ActionCard(
            iconForData(data.get("icon")),
            data["title"],
            data.get("description", ""),
            self.cardsWidget,
        )
        card.setRemovable(True)
        card.setEditable(True)
        card.deleteButton.clicked.connect(
            lambda _checked=False, customId=cardId: self._removeCustomCard(customId)
        )
        card.editButton.clicked.connect(
            lambda _checked=False, customId=cardId: self._editCustomCard(customId)
        )
        card.clicked.connect(
            lambda customId=cardId: self._runCustomCard(customId)
        )
        card.dragStarted.connect(self._startCardDrag)
        card.dragMoved.connect(self._moveCard)
        card.dragFinished.connect(self._finishCardDrag)
        self.allCards[key] = card
        self._customCardKeys.add(key)
        with self._cardsLock:
            self._customCardData[cardId] = data
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
        card = self.allCards.get(name)
        if card is not None:
            card.setEditing(self._editingCards)
        self._renderCards()
        self._saveCardOrder()

    def _removeDefaultCard(self, name):
        names = [item for item in self._defaultCardNames() if item != name]
        self._saveVisibleDefaults(names)
        self._cardOrder = [item for item in self._cardOrder if item != name]
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
            card.setEditing(self._editingCards)
            self._renderCards()
            self._saveCardOrder()

    def _editCustomCard(self, cardId):
        from app.view.components.home_card_dialog import CustomCardDialog

        with self._cardsLock:
            data = deepcopy(self._customCardData.get(cardId))
        if data is None:
            return
        dialog = CustomCardDialog(data, self.window())
        try:
            if not dialog.exec():
                return
            updated = dialog.getData()
        finally:
            dialog.deleteLater()
        oldIcon = data.get("icon")
        newIcon = updated.get("icon")
        if oldIcon != newIcon:
            removeCachedIcon(oldIcon)
        with self._cardsLock:
            self._customCardData[cardId] = updated
        card = self.allCards.get(f"custom:{cardId}")
        if card is not None:
            card.setCardData(iconForData(newIcon), updated["title"], updated["description"])
        self._saveCustomCards()
        self._renderCards()

    def _removeCustomCard(self, cardId):
        with self._cardsLock:
            data = deepcopy(self._customCardData.get(cardId))
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
        for worker in self._customWorkers.get(cardId, []):
            worker.cancel()
        removeCachedIcon(data.get("icon"))
        with self._cardsLock:
            self._customCardData.pop(cardId, None)
        key = f"custom:{cardId}"
        card = self.allCards.pop(key, None)
        self._customCardKeys.discard(key)
        if card is not None:
            card.deleteLater()
        self._cardOrder = [item for item in self._cardOrder if item != key]
        self._saveCustomCards()
        self._saveCardOrder()
        self._renderCards()

    def _getCustomActions(self, cardId):
        with self._cardsLock:
            data = self._customCardData.get(cardId)
            return deepcopy(data["actions"]) if data else None

    def _runCustomCard(self, cardId, confirmDuplicate=True):
        with self._cardsLock:
            if cardId not in self._customCardData:
                return False
        workers = self._customWorkers.setdefault(cardId, [])
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
        worker = ActionSequenceWorker(cardId, self._getCustomActions)
        worker.finished.connect(self._customSequenceFinished)
        workers.append(worker)
        worker.start()
        return True

    def _customSequenceFinished(self, cardId, errors):
        worker = self.sender()
        workers = self._customWorkers.get(cardId, [])
        if worker in workers:
            workers.remove(worker)
        if not workers:
            self._customWorkers.pop(cardId, None)
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
        card = self.allCards.pop(key, None)
        self._applicationCardKeys.discard(key)
        self._applicationCardData.pop(key, None)
        if card is None:
            return
        card.deleteLater()
        self._cardOrder = [name for name in self._cardOrder if name != key]
        self._saveCardOrder()
        self._renderCards()
        if item is not None:
            self.applicationCardRemoved.emit(item)

    def _renderCards(self):
        activeNames = self._activeCardNames()
        savedOrder = cfg.homeCardOrder.value
        if not isinstance(savedOrder, list):
            savedOrder = []
        currentOrder = [
            name for name in savedOrder if isinstance(name, str) and name in activeNames
        ]
        for name in self.allCards:
            if name in activeNames and name not in currentOrder:
                currentOrder.append(name)
        self._cardOrder = currentOrder
        self._layoutCards()
        self.homeCardsChanged.emit(self.homeCardEntries())

    def _layoutCards(self):
        self.flowLayout.removeAllWidgets()
        for name, card in self.allCards.items():
            card.setVisible(name in self._cardOrder)
        for name in self._cardOrder:
            card = self.allCards[name]
            self.flowLayout.addWidget(card)
            card.show()
        self.flowLayout.invalidate()
        self.cardsWidget.updateGeometry()
        self.vBoxLayout.invalidate()
        self.vBoxLayout.activate()

    def _toggleCardEditing(self):
        self._editingCards = not self._editingCards
        self.editHint.setVisible(self._editingCards)
        self.addBtn.setVisible(self._editingCards)
        self.sortBtn.setIcon(FIF.ACCEPT if self._editingCards else FIF.EDIT)
        self.sortBtn.setToolTip(
            "完成调整" if self._editingCards else "调整卡片顺序"
        )
        self.sortBtn.setAccessibleName(self.sortBtn.toolTip())
        for card in self.allCards.values():
            card.setEditing(self._editingCards)

        # 编辑态由排序手势独占触控：卡片自己吃掉 TouchBegin，页面只调高拖动阈值、
        # 不释放手势——抓了又放会在 Qt 的手势管理器里留下残留，之后创建窗口时崩溃。
        self.setTouchScrollSuppressed(self._editingCards)
        if not self._editingCards:
            self._saveCardOrder()

    def _startCardDrag(self, card, globalPosition):
        self._dragTarget = None
        self._dragCard = card
        self._dragPosition = QPoint(globalPosition)
        self._dragOffset = globalPosition - card.mapToGlobal(QPoint())
        self.dragPreview.setPixmap(card.grab())
        self.dragPreview.resize(card.size())
        self._moveDragPreview(globalPosition)
        self.dragPreview.show()
        self.dragPreview.raise_()
        effect = QGraphicsOpacityEffect(card)
        effect.setOpacity(0.2)
        card.setGraphicsEffect(effect)
        self._dragScrollTimer.start()

    def _moveDragPreview(self, globalPosition):
        self.dragPreview.move(
            self.viewport().mapFromGlobal(globalPosition - self._dragOffset)
        )

    def _moveCard(self, card, globalPosition):
        self._dragCard = card
        self._dragPosition = QPoint(globalPosition)
        self._moveDragPreview(globalPosition)
        self._reorderCardAt(card, globalPosition)

    def _reorderCardAt(self, card, globalPosition):
        position = self.cardsWidget.mapFromGlobal(globalPosition)
        hitMargin = 32
        target = min(
            (
                other
                for other in (self.allCards[name] for name in self._cardOrder)
                if other is not card
                and other.geometry()
                .adjusted(-hitMargin, -hitMargin, hitMargin, hitMargin)
                .contains(position)
            ),
            key=lambda other: (
                other.geometry().center() - position
            ).manhattanLength(),
            default=None,
        )
        if target is None:
            self._dragTarget = None
            return
        if target is self._dragTarget:
            return
        self._dragTarget = target

        cardName = next(
            name for name, value in self.allCards.items() if value is card
        )
        targetName = next(
            name for name, value in self.allCards.items() if value is target
        )
        fromIndex = self._cardOrder.index(cardName)
        toIndex = self._cardOrder.index(targetName)
        self._cardOrder.pop(fromIndex)
        self._cardOrder.insert(toIndex, cardName)
        # FlowLayout 的公开插入接口会二次移除同布局控件，需同步移动现有动画项。
        item = self.flowLayout._items.pop(fromIndex)
        animation = self.flowLayout._anis.pop(fromIndex)
        self.flowLayout._items.insert(toIndex, item)
        self.flowLayout._anis.insert(toIndex, animation)
        self.flowLayout.setGeometry(self.flowLayout.geometry())

    def _autoScrollCardDrag(self):
        if self._dragCard is None:
            return
        position = self.viewport().mapFromGlobal(self._dragPosition)
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
            self._moveDragPreview(self._dragPosition)
            self._reorderCardAt(self._dragCard, self._dragPosition)

    def _finishCardDrag(self, card):
        self._dragScrollTimer.stop()
        self._dragCard = None
        self.dragPreview.hide()
        card.setGraphicsEffect(None)
        self._saveCardOrder()
        self.homeCardsChanged.emit(self.homeCardEntries())

    def _saveCardOrder(self):
        if cfg.homeCardOrder.value != self._cardOrder:
            cfg.set(cfg.homeCardOrder, list(self._cardOrder))

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
