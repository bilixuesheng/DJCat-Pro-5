"""App Font: the font DJCat shows its text in.

QFluentWidgets widgets take the families in ``qconfig.fontFamilies`` through their style
sheets and ``getFont()``. Plain Qt widgets (the banner's "主页", the countdown and clock
titles, the Projection body) name no family and inherit the QApplication font, which Qt 6
on Windows takes from the system message font. When that font has no Chinese glyphs,
Qt does not follow Windows font linking (SystemLink); it walks its own fallback list,
and for the Simplified Chinese locale that list starts with SimSun. Both sides must
therefore carry the same families.
"""

from PySide6.QtWidgets import QApplication
from qfluentwidgets import qconfig


def applyAppFont() -> None:
    app = QApplication.instance()
    font = app.font()
    font.setFamilies(qconfig.get(qconfig.fontFamilies))
    app.setFont(font)
