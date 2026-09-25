from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget
from qfluentwidgets import FluentIconBase, Theme, ToolTip, isDarkTheme, themeColor
from qfluentwidgets.common.screen import getCurrentScreenGeometry
from qfluentwidgets.common.style_sheet import ThemeColor

from app.view.components.scroll_area import registerTouchPressTarget

# 与 QFluentWidgets ToggleToolButton + FlowLayout(isTight=True) 的原排布一致。
CELL_SIZE = QSize(38, 32)
CELL_SPACING = 10
GRID_MARGIN = 8
ICON_SIZE = 16
CORNER_RADIUS = 5
TOOLTIP_DELAY_MS = 300


@dataclass
class IconGridItem:
    key: str
    icon: FluentIconBase | QIcon
    toolTip: str


class IconGrid(QWidget):
    """A grid of toggle icons painted by one widget.

    The icon library has 175 entries. As separate ToggleToolButtons each one
    needed its own style sheet polish, tooltip filter and layout item; opening
    the picker spent about half a second building them. One widget paints only
    the cells inside the exposed rectangle and keeps the Fluent button look.
    """

    iconClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[IconGridItem] = []
        self._visible: list[int] = []
        self._checked: int | None = None
        self._hover: int | None = None
        self._pressed: int | None = None
        self._toolTip = None
        self._toolTipIndex = None
        self._toolTipTimer = QTimer(self)
        self._backgrounds = {}
        self._icons = {}

        self._initWidget()

    def _initWidget(self) -> None:
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._toolTipTimer.setSingleShot(True)
        self._toolTipTimer.setInterval(TOOLTIP_DELAY_MS)
        self._toolTipTimer.timeout.connect(self._showToolTip)
        registerTouchPressTarget(self)

    def setItems(self, items: list[IconGridItem]) -> None:
        self._items = list(items)
        self._icons.clear()
        self._visible = list(range(len(self._items)))
        self._checked = None
        self._resetPointerState()
        self.updateGeometry()
        self.update()

    def items(self) -> tuple[IconGridItem, ...]:
        return tuple(self._items)

    def count(self) -> int:
        return len(self._items)

    def visibleIndexes(self) -> tuple[int, ...]:
        return tuple(self._visible)

    def setFilterText(self, text: str) -> None:
        query = text.strip().lower()
        self._visible = [
            index
            for index, item in enumerate(self._items)
            if not query or query in item.toolTip.lower()
        ]
        self._resetPointerState()
        self.updateGeometry()
        self.update()

    def checkedIndex(self) -> int | None:
        return self._checked

    def setCheckedIndex(self, index: int | None) -> None:
        if index is not None and not 0 <= index < len(self._items):
            index = None
        if index == self._checked:
            return
        self._checked = index
        self.update()

    def indexOfKey(self, key: str) -> int | None:
        return next(
            (index for index, item in enumerate(self._items) if item.key == key),
            None,
        )

    def cellRect(self, index: int) -> QRect:
        """Geometry of an item, or an empty rect when it is filtered out."""
        try:
            position = self._visible.index(index)
        except ValueError:
            return QRect()
        columns = self._columns(self.width())
        row, column = divmod(position, columns)
        return QRect(
            GRID_MARGIN + column * (CELL_SIZE.width() + CELL_SPACING),
            GRID_MARGIN + row * (CELL_SIZE.height() + CELL_SPACING),
            CELL_SIZE.width(),
            CELL_SIZE.height(),
        )

    def indexAt(self, position: QPoint) -> int | None:
        columns = self._columns(self.width())
        x = position.x() - GRID_MARGIN
        y = position.y() - GRID_MARGIN
        if x < 0 or y < 0:
            return None
        column, cellX = divmod(x, CELL_SIZE.width() + CELL_SPACING)
        row, cellY = divmod(y, CELL_SIZE.height() + CELL_SPACING)
        if column >= columns or cellX >= CELL_SIZE.width() or cellY >= CELL_SIZE.height():
            return None
        position = row * columns + column
        return self._visible[position] if position < len(self._visible) else None

    @staticmethod
    def _columns(width: int) -> int:
        usable = width - 2 * GRID_MARGIN + CELL_SPACING
        return max(1, usable // (CELL_SIZE.width() + CELL_SPACING))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        if not self._visible:
            return 2 * GRID_MARGIN
        rows = math.ceil(len(self._visible) / self._columns(width))
        return (
            2 * GRID_MARGIN
            + rows * CELL_SIZE.height()
            + (rows - 1) * CELL_SPACING
        )

    def sizeHint(self) -> QSize:
        width = max(self.width(), CELL_SIZE.width() + 2 * GRID_MARGIN)
        return QSize(width, self.heightForWidth(width))

    def minimumSizeHint(self) -> QSize:
        return QSize(CELL_SIZE.width() + 2 * GRID_MARGIN, 2 * GRID_MARGIN)

    def paintEvent(self, event) -> None:
        exposed = event.rect()
        painter = QPainter(self)
        dark = isDarkTheme()
        ratio = self.devicePixelRatioF()
        for index in self._visible:
            rect = self.cellRect(index)
            if rect.intersects(exposed):
                self._paintCell(painter, index, rect, dark, ratio)

    def _paintCell(self, painter: QPainter, index: int, rect: QRect, dark: bool, ratio: float) -> None:
        # 背景只有几种状态、图标也不会变，都按设备像素缓存成位图，每格只剩两次贴图。
        checked = index == self._checked
        pressed = index == self._pressed and index == self._hover
        hover = index == self._hover
        painter.drawPixmap(
            rect.topLeft(),
            self._cellBackground(dark, checked, hover, pressed, ratio),
        )
        if pressed:
            painter.setOpacity(0.63)
        painter.drawPixmap(
            rect.x() + (rect.width() - ICON_SIZE) // 2,
            rect.y() + (rect.height() - ICON_SIZE) // 2,
            self._iconPixmap(index, dark, checked, ratio),
        )
        if pressed:
            painter.setOpacity(1.0)

    def _cellBackground(self, dark, checked, hover, pressed, ratio) -> QPixmap:
        key = (dark, checked, hover, pressed, ratio, themeColor().rgba())
        pixmap = self._backgrounds.get(key)
        if pixmap is not None:
            return pixmap
        if len(self._backgrounds) > 64:
            self._backgrounds.clear()
        background, border, accentBorder, accentBottom = _cellColors(
            dark, checked, hover, pressed
        )
        pixmap = QPixmap(
            round(CELL_SIZE.width() * ratio),
            round(CELL_SIZE.height() * ratio),
        )
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        frame = QRectF(0.5, 0.5, CELL_SIZE.width() - 1, CELL_SIZE.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(frame, CORNER_RADIUS, CORNER_RADIUS)
        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawPath(path)
        if accentBorder is not None:
            # QSS 的上下边框单独着色；只描直线段，圆角部分沿用侧边颜色。
            y = frame.bottom() if accentBottom else frame.top()
            painter.setPen(QPen(accentBorder, 1))
            painter.drawLine(
                QPointF(frame.left() + CORNER_RADIUS, y),
                QPointF(frame.right() - CORNER_RADIUS, y),
            )
        painter.end()
        self._backgrounds[key] = pixmap
        return pixmap

    def _iconPixmap(self, index, dark, checked, ratio) -> QPixmap:
        item = self._items[index]
        icon = item.icon
        # 选中项与 PrimaryToolButton 一样反转图标颜色。
        theme = (Theme.LIGHT if dark else Theme.DARK) if checked else Theme.AUTO
        key = (index, dark, theme, ratio)
        pixmap = self._icons.get(key)
        if pixmap is not None:
            return pixmap
        size = round(ICON_SIZE * ratio)
        pixmap = QPixmap(size, size)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        target = QRectF(0, 0, ICON_SIZE, ICON_SIZE)
        if isinstance(icon, FluentIconBase):
            icon.render(painter, target, theme=theme)
        else:
            icon.paint(painter, target.toRect(), Qt.AlignmentFlag.AlignCenter)
        painter.end()
        self._icons[key] = pixmap
        return pixmap

    def cancelTouchPress(self) -> None:
        if self._pressed is None:
            return
        self._pressed = None
        self.update()

    def _setHover(self, index: int | None) -> None:
        if index == self._hover:
            return
        previous = self._hover
        self._hover = index
        for changed in (previous, index):
            if changed is not None:
                self.update(self.cellRect(changed))
        self._hideToolTip()
        if index is not None:
            self._toolTipIndex = index
            self._toolTipTimer.start()

    def _resetPointerState(self) -> None:
        self._hover = None
        self._pressed = None
        self._hideToolTip()

    def mouseMoveEvent(self, event) -> None:
        self._setHover(self.indexAt(event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._hideToolTip()
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        index = self.indexAt(event.position().toPoint())
        self._pressed = index
        self._setHover(index)
        self._hideToolTip()
        if index is not None:
            self.update(self.cellRect(index))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        pressed = self._pressed
        self._pressed = None
        index = self.indexAt(event.position().toPoint())
        if pressed is not None:
            self.update(self.cellRect(pressed))
        if pressed is not None and pressed == index:
            self.iconClicked.emit(index)
        event.accept()

    def leaveEvent(self, event) -> None:
        self._setHover(None)
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:
        self._resetPointerState()
        super().hideEvent(event)

    def _showToolTip(self) -> None:
        index = self._toolTipIndex
        if index is None or index != self._hover or not self.isVisible():
            return
        if self._toolTip is None:
            self._toolTip = ToolTip("", self.window())
        self._toolTip.setText(self._items[index].toolTip)
        rect = self.cellRect(index)
        anchor = self.mapToGlobal(rect.topLeft())
        x = anchor.x() + rect.width() // 2 - self._toolTip.width() // 2
        y = anchor.y() - self._toolTip.height()
        screen = getCurrentScreenGeometry()
        x = max(screen.left(), min(x, screen.right() - self._toolTip.width() - 4))
        y = max(screen.top(), min(y, screen.bottom() - self._toolTip.height() - 4))
        self._toolTip.move(x, y)
        self._toolTip.show()

    def _hideToolTip(self) -> None:
        self._toolTipTimer.stop()
        if self._toolTip is not None:
            self._toolTip.hide()

    def toolTipText(self) -> str:
        """The text the tooltip shows for the hovered cell, for tests."""
        if self._toolTip is None or not self._toolTip.isVisible():
            return ""
        return self._toolTip.text()


def _alpha(red: int, green: int, blue: int, alpha: float) -> QColor:
    return QColor(red, green, blue, round(alpha * 255))


def _cellColors(dark: bool, checked: bool, hover: bool, pressed: bool):
    """Background, side border, accent border and whether the accent is at the bottom.

    Mirrors QFluentWidgets' button.qss for ToggleToolButton.
    """
    if checked:
        if pressed:
            color = (ThemeColor.DARK_2 if dark else ThemeColor.LIGHT_3).color()
            return color, color, None, False
        if dark:
            background = (ThemeColor.DARK_1 if hover else ThemeColor.PRIMARY).color()
            return background, ThemeColor.LIGHT_1.color(), ThemeColor.LIGHT_2.color(), True
        background = (ThemeColor.LIGHT_1 if hover else ThemeColor.PRIMARY).color()
        border = (ThemeColor.LIGHT_2 if hover else ThemeColor.LIGHT_1).color()
        return background, border, ThemeColor.DARK_1.color(), True

    if dark:
        if pressed:
            return _alpha(255, 255, 255, 0.0326), _alpha(255, 255, 255, 0.053), None, False
        background = _alpha(255, 255, 255, 0.0837 if hover else 0.0605)
        return background, _alpha(255, 255, 255, 0.053), _alpha(255, 255, 255, 0.08), False
    if pressed:
        return _alpha(249, 249, 249, 0.3), _alpha(0, 0, 0, 0.073), None, True
    background = (
        _alpha(249, 249, 249, 0.5) if hover else _alpha(255, 255, 255, 0.7)
    )
    return background, _alpha(0, 0, 0, 0.073), _alpha(0, 0, 0, 0.183), True


__all__ = ["IconGrid", "IconGridItem"]
