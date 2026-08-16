from __future__ import annotations

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QPainter, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FluentIcon,
    FluentStyleSheet,
    IconWidget,
    SettingCard,
    StrongBodyLabel,
    isDarkTheme,
)
from qfluentwidgets.components.settings.expand_setting_card import (
    ExpandBorderWidget,
    GroupSeparator,
    HeaderSettingCard,
)

from app.config.cfg import cfg

QWIDGETSIZE_MAX = (1 << 24) - 1


def _set_reveal_painting(widget: QWidget, enabled: bool) -> None:
    if enabled:
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
    elif widget.graphicsEffect() is None:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0)
        widget.setGraphicsEffect(effect)


class LabelElideFilter(QObject):
    def __init__(self, parent=None, maximumLines=None):
        super().__init__(parent)
        self.maximumLines = maximumLines

    def displayLines(self, label: QLabel) -> list[str]:
        metrics = label.fontMetrics()
        width = label.contentsRect().width()
        if self.maximumLines is None:
            return [
                metrics.elidedText(line, Qt.TextElideMode.ElideRight, width)
                for line in label.text().splitlines() or [""]
            ]
        if self.maximumLines == 1:
            return [
                metrics.elidedText(
                    " ".join(label.text().split()),
                    Qt.TextElideMode.ElideRight,
                    width,
                )
            ]

        text = " ".join(label.text().split())
        layout = QTextLayout(text, label.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        lines = []
        layout.beginLayout()
        for index in range(self.maximumLines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            start = line.textStart()
            end = start + line.textLength()
            value = text[start:end].rstrip()
            if index == self.maximumLines - 1 and end < len(text):
                value = metrics.elidedText(
                    text[start:],
                    Qt.TextElideMode.ElideRight,
                    width,
                )
            lines.append(value)
        layout.endLayout()
        return lines

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.Paint or not isinstance(obj, QLabel):
            return False

        rect = obj.contentsRect()
        lines = self.displayLines(obj)
        lineHeight = obj.fontMetrics().lineSpacing()
        top = rect.top() + max(0, (rect.height() - len(lines) * lineHeight) // 2)
        with QPainter(obj) as painter:
            painter.setFont(obj.font())
            painter.setPen(obj.palette().color(obj.foregroundRole()))
            for index, line in enumerate(lines):
                lineRect = QRect(
                    rect.left(),
                    top + index * lineHeight,
                    rect.width(),
                    lineHeight,
                )
                painter.drawText(
                    lineRect,
                    obj.alignment(),
                    line,
                )
        return True


class CardPaintFilter(QObject):
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        return event.type() == QEvent.Type.Paint


class SettingMaterialCard(CardWidget):
    """Card using the same translucent material as setting groups."""

    def _normalBackgroundColor(self):
        return QColor(255, 255, 255, 13 if isDarkTheme() else 170)

    def applyExpandCardMaterial(self, expandCard):
        """Let this card's material show through an ``ExpandSettingCard``."""
        paintFilter = CardPaintFilter(self)
        expandCard.card.installEventFilter(paintFilter)
        expandCard.borderWidget.installEventFilter(paintFilter)

        surfaces = (
            expandCard,
            expandCard.viewport(),
            expandCard.scrollWidget,
            expandCard.view,
            expandCard.card,
        )
        for surface in surfaces:
            surface.setAutoFillBackground(False)
            surface.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        return paintFilter


class SettingExpandButton(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._angle = 0.0
        self.rotateAnimation = QPropertyAnimation(self, b"angle", self)
        self.rotateAnimation.setDuration(200)
        self.rotateAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        if not self.isEnabled():
            painter.setOpacity(0.36)
        elif self.isDown():
            painter.setOpacity(0.63)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self._angle)
        FluentIcon.CHEVRON_RIGHT_MED.render(
            painter,
            QRectF(-6, -6, 12, 12),
        )

    def setExpanded(self, expanded: bool, animated: bool = True) -> None:
        endAngle = 90.0 if expanded else 0.0
        self.rotateAnimation.stop()
        if not animated:
            self.setAngle(endAngle)
            return
        self.rotateAnimation.setStartValue(self._angle)
        self.rotateAnimation.setEndValue(endAngle)
        self.rotateAnimation.start()

    def getAngle(self) -> float:
        return self._angle

    def setAngle(self, angle: float) -> None:
        self._angle = angle
        self.update()

    angle = Property(float, getAngle, setAngle)


class CollapsibleSettingCard(QWidget):
    def __init__(self, icon, title: str, content: str | None = None, parent=None):
        super().__init__(parent)
        self.isExpand = False

        self._initCardWidget(icon, title, content)
        self._initCardLayout()
        self._bindCard()
        self._headerPressPosition = None
        self._headerPressCanceled = False
        self.card.installEventFilter(self)

    def _initCardWidget(self, icon, title: str, content: str | None) -> None:
        self.card = HeaderSettingCard(icon, title, content, self)
        self.view = QWidget(self)
        self.viewContent = QWidget(self.view)
        self.borderWidget = ExpandBorderWidget(self)
        self.expandAnimation = QPropertyAnimation(
            self.view, QByteArray(b"maximumHeight"), self
        )
        self.vBoxLayout = QVBoxLayout(self)
        self.revealLayout = QVBoxLayout(self.view)
        self.viewLayout = QVBoxLayout(self.viewContent)

        self.expandAnimation.setDuration(200)
        self.expandAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.view.setMaximumHeight(0)
        _set_reveal_painting(self.viewContent, False)
        self.setFixedHeight(self.card.height())
        self.view.setObjectName("view")

        FluentStyleSheet.EXPAND_SETTING_CARD.apply(self.card)
        FluentStyleSheet.EXPAND_SETTING_CARD.apply(self)

    def _initCardLayout(self) -> None:
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.card)
        self.vBoxLayout.addWidget(self.view)
        self.revealLayout.setContentsMargins(0, 0, 0, 0)
        self.revealLayout.setSpacing(0)
        self.revealLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.revealLayout.addWidget(self.viewContent)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(0)

    def _bindCard(self) -> None:
        self.card.expandButton.clicked.connect(self._onExpandClicked)
        self.expandAnimation.valueChanged.connect(self._onExpandValueChanged)
        self.expandAnimation.finished.connect(self._onExpandFinished)

    def addWidget(self, widget: QWidget) -> None:
        self.card.addWidget(widget)

    def addGroupWidget(self, widget: QWidget) -> None:
        if self.viewLayout.count() >= 1:
            self.viewLayout.addWidget(GroupSeparator(self.viewContent))
        widget.setParent(self.viewContent)
        self.viewLayout.addWidget(widget)
        self._contentHeight()

    def _contentHeight(self) -> int:
        self.viewLayout.invalidate()
        self.viewLayout.activate()
        height = self.viewLayout.sizeHint().height()
        self.viewContent.setFixedHeight(height)
        return height

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
            0 if not isExpand else self._contentHeight()
        )
        self.expandAnimation.start()

    def setExpandedImmediately(self, isExpand: bool) -> None:
        self.expandAnimation.stop()
        self.isExpand = isExpand
        self.setProperty("isExpand", isExpand)
        self.setStyle(QApplication.style())
        self.card.expandButton.setExpand(isExpand)
        height = self._contentHeight() if isExpand else 0
        self.view.setMaximumHeight(QWIDGETSIZE_MAX if isExpand else 0)
        self._onExpandValueChanged(height)

    def _onExpandValueChanged(self, height) -> None:
        height = int(height)
        self.setFixedHeight(self.card.height() + height)
        _set_reveal_painting(self.viewContent, height > 0)

    def _onExpandClicked(self) -> None:
        self.setExpand(not self.isExpand)

    def _onExpandFinished(self) -> None:
        if self.isExpand:
            self.view.setMaximumHeight(QWIDGETSIZE_MAX)
            self._onExpandValueChanged(self._contentHeight())

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is not self.card:
            return super().eventFilter(obj, event)

        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._headerPressPosition = event.globalPosition().toPoint()
            self._headerPressCanceled = False
            self.card.expandButton.setPressed(True)
            return True

        if self._headerPressPosition is None:
            return super().eventFilter(obj, event)

        if event.type() == QEvent.Type.MouseMove:
            distance = (
                event.globalPosition().toPoint() - self._headerPressPosition
            ).manhattanLength()
            self._headerPressCanceled = (
                self._headerPressCanceled
                or distance >= QApplication.startDragDistance()
                or not self.card.rect().contains(event.position().toPoint())
            )
            self.card.expandButton.setPressed(not self._headerPressCanceled)
            return True

        if event.type() == QEvent.Type.Leave:
            self._headerPressCanceled = True
            self.card.expandButton.setPressed(False)
            return super().eventFilter(obj, event)

        if event.type() != QEvent.Type.MouseButtonRelease:
            return super().eventFilter(obj, event)

        shouldToggle = (
            event.button() == Qt.MouseButton.LeftButton
            and not self._headerPressCanceled
            and self.card.rect().contains(event.position().toPoint())
        )
        self._headerPressPosition = None
        self._headerPressCanceled = False
        self.card.expandButton.setPressed(False)
        if shouldToggle:
            self.card.expandButton.click()
        return True


class CollapsibleSettingCardGroup(SettingMaterialCard):
    def __init__(
        self,
        title: str,
        key: str,
        parent=None,
        icon=None,
        content: str = "",
    ):
        super().__init__(parent)
        self.setObjectName(key)

        self.iconWidget = IconWidget(icon, self) if icon is not None else None
        self.titleLabel = StrongBodyLabel(title, self)
        self.contentLabel = CaptionLabel(content, self)
        self.expandButton = SettingExpandButton(self)
        self.cardContainer = QWidget(self)
        self.cardView = QWidget(self.cardContainer)
        self.cardPaintFilter = CardPaintFilter(self)
        self.labelElideFilter = LabelElideFilter(self)
        self.collapseAnimation = QPropertyAnimation(
            self.cardContainer, QByteArray(b"maximumHeight"), self
        )

        self.headerWidget = QWidget(self)
        self.headerLayout = QHBoxLayout(self.headerWidget)
        self.titleLayout = QVBoxLayout()
        self.revealLayout = QVBoxLayout(self.cardContainer)
        self.cardLayout = QVBoxLayout(self.cardView)
        self.vBoxLayout = QVBoxLayout(self)
        self.separator = GroupSeparator(self.cardView)
        self._settingCards = []
        self._itemSeparators = []
        self._headerPressPosition = None
        self._headerPressCanceled = False
        self._searchActive = False
        self._searchCollapsed = False

        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.expandButton.setFixedSize(26, 26)
        if self.iconWidget is not None:
            self.iconWidget.setFixedSize(24, 24)
        self.headerWidget.setFixedHeight(70)
        self.titleLabel.setFixedHeight(22)
        self.contentLabel.setFixedHeight(18)

        self.collapseAnimation.setDuration(200)
        self.collapseAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        FluentStyleSheet.SETTING_CARD_GROUP.apply(self)

        self.isCollapsed = self.objectName() not in cfg.expandedSettingGroups.value
        self.cardContainer.setMaximumHeight(0 if self.isCollapsed else QWIDGETSIZE_MAX)
        _set_reveal_painting(self.cardView, not self.isCollapsed)
        self._refreshExpandIcon()

    def _initLayout(self) -> None:
        self.headerLayout.setContentsMargins(16, 15, 8, 15)
        self.headerLayout.setSpacing(12)
        if self.iconWidget is not None:
            self.headerLayout.addWidget(self.iconWidget)
        self.titleLayout.setContentsMargins(0, 0, 0, 0)
        self.titleLayout.setSpacing(0)
        self.titleLayout.addWidget(self.titleLabel)
        self.titleLayout.addWidget(self.contentLabel)
        self.headerLayout.addLayout(self.titleLayout)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.expandButton)

        self.cardLayout.setContentsMargins(0, 0, 0, 0)
        self.cardLayout.setSpacing(0)
        self.cardLayout.addWidget(self.separator)
        self.revealLayout.setContentsMargins(0, 0, 0, 0)
        self.revealLayout.setSpacing(0)
        self.revealLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.revealLayout.addWidget(self.cardView)

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.vBoxLayout.addWidget(self.headerWidget)
        self.vBoxLayout.addWidget(self.cardContainer)
        self.setFixedHeight(self.headerWidget.height())

    def _bind(self) -> None:
        self.expandButton.clicked.connect(self._onExpandClicked)
        self.collapseAnimation.finished.connect(self._onCollapseFinished)
        self.collapseAnimation.valueChanged.connect(self._onCollapseValueChanged)

    def addSettingCard(self, card: QWidget) -> None:
        separator = None
        if self._settingCards:
            separator = GroupSeparator(self.cardView)
            self.cardLayout.addWidget(separator)
        self.cardLayout.addWidget(card)
        self._settingCards.append(card)
        self._itemSeparators.append(separator)
        targets = [card]
        if isinstance(card, CollapsibleSettingCard):
            targets += card.findChildren(SettingCard)
            targets += card.findChildren(ExpandBorderWidget)
            targets += card.findChildren(GroupSeparator)
            card.expandAnimation.valueChanged.connect(
                lambda _: self._contentHeight()
            )
            card.expandAnimation.finished.connect(self._contentHeight)
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
        self._contentHeight()

    def addSettingCards(self, cards: list[QWidget]) -> None:
        for card in cards:
            self.addSettingCard(card)

    def settingCards(self) -> tuple[QWidget, ...]:
        return tuple(self._settingCards)

    def setSettingCardVisible(self, card: QWidget, visible: bool) -> None:
        card.setVisible(visible)
        hasVisibleCard = False
        for settingCard, separator in zip(
            self._settingCards,
            self._itemSeparators,
        ):
            isVisible = not settingCard.isHidden()
            if separator is not None:
                separator.setVisible(isVisible and hasVisibleCard)
            hasVisibleCard |= isVisible
        self._contentHeight()

    def _contentHeight(self) -> int:
        self.cardLayout.invalidate()
        self.cardLayout.activate()
        height = self.cardLayout.sizeHint().height()
        self.cardView.setFixedHeight(height)
        if (
            not self._isVisuallyCollapsed()
            and self.collapseAnimation.state()
            == QPropertyAnimation.State.Stopped
        ):
            self.setFixedHeight(self.headerWidget.height() + height)
        return height

    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() < self.cardContainer.geometry().top()
        ):
            self._headerPressPosition = event.globalPosition().toPoint()
            self._headerPressCanceled = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._headerPressPosition is not None:
            distance = (
                event.globalPosition().toPoint() - self._headerPressPosition
            ).manhattanLength()
            if (
                distance >= QApplication.startDragDistance()
                or not self.rect().contains(event.position().toPoint())
                or event.position().y() >= self.cardContainer.geometry().top()
            ):
                self._headerPressCanceled = True
                self.isPressed = False
                self._updateBackgroundColor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        shouldToggle = (
            event.button() == Qt.MouseButton.LeftButton
            and self._headerPressPosition is not None
            and not self._headerPressCanceled
            and self.rect().contains(event.position().toPoint())
            and event.position().y() < self.cardContainer.geometry().top()
        )
        self._headerPressPosition = None
        self._headerPressCanceled = False
        super().mouseReleaseEvent(event)
        if shouldToggle:
            self._onExpandClicked()

    def leaveEvent(self, event) -> None:
        if self._headerPressPosition is not None:
            self._headerPressCanceled = True
            self.isPressed = False
            self._updateBackgroundColor()
        super().leaveEvent(event)

    def _onExpandClicked(self) -> None:
        if self._searchActive:
            self._searchCollapsed = not self._searchCollapsed
            self._animateCollapsed(self._searchCollapsed)
            return
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
        self._animateCollapsed(self._isVisuallyCollapsed())

    def _animateCollapsed(self, isCollapsed: bool) -> None:
        self._refreshExpandIcon(animated=True)
        self.collapseAnimation.stop()
        self.collapseAnimation.setStartValue(self.cardContainer.height())
        self.collapseAnimation.setEndValue(
            0 if isCollapsed else self._contentHeight()
        )
        self.collapseAnimation.start()

    def setSearchExpanded(self, expanded: bool) -> None:
        if expanded and not self._searchActive:
            self._searchCollapsed = False
        self._searchActive = expanded
        if not expanded:
            self._searchCollapsed = False
        self.collapseAnimation.stop()
        isCollapsed = self._isVisuallyCollapsed()
        self.cardContainer.setMaximumHeight(0 if isCollapsed else QWIDGETSIZE_MAX)
        self._onCollapseValueChanged(0 if isCollapsed else self._contentHeight())
        self._refreshExpandIcon()

    def _isVisuallyCollapsed(self) -> bool:
        return self._searchCollapsed if self._searchActive else self.isCollapsed

    def _refreshExpandIcon(self, animated: bool = False) -> None:
        self.expandButton.setExpanded(
            not self._isVisuallyCollapsed(),
            animated,
        )

    def _onCollapseFinished(self) -> None:
        if not self._isVisuallyCollapsed():
            self.cardContainer.setMaximumHeight(QWIDGETSIZE_MAX)
            self._onCollapseValueChanged(self._contentHeight())
        else:
            self._onCollapseValueChanged(0)

    def _onCollapseValueChanged(self, height) -> None:
        height = max(0, int(height))
        self.setFixedHeight(self.headerWidget.height() + height)
        _set_reveal_painting(self.cardView, height > 0)
