from PySide6.QtCore import QEvent, QObject, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QAbstractItemView, QScroller
from qfluentwidgets import TimePicker, isDarkTheme
from qfluentwidgets import FluentIcon as FIF


class TouchTimePicker(TimePicker):
    """Time picker whose popup columns support touch scrolling."""

    def _showPanel(self):
        super()._showPanel()
        for view in self.findChildren(QAbstractItemView):
            viewport = view.viewport()
            if QScroller.hasScroller(viewport):
                continue
            QScroller.grabGesture(
                viewport,
                QScroller.ScrollerGestureType.TouchGesture,
            )
            QScroller.scroller(viewport).stateChanged.connect(
                lambda state, column=view: self._settleColumn(
                    column,
                    state,
                )
            )
            view.window().setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

    @staticmethod
    def _settleColumn(column, state):
        if state != QScroller.State.Inactive:
            return
        item = column.itemAt(column.viewport().rect().center())
        if item is None or not item.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        column.setCurrentIndex(column.row(item))
        column.scrollToItem(item)


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
        if (
            obj is self.expandCard.card.expandButton
            and event.type() == QEvent.Type.Paint
        ):
            self._paintArrow(obj)
            return True
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
            )
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
        if shouldExpand:
            self.expandCard.card.expandButton.click()
        return True

    @staticmethod
    def _paintArrow(button):
        painter = QPainter(button)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        if not button.isEnabled():
            painter.setOpacity(0.36)
        painter.translate(button.width() // 2, button.height() // 2)
        painter.rotate(button.angle)
        FIF.ARROW_DOWN.render(painter, QRectF(-5, -5, 9.6, 9.6))

    def _paintSeparator(self, widget):
        if not self.expandCard.isExpand:
            return
        painter = QPainter(widget)
        painter.setPen(
            QColor(255, 255, 255, 24)
            if isDarkTheme()
            else QColor(0, 0, 0, 19)
        )
        y = self.expandCard.card.height()
        painter.drawLine(1, y, widget.width() - 1, y)


def configure_task_expand_card(expandCard):
    return TaskExpandCardBehavior(expandCard)
