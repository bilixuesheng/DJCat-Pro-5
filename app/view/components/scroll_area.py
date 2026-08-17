import sys

from PySide6.QtWidgets import QScroller

if sys.platform == "darwin":
    from qfluentwidgets import ScrollArea as FluentScrollArea
else:
    from qfluentwidgets import SmoothScrollArea as FluentScrollArea


class ScrollArea(FluentScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ownScrollAnimations()
        QScroller.grabGesture(
            self.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )

    def _ownScrollAnimations(self):
        """Keep qfluentwidgets' smooth-bar animations inside the bar lifetime."""
        delegate = getattr(self, "delegate", None)
        if delegate is None:
            return
        for name in ("vScrollBar", "hScrollBar"):
            bar = getattr(delegate, name, None)
            animation = getattr(bar, "ani", None)
            if animation is not None and animation.parent() is None:
                animation.setParent(bar)

    def enableTransparentBackground(self):
        self.setStyleSheet("QScrollArea{border: none; background: transparent}")
        self.viewport().setStyleSheet("background: transparent")
