from __future__ import annotations

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    FluentStyleSheet,
    SettingCard,
    StrongBodyLabel,
    TransparentToolButton,
    isDarkTheme,
)
from qfluentwidgets.components.settings.expand_setting_card import (
    ExpandBorderWidget,
    GroupSeparator,
    HeaderSettingCard,
)

from app.config.cfg import cfg

QWIDGETSIZE_MAX = (1 << 24) - 1


class LabelElideFilter(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Paint or not isinstance(obj, QLabel):
            return False

        metrics = obj.fontMetrics()
        rect = obj.contentsRect()
        text = "\n".join(
            metrics.elidedText(line, Qt.TextElideMode.ElideRight, rect.width())
            for line in obj.text().splitlines() or [""]
        )
        with QPainter(obj) as painter:
            painter.setFont(obj.font())
            painter.setPen(obj.palette().color(obj.foregroundRole()))
            painter.drawText(rect, obj.alignment(), text)
        return True


class CardPaintFilter(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        return event.type() == QEvent.Type.Paint


class CollapsibleSettingCard(QWidget):
    def __init__(self, icon, title: str, content: str | None = None, parent=None):
        super().__init__(parent)
        self.isExpand = False

        self._initCardWidget(icon, title, content)
        self._initCardLayout()
        self._bindCard()

    def _initCardWidget(self, icon, title: str, content: str | None) -> None:
        self.card = HeaderSettingCard(icon, title, content, self)
        self.view = QWidget(self)
        self.borderWidget = ExpandBorderWidget(self)
        self.expandAnimation = QPropertyAnimation(
            self.view, QByteArray(b"maximumHeight"), self
        )
        self.vBoxLayout = QVBoxLayout(self)
        self.viewLayout = QVBoxLayout(self.view)

        self.expandAnimation.setDuration(200)
        self.expandAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.view.setMaximumHeight(0)
        self.view.setObjectName("view")

        FluentStyleSheet.EXPAND_SETTING_CARD.apply(self.card)
        FluentStyleSheet.EXPAND_SETTING_CARD.apply(self)

    def _initCardLayout(self) -> None:
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.card)
        self.vBoxLayout.addWidget(self.view)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(0)

    def _bindCard(self) -> None:
        self.card.expandButton.clicked.connect(self._onExpandClicked)
        self.expandAnimation.finished.connect(self._onExpandFinished)

    def addWidget(self, widget: QWidget) -> None:
        self.card.addWidget(widget)

    def addGroupWidget(self, widget: QWidget) -> None:
        if self.viewLayout.count() >= 1:
            self.viewLayout.addWidget(GroupSeparator(self.view))
        widget.setParent(self.view)
        self.viewLayout.addWidget(widget)

    def setExpand(self, isExpand: bool) -> None:
        if self.isExpand == isExpand:
            return
        self.isExpand = isExpand
        self.setProperty("isExpand", isExpand)
        self.setStyle(QApplication.style())
        self.card.expandButton.setExpand(isExpand)
        self.expandAnimation.stop()
        self.expandAnimation.setStartValue(self.view.height())
        self.expandAnimation.setEndValue(
            0 if not isExpand else self.view.sizeHint().height()
        )
        self.expandAnimation.start()

    def _onExpandClicked(self) -> None:
        self.setExpand(not self.isExpand)

    def _onExpandFinished(self) -> None:
        if self.isExpand:
            self.view.setMaximumHeight(QWIDGETSIZE_MAX)


class CollapsibleSettingCardGroup(CardWidget):
    orderChanged = Signal()

    def __init__(self, title: str, key: str, parent=None):
        super().__init__(parent)
        self.setObjectName(key)

        self.titleLabel = StrongBodyLabel(title, self)
        self.moveUpButton = TransparentToolButton(FluentIcon.UP, self)
        self.moveDownButton = TransparentToolButton(FluentIcon.DOWN, self)
        self.expandButton = TransparentToolButton(FluentIcon.CHEVRON_DOWN_MED, self)
        self.cardContainer = QWidget(self)
        self.cardPaintFilter = CardPaintFilter(self)
        self.labelElideFilter = LabelElideFilter(self)
        self.collapseAnimation = QPropertyAnimation(
            self.cardContainer, QByteArray(b"maximumHeight"), self
        )

        self.headerLayout = QHBoxLayout()
        self.cardLayout = QVBoxLayout(self.cardContainer)
        self.vBoxLayout = QVBoxLayout(self)

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        for button in (self.moveUpButton, self.moveDownButton, self.expandButton):
            button.setFixedSize(26, 26)
            button.setIconSize(QSize(12, 12))
        self.moveUpButton.hide()
        self.moveDownButton.hide()
        self.titleLabel.setFixedHeight(26)

        self.collapseAnimation.setDuration(200)
        self.collapseAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        FluentStyleSheet.SETTING_CARD_GROUP.apply(self)

        self.isCollapsed = self.objectName() not in cfg.expandedSettingGroups.value
        self.cardContainer.setMaximumHeight(0 if self.isCollapsed else QWIDGETSIZE_MAX)
        self._refreshExpandIcon()

    def _initLayout(self) -> None:
        self.headerLayout.setContentsMargins(16, 4, 8, 4)
        self.headerLayout.setSpacing(4)
        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.moveUpButton)
        self.headerLayout.addWidget(self.moveDownButton)
        self.headerLayout.addWidget(self.expandButton)

        self.cardLayout.setContentsMargins(0, 0, 0, 0)
        self.cardLayout.setSpacing(0)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.vBoxLayout.addLayout(self.headerLayout)
        self.vBoxLayout.addWidget(self.cardContainer)

    def _bind(self) -> None:
        self.expandButton.clicked.connect(self._onExpandClicked)
        self.moveUpButton.clicked.connect(lambda: self._reorder(-1))
        self.moveDownButton.clicked.connect(lambda: self._reorder(1))
        self.collapseAnimation.finished.connect(self._onCollapseFinished)

    def addSettingCard(self, card: QWidget) -> None:
        self.cardLayout.addWidget(card)
        targets = [card]
        if isinstance(card, CollapsibleSettingCard):
            targets += card.findChildren(SettingCard)
            targets += card.findChildren(ExpandBorderWidget)
            targets += card.findChildren(GroupSeparator)
        for widget in targets:
            widget.installEventFilter(self.cardPaintFilter)
            if isinstance(widget, SettingCard):
                for label in (widget.titleLabel, widget.contentLabel):
                    label.setWordWrap(False)
                    label.setSizePolicy(
                        QSizePolicy.Policy.Ignored,
                        QSizePolicy.Policy.Preferred,
                    )
                    widget.vBoxLayout.setAlignment(label, Qt.AlignmentFlag.AlignVCenter)
                    label.installEventFilter(self.labelElideFilter)
                widget.hBoxLayout.setStretchFactor(widget.vBoxLayout, 1 << 16)

    def addSettingCards(self, cards: list[QWidget]) -> None:
        for card in cards:
            self.addSettingCard(card)

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() < self.cardContainer.geometry().top()
        ):
            self._onExpandClicked()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.moveUpButton.show()
        self.moveDownButton.show()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.moveUpButton.hide()
        self.moveDownButton.hide()

    def _normalBackgroundColor(self):
        return QColor(255, 255, 255, 13 if isDarkTheme() else 170)

    def _onExpandClicked(self) -> None:
        self._setCollapsed(not self.isCollapsed)
        key = self.objectName()
        expandedGroups = list(cfg.expandedSettingGroups.value)
        if not self.isCollapsed and key not in expandedGroups:
            expandedGroups.append(key)
        elif self.isCollapsed and key in expandedGroups:
            expandedGroups.remove(key)
        cfg.set(cfg.expandedSettingGroups, expandedGroups)

    def _setCollapsed(self, isCollapsed: bool) -> None:
        self.isCollapsed = isCollapsed
        self._refreshExpandIcon()
        self.collapseAnimation.stop()
        self.collapseAnimation.setStartValue(self.cardContainer.height())
        self.collapseAnimation.setEndValue(
            0 if isCollapsed else self.cardContainer.sizeHint().height()
        )
        self.collapseAnimation.start()

    def _refreshExpandIcon(self) -> None:
        icon = (
            FluentIcon.CHEVRON_RIGHT_MED
            if self.isCollapsed
            else FluentIcon.CHEVRON_DOWN_MED
        )
        self.expandButton.setIcon(icon)

    def _onCollapseFinished(self) -> None:
        if not self.isCollapsed:
            self.cardContainer.setMaximumHeight(QWIDGETSIZE_MAX)

    def _reorder(self, offset: int) -> None:
        groups = self._siblings()
        target = groups[groups.index(self) + offset]
        layout = self.parentWidget().layout()
        layout.insertWidget(layout.indexOf(target), self)
        self._saveOrder()
        for group in self._siblings():
            group.updateArrows()
        self.orderChanged.emit()

    def _siblings(self) -> list[CollapsibleSettingCardGroup]:
        layout = self.parentWidget().layout()
        return [
            layout.itemAt(index).widget()
            for index in range(layout.count())
            if isinstance(
                layout.itemAt(index).widget(),
                CollapsibleSettingCardGroup,
            )
        ]

    def updateArrows(self) -> None:
        groups = self._siblings()
        index = groups.index(self)
        self.moveUpButton.setEnabled(index > 0)
        self.moveDownButton.setEnabled(index < len(groups) - 1)

    def _saveOrder(self) -> None:
        keys = [group.objectName() for group in self._siblings()]
        staleKeys = [key for key in cfg.settingGroupOrder.value if key not in keys]
        cfg.set(cfg.settingGroupOrder, keys + staleKeys)
