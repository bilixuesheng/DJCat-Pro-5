from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    Property,
    QPropertyAnimation,
    QRectF,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QGraphicsOpacityEffect,
    QScroller,
    QSizePolicy,
)
from qfluentwidgets import (
    ExpandSettingCard,
    SettingCard,
    TimePicker,
    isDarkTheme,
)
from qfluentwidgets import FluentIcon as FIF


def _set_reveal_painting(widget, enabled):
    if enabled:
        if widget.graphicsEffect() is not None:
            widget.setGraphicsEffect(None)
    elif widget.graphicsEffect() is None:
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(0)
        widget.setGraphicsEffect(effect)


class TouchTimePicker(TimePicker):
    """Time picker whose popup columns support touch scrolling."""

    def _showPanel(self):
        super()._showPanel()
        views = self.findChildren(QAbstractItemView)
        if not views:
            return

        panel = views[0].window()
        panel.itemMaskWidget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        panel.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        for view in views:
            viewport = view.viewport()
            # Let Qt synthesize mouse drags so both inputs share one scroller.
            viewport.setAttribute(
                Qt.WidgetAttribute.WA_AcceptTouchEvents,
                False,
            )
            QScroller.grabGesture(
                viewport,
                QScroller.ScrollerGestureType.LeftMouseButtonGesture,
            )
            QScroller.scroller(viewport).stateChanged.connect(
                lambda state, column=view: self._settleColumn(
                    column,
                    state,
                )
            )

    @staticmethod
    def _settleColumn(column, state):
        if state == QScroller.State.Dragging:
            column.vScrollBar.ani.stop()
            column.vScrollBar.resetValue(column.verticalScrollBar().value())
            return
        if state != QScroller.State.Inactive:
            return
        item = column.itemAt(column.viewport().rect().center())
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        column.setCurrentIndex(column.row(item))
        column.scrollToItem(column.currentItem())


class TaskFormSettingCard(SettingCard):
    def __init__(self, icon, title, content, widget, parent=None):
        super().__init__(icon, title, content, parent)
        for label in (self.titleLabel, self.contentLabel):
            label.setWordWrap(False)
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
        self.hBoxLayout.setStretchFactor(self.vBoxLayout, 1)
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(
            QColor(0, 0, 0, 50)
            if isDarkTheme()
            else QColor(0, 0, 0, 19)
        )
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class TaskExpandSettingCard(ExpandSettingCard):
    """Expand a task by revealing its body below a stationary header."""

    def __init__(self, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self._revealHeight = 0
        self.revealAnimation = QPropertyAnimation(
            self,
            b"revealHeight",
            self,
        )
        self.revealAnimation.setDuration(200)
        self.revealAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(0)
        _set_reveal_painting(self.view, False)
        self.verticalScrollBar().setValue(0)

    def getRevealHeight(self):
        return self._revealHeight

    def setRevealHeight(self, height):
        self._revealHeight = max(0, int(height))
        self.verticalScrollBar().setValue(0)
        height = self.card.height() + self._revealHeight
        self.setFixedHeight(height)
        parent = self.parentWidget()
        if parent is not None and getattr(parent, "expandCard", None) is self:
            parent.setFixedHeight(height)
        _set_reveal_painting(self.view, self._revealHeight > 0)

    revealHeight = Property(int, getRevealHeight, setRevealHeight)

    def setExpand(self, isExpand: bool):
        if self.isExpand == isExpand:
            return

        self._adjustViewSize()
        self.isExpand = isExpand
        self.setProperty("isExpand", isExpand)
        self.setStyle(QApplication.style())

        self.revealAnimation.stop()
        self.revealAnimation.setStartValue(self._revealHeight)
        self.revealAnimation.setEndValue(
            self.viewLayout.sizeHint().height() if isExpand else 0
        )
        self.revealAnimation.start()
        self.card.expandButton.setExpand(isExpand)

    def _adjustViewSize(self):
        height = self.viewLayout.sizeHint().height()
        self.spaceWidget.setFixedHeight(0)
        if (
            self.isExpand
            and self.revealAnimation.state()
            != QPropertyAnimation.State.Running
        ):
            self.setRevealHeight(height)


class TaskExpandCardBehavior(QObject):
    def __init__(self, expandCard):
        super().__init__(expandCard)
        self.expandCard = expandCard
        self._pressPosition = None
        self._dragged = False

        expandCard.card.installEventFilter(self)
        expandCard.card.expandButton.installEventFilter(self)
        expandCard.borderWidget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.expandCard.card:
            return self._filterHeader(event)
        if obj is self.expandCard.card.expandButton:
            return self._filterArrow(obj, event)
        if (
            obj is self.expandCard.borderWidget
            and event.type() == QEvent.Type.Paint
        ):
            self._paintSeparator(obj)
            return True
        return False

    def _filterHeader(self, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            self._pressPosition = event.globalPosition().toPoint()
            self._dragged = False
            self._setMaterialPressed(True)
            return True

        if self._pressPosition is None:
            return False

        if event.type() == QEvent.Type.MouseMove:
            distance = (
                event.globalPosition().toPoint() - self._pressPosition
            ).manhattanLength()
            self._dragged = (
                self._dragged
                or distance >= QApplication.startDragDistance()
                or not self.expandCard.card.rect().contains(
                    event.position().toPoint()
                )
            )
            self._setMaterialPressed(not self._dragged)
            return True

        if event.type() != QEvent.Type.MouseButtonRelease:
            return False

        shouldExpand = (
            event.button() == Qt.MouseButton.LeftButton
            and not self._dragged
            and self.expandCard.card.rect().contains(
                event.position().toPoint()
            )
        )
        self._pressPosition = None
        self._dragged = False
        self._setMaterialPressed(False)
        if shouldExpand:
            self.expandCard.card.expandButton.click()
        return True

    def _filterArrow(self, button, event):
        if event.type() == QEvent.Type.Paint:
            self._paintArrow(button)
            return True
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._setMaterialPressed(True)
        elif event.type() == QEvent.Type.MouseMove and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            self._setMaterialPressed(
                button.rect().contains(event.position().toPoint())
            )
        elif event.type() in (
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.Leave,
        ):
            self._setMaterialPressed(False)
        return False

    def _setMaterialPressed(self, pressed):
        card = self.expandCard.parentWidget()
        if card is None or not hasattr(card, "_updateBackgroundColor"):
            return
        card.isPressed = pressed
        card._updateBackgroundColor()

    @staticmethod
    def _paintArrow(button):
        painter = QPainter(button)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        if not button.isEnabled():
            painter.setOpacity(0.36)
        elif button.isDown():
            painter.setOpacity(0.63)
        painter.translate(button.width() // 2, button.height() // 2)
        painter.rotate(button.angle)
        FIF.ARROW_DOWN.render(painter, QRectF(-5, -5, 9.6, 9.6))

    def _paintSeparator(self, widget):
        if widget.height() <= self.expandCard.card.height():
            return
        painter = QPainter(widget)
        painter.setPen(
            QColor(0, 0, 0, 50)
            if isDarkTheme()
            else QColor(0, 0, 0, 19)
        )
        y = self.expandCard.card.height()
        painter.drawLine(1, y, widget.width() - 1, y)


def configure_task_expand_card(expandCard):
    return TaskExpandCardBehavior(expandCard)
