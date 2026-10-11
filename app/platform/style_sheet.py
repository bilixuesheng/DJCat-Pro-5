"""QFluentWidgets' theme updates: no ever-deeper registry, no redundant re-polish.

``updateStyleSheet()`` hands each widget's registered ``StyleSheetCompose`` back to
``StyleSheetManager.register()``, which wraps it in a new compose together with the
widget's ``CustomStyleSheet``. Every theme or theme color change therefore nests each
registered widget one level deeper, and the custom QSS is repeated once more in the
style sheet text. Nothing ever unwraps it.

It also sets every widget's style sheet again even when the text is unchanged, and Qt
re-polishes the whole subtree each time. The main window's page stack carries the
window's style sheet, which does not mention the theme color, yet re-applying it
re-polished all thirteen hundred widgets of every loaded page on each color change.
"""

from qfluentwidgets.common import style_sheet as _fluentStyleSheet
from qfluentwidgets.common.style_sheet import (
    CustomStyleSheet,
    StyleSheetCompose,
    StyleSheetManager,
    Theme,
    getStyleSheet,
    styleSheetManager,
)

_originalRegister = StyleSheetManager.register


def _register(self, source, widget, reset=True):
    if (
        reset
        and isinstance(source, StyleSheetCompose)
        and widget in self.widgets
        and CustomStyleSheet(widget) in source.sources
    ):
        # 交回来的就是这个控件已登记的组合，原样留着，不再包一层。
        self.widgets[widget] = source
        return
    _originalRegister(self, source, widget, reset)


def _setStyleSheet(widget, source, theme=Theme.AUTO, register=True):
    if register:
        styleSheetManager.register(source, widget)
    styleSheet = getStyleSheet(source, theme)
    if styleSheet != widget.styleSheet():
        widget.setStyleSheet(styleSheet)


def optimizeFluentStyleSheets() -> None:
    StyleSheetManager.register = _register
    # updateStyleSheet() 和 FluentStyleSheet.apply() 都按模块全局名调用它。
    _fluentStyleSheet.setStyleSheet = _setStyleSheet
