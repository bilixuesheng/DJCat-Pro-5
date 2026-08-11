from PySide6.QtCore import QUrl
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


class MarkdownView(MarkdownWidget):
    def __init__(
        self,
        parent: QWidget | None = None,
        largeText: bool = False,
    ):
        super().__init__(DARK if isDarkTheme() else LIGHT, parent)
        self._largeText = largeText
        self.linkClicked.connect(self._openLink)
        self._applyLargeText()

    def setTheme(self, theme: Theme) -> None:
        super().setTheme(theme)
        self._applyLargeText()

    def syncTheme(self) -> None:
        self.setTheme(DARK if isDarkTheme() else LIGHT)

    def _applyLargeText(self) -> None:
        if self._largeText:
            self.setStyleSheet(f"{self.styleSheet()}\n{_LARGE_TEXT_QSS}")

    @staticmethod
    def _openLink(url: str) -> None:
        target = QUrl(url)
        if target.scheme().lower() in {"http", "https"}:
            QDesktopServices.openUrl(target)
