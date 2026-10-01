from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScroller

from qfluentwidgets import ColorDialog as FluentColorDialog

from app.view.components.scroll_area import ScrollArea, registerTouchDragTarget


class ColorDialog(FluentColorDialog):
    """QFluentWidgets' color dialog, scrolled by the project ``ScrollArea``.

    The library's ``SingleDirectionScrollArea`` never grabs a touch gesture, so a
    short window left the lower half of the dialog out of a finger's reach.
    """

    def __init__(self, color, title: str, parent=None, enableAlpha=False):
        super().__init__(color, title, parent, enableAlpha)
        self._closing = False
        self._replaceScrollArea()
        registerTouchDragTarget(self.huePanel)
        registerTouchDragTarget(self.brightSlider)

    def _replaceScrollArea(self) -> None:
        libraryScrollArea = self.scrollArea
        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scrollArea.setViewportMargins(libraryScrollArea.viewportMargins())
        self.scrollArea.setWidget(libraryScrollArea.takeWidget())
        self.vBoxLayout.replaceWidget(libraryScrollArea, self.scrollArea)
        libraryScrollArea.deleteLater()

    def done(self, code):
        if self._closing:
            return
        self._closing = True
        viewport = self.scrollArea.viewport()
        QScroller.scroller(viewport).stop()
        QScroller.ungrabGesture(viewport)
        super().done(code)
