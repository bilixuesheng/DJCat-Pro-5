import sys

from PySide6.QtWidgets import QScroller

if sys.platform == "darwin":
    from qfluentwidgets import ScrollArea as FluentScrollArea
else:
    from qfluentwidgets import SmoothScrollArea as FluentScrollArea


class ScrollArea(FluentScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        QScroller.grabGesture(
            self.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )

    def enableTransparentBackground(self):
        self.setStyleSheet("QScrollArea{border: none; background: transparent}")
        self.viewport().setStyleSheet("background: transparent")
