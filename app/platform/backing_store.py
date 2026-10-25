"""Copy what a window already shows from its back buffer instead of painting it again."""

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage


def paintedImage(widget) -> QImage | None:
    """The pixels the window last painted where ``widget`` is, or None when there are none."""
    window = widget.window()
    handle = window.windowHandle()
    store = window.backingStore()
    # 窗口还没画过时后备缓冲还没有图像，这时去读会崩溃。
    if handle is None or not handle.isExposed() or store is None or store.size().isEmpty():
        return None
    image = store.paintDevice()
    if not isinstance(image, QImage):
        return None
    ratio = image.devicePixelRatio()
    origin = widget.mapTo(window, QPoint())
    rect = QRect(
        round(origin.x() * ratio),
        round(origin.y() * ratio),
        round(widget.width() * ratio),
        round(widget.height() * ratio),
    )
    if not image.rect().contains(rect):
        return None
    painted = image.copy(rect)
    painted.setDevicePixelRatio(ratio)
    return painted
