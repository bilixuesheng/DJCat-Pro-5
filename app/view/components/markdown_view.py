from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget
from qfluentwidgets import isDarkTheme

from pyqt_github_markdown import DARK, LIGHT, MarkdownWidget, Theme

_LARGE_TEXT_QSS = """
#markdown, #markdown QWidget { font-size: 26px; }
QLabel#h1 { font-size: 49px; }
QLabel#h2 { font-size: 36px; }
QLabel#h3 { font-size: 29px; }
QLabel#h4 { font-size: 26px; }
QLabel#h5 { font-size: 23px; }
QLabel#h6 { font-size: 21px; }
QLabel#paragraph { font-size: 26px; }
QLabel#code-lang { font-size: 19px; }
"""
_TRANSPARENT_QSS = """
#markdown, #markdown QWidget { background: transparent; }
#markdown #code-block, #markdown QTextEdit#code-editor {
    background: rgba(0, 0, 0, 0.28);
}
#markdown QLabel[role="header"], #markdown QLabel[odd="true"] {
    background: rgba(0, 0, 0, 0.18);
}
#markdown QFrame#hr { background: rgba(255, 255, 255, 0.45); }
"""


class MarkdownView(MarkdownWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        largeText: bool = False,
        transparentBackground: bool = False,
    ):
        super().__init__(DARK if isDarkTheme() else LIGHT, parent)
        self._largeText = largeText
        self._transparentBackground = transparentBackground
        if transparentBackground:
            for widget in (self._scroll, self._scroll.viewport(), self._content):
                widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                widget.setAutoFillBackground(False)
        self.linkClicked.connect(self._openLink)
        self._applyStyleOverrides()

    def setTheme(self, theme: Theme) -> None:
        super().setTheme(theme)
        self._applyStyleOverrides()

    def syncTheme(self) -> None:
        self.setTheme(DARK if isDarkTheme() else LIGHT)

    def _applyStyleOverrides(self) -> None:
        overrides = []
        if self._transparentBackground:
            overrides.append(_TRANSPARENT_QSS)
        if self._largeText:
            overrides.append(_LARGE_TEXT_QSS)
        if overrides:
            self.setStyleSheet(f"{self.styleSheet()}\n{''.join(overrides)}")

    @staticmethod
    def _openLink(url: str) -> None:
        target = QUrl(url)
        if target.scheme().lower() in {"http", "https"}:
            QDesktopServices.openUrl(target)
