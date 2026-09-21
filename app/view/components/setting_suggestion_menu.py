from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import QListWidgetItem
from qfluentwidgets.components.widgets.line_edit import CompleterMenu

EMPTY_SUGGESTION_TEXT = "无匹配项"


class SettingSuggestionMenu(CompleterMenu):
    """The settings search box's suggestion popup.

    Unlike the stock completer it never writes the chosen line back into the
    search box: a suggestion carries a Setting Route, not a search term.
    """

    suggestionActivated = Signal(object)

    def __init__(self, lineEdit):
        super().__init__(lineEdit)
        self._suggestions = []

    def setSuggestions(self, suggestions) -> bool:
        """Return whether the popup needs to be shown again."""
        suggestions = list(suggestions)
        items = [suggestion.text for suggestion in suggestions] or [
            EMPTY_SUGGESTION_TEXT
        ]
        if self.items == items and self.isVisible():
            return False

        self._suggestions = suggestions
        self.items = items
        self.indexes.clear()
        self.view.clear()
        for suggestion in suggestions:
            item = QListWidgetItem(suggestion.text)
            if suggestion.icon is not None:
                item.setIcon(suggestion.icon)
            item.setSizeHint(QSize(1, self.itemHeight))
            self.view.addItem(item)
        if not suggestions:
            item = QListWidgetItem(EMPTY_SUGGESTION_TEXT)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setSizeHint(QSize(1, self.itemHeight))
            self.view.addItem(item)
        return True

    def _onCompletionItemSelected(self, text: str, row: int) -> None:
        if 0 <= row < len(self._suggestions):
            self.suggestionActivated.emit(self._suggestions[row])

    def eventFilter(self, obj, event) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return)
            and self.view.currentRow() < 0
            and self._suggestions
        ):
            self._onCompletionItemSelected(self.items[0], 0)
            self.close()
            return True
        return super().eventFilter(obj, event)
