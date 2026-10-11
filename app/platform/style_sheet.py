"""Keep QFluentWidgets' style sheet registry from growing on every theme change.

``updateStyleSheet()`` hands each widget's registered ``StyleSheetCompose`` back to
``StyleSheetManager.register()``, which wraps it in a new compose together with the
widget's ``CustomStyleSheet``. Every theme or theme color change therefore nests each
registered widget one level deeper, and the custom QSS is repeated once more in the
style sheet text. Nothing ever unwraps it.
"""

from qfluentwidgets.common.style_sheet import (
    CustomStyleSheet,
    StyleSheetCompose,
    StyleSheetManager,
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


def stopStyleSheetNesting() -> None:
    StyleSheetManager.register = _register
