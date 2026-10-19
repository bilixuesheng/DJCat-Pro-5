"""Choosing an App Font: a searchable list of the installed fonts, each named in its own face."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter
from PySide6.QtWidgets import QLabel, QScroller, QSizePolicy, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    MessageBoxBase,
    PushButton,
    SearchLineEdit,
    SettingCard,
    SubtitleLabel,
    isDarkTheme,
    themeColor,
)

from app.common.app_font import (
    DEFAULT_CJK_FAMILIES,
    fontInstalled,
    previewFamilies,
    systemFontFamily,
)
from app.config.cfg import DEFAULT_FONT, SYSTEM_FONT, cfg
from app.view.components.scroll_area import ScrollArea, registerTouchPressTarget

ROW_HEIGHT = 40
ROW_RADIUS = 5
ROW_PADDING = 16
ROW_FONT_SIZE = 15
SAMPLE_TEXT = "电教猫 DJCat 0123456789，。“引号” \"quotes\""


def fontDisplayName(value: str) -> str:
    if value == DEFAULT_FONT:
        return "默认"
    if value == SYSTEM_FONT:
        return f"跟随系统（{systemFontFamily()}）"
    if not fontInstalled(value):
        return f"{value}（未安装，正在使用默认）"
    return value


@dataclass(frozen=True)
class FontChoice:
    value: str
    text: str
    families: tuple[str, ...]


def fontChoices(item) -> list[FontChoice]:
    """「默认」first, then 「跟随系统」 where it applies, then the installed families.

    The CJK Font lists only fonts that cover Simplified Chinese; vertical ``@`` faces
    and application-private families are never offered.
    """
    cjkOnly = item is cfg.cjkFont
    choices = [FontChoice(DEFAULT_FONT, "默认", tuple(previewFamilies(item, DEFAULT_FONT)))]
    if not cjkOnly:
        system = systemFontFamily()
        choices.append(
            FontChoice(SYSTEM_FONT, f"跟随系统（{system}）", (system, *DEFAULT_CJK_FAMILIES))
        )
    for family in QFontDatabase.families():
        if family.startswith("@") or QFontDatabase.isPrivateFamily(family):
            continue
        systems = QFontDatabase.writingSystems(family)
        chinese = QFontDatabase.WritingSystem.SimplifiedChinese in systems
        if cjkOnly and not chinese:
            continue
        # 符号字体（Wingdings 之类）用自己写出来是一串图形，名字改用界面字体写。
        readable = chinese or QFontDatabase.WritingSystem.Latin in systems
        families = (family, *DEFAULT_CJK_FAMILIES) if readable else ()
        choices.append(FontChoice(family, family, families))
    return choices


class FontList(QWidget):
    """Every font choice painted by one widget, each name in its own face.

    A machine has hundreds of fonts. As list items or buttons each one would need
    its own polish; painting only the rows inside the exposed rectangle keeps the
    picker quick to open, the same reason the icon library uses ``IconGrid``.
    """

    choiceClicked = Signal(int)
    choiceActivated = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._choices: list[FontChoice] = []
        self._visible: list[int] = []
        self._current: int | None = None
        self._hover: int | None = None
        self._pressed: int | None = None
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        registerTouchPressTarget(self)

    def setChoices(self, choices: list[FontChoice]) -> None:
        self._choices = list(choices)
        self._current = None
        self.setFilterText("")

    def choices(self) -> tuple[FontChoice, ...]:
        return tuple(self._choices)

    def visibleIndexes(self) -> tuple[int, ...]:
        return tuple(self._visible)

    def setFilterText(self, text: str) -> None:
        query = text.strip().lower()
        self._visible = [
            index
            for index, choice in enumerate(self._choices)
            if not query or query in choice.text.lower()
        ]
        self._hover = self._pressed = None
        self.setFixedHeight(max(1, len(self._visible)) * ROW_HEIGHT)
        self.update()

    def currentIndex(self) -> int | None:
        return self._current

    def setCurrentIndex(self, index: int | None) -> None:
        if index == self._current:
            return
        previous, self._current = self._current, index
        for changed in (previous, index):
            if changed is not None:
                self.update(self.rowRect(changed))

    def indexOfValue(self, value: str) -> int | None:
        return next(
            (index for index, choice in enumerate(self._choices) if choice.value == value),
            None,
        )

    def rowRect(self, index: int) -> QRect:
        """Geometry of a choice, or an empty rect when the search hides it."""
        try:
            row = self._visible.index(index)
        except ValueError:
            return QRect()
        return QRect(0, row * ROW_HEIGHT, self.width(), ROW_HEIGHT)

    def indexAt(self, y: float) -> int | None:
        row = int(y // ROW_HEIGHT)
        return self._visible[row] if 0 <= row < len(self._visible) and y >= 0 else None

    def sizeHint(self) -> QSize:
        return QSize(320, self.height())

    def paintEvent(self, event) -> None:
        if not self._visible:
            return
        exposed = event.rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = isDarkTheme()
        first = max(0, exposed.top() // ROW_HEIGHT)
        last = min(len(self._visible) - 1, exposed.bottom() // ROW_HEIGHT)
        for row in range(first, last + 1):
            self._paintRow(painter, self._visible[row], dark)

    def _paintRow(self, painter: QPainter, index: int, dark: bool) -> None:
        rect = self.rowRect(index)
        frame = QRectF(rect).adjusted(4, 2, -4, -2)
        alpha = 0
        if index == self._pressed and index == self._hover:
            alpha = 6 if not dark else 9
        elif index in (self._hover, self._current):
            alpha = 9 if not dark else 13
        if alpha:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, alpha) if dark else QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(frame, ROW_RADIUS, ROW_RADIUS)
        if index == self._current:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(themeColor())
            indicator = QRectF(frame.left(), frame.center().y() - 8, 3, 16)
            painter.drawRoundedRect(indicator, 1.5, 1.5)

        choice = self._choices[index]
        font = QFont(self.font())
        if choice.families:
            font.setFamilies(list(choice.families))
        font.setPixelSize(ROW_FONT_SIZE)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255) if dark else QColor(0, 0, 0))
        textRect = rect.adjusted(ROW_PADDING, 0, -ROW_PADDING, 0)
        text = QFontMetrics(font).elidedText(
            choice.text, Qt.TextElideMode.ElideRight, textRect.width()
        )
        painter.drawText(textRect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def cancelTouchPress(self) -> None:
        if self._pressed is None:
            return
        pressed, self._pressed = self._pressed, None
        self.update(self.rowRect(pressed))

    def _setHover(self, index: int | None) -> None:
        if index == self._hover:
            return
        previous, self._hover = self._hover, index
        for changed in (previous, index):
            if changed is not None:
                self.update(self.rowRect(changed))

    def mouseMoveEvent(self, event) -> None:
        self._setHover(self.indexAt(event.position().y()))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        index = self.indexAt(event.position().y())
        self._pressed = index
        self._setHover(index)
        if index is not None:
            self.update(self.rowRect(index))
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        pressed, self._pressed = self._pressed, None
        if pressed is None:
            event.accept()
            return
        self.update(self.rowRect(pressed))
        if pressed == self.indexAt(event.position().y()):
            self.setCurrentIndex(pressed)
            self.choiceClicked.emit(pressed)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.indexAt(event.position().y())
        if event.button() == Qt.MouseButton.LeftButton and index is not None:
            self.setCurrentIndex(index)
            self.choiceActivated.emit(index)
        event.accept()

    def keyPressEvent(self, event) -> None:
        step = {Qt.Key.Key_Up: -1, Qt.Key.Key_Down: 1}.get(event.key())
        if step is None or not self._visible:
            super().keyPressEvent(event)
            return
        row = self._visible.index(self._current) + step if self._current in self._visible else 0
        index = self._visible[max(0, min(len(self._visible) - 1, row))]
        self.setCurrentIndex(index)
        self.choiceClicked.emit(index)

    def leaveEvent(self, event) -> None:
        self._setHover(None)
        super().leaveEvent(event)


class FontPickerDialog(MessageBoxBase):
    def __init__(self, item, title: str, parent=None):
        super().__init__(parent)
        self._item = item
        self._initWidget(title)
        self._initLayout()
        self._bind()

    def _initWidget(self, title: str) -> None:
        self.titleLabel = SubtitleLabel(title, self)
        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("搜索字体")
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.enableTransparentBackground()
        self.scrollArea.setFixedHeight(ROW_HEIGHT * 9)
        self.fontList = FontList(self.scrollArea)
        self.scrollArea.setWidget(self.fontList)
        self.fontList.setChoices(fontChoices(self._item))
        self.fontList.setCurrentIndex(self.fontList.indexOfValue(self._item.value) or 0)
        self.sampleLabel = QLabel(SAMPLE_TEXT, self)
        self.sampleLabel.setWordWrap(True)
        self.yesButton.setText("选择")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(480)
        self._refreshSample()

    def _initLayout(self) -> None:
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.searchEdit)
        self.viewLayout.addWidget(self.scrollArea)
        self.viewLayout.addWidget(self.sampleLabel)

    def _bind(self) -> None:
        self.searchEdit.textChanged.connect(self.fontList.setFilterText)
        self.fontList.choiceClicked.connect(self._onChoiceClicked)
        self.fontList.choiceActivated.connect(lambda _index: self.accept())

    def selectedValue(self) -> str:
        return self.fontList.choices()[self.fontList.currentIndex()].value

    def _onChoiceClicked(self, index: int) -> None:
        self._refreshSample()
        rect = self.fontList.rowRect(index)
        self.scrollArea.ensureVisible(0, rect.center().y(), 0, ROW_HEIGHT)

    def _refreshSample(self) -> None:
        font = QFont(self.font())
        font.setFamilies(previewFamilies(self._item, self.selectedValue()))
        font.setPixelSize(18)
        self.sampleLabel.setFont(font)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        rect = self.fontList.rowRect(self.fontList.currentIndex())
        self.scrollArea.ensureVisible(0, rect.center().y(), 0, ROW_HEIGHT * 4)

    def done(self, code) -> None:
        viewport = self.scrollArea.viewport()
        QScroller.scroller(viewport).stop()
        QScroller.ungrabGesture(viewport)
        super().done(code)


class FontSettingCard(SettingCard):
    """One App Font value: its name, and a button that opens the picker."""

    def __init__(self, item, title: str, content: str, parent=None):
        super().__init__(FluentIcon.FONT, title, content, parent)
        self.item = item
        self.valueLabel = BodyLabel(self)
        self.chooseButton = PushButton("选择", self)
        self.hBoxLayout.addWidget(self.valueLabel)
        self.hBoxLayout.addSpacing(12)
        self.hBoxLayout.addWidget(self.chooseButton)
        self.hBoxLayout.addSpacing(16)
        self.chooseButton.clicked.connect(self._choose)
        item.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args) -> None:
        self.valueLabel.setText(fontDisplayName(self.item.value))

    def _choose(self) -> None:
        dialog = FontPickerDialog(self.item, f"选择{self.titleLabel.text()}", self.window())
        try:
            if dialog.exec():
                cfg.set(self.item, dialog.selectedValue())
        finally:
            dialog.deleteLater()
