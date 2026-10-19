"""Frame Rate: how many times a second DJCat repaints a window, in its top-left corner.

Windows reports the frames it actually shows only for the whole desktop
(``DwmGetCompositionTimingInfo`` takes no window since 8.1), so this counts the
window's own repaints instead: Qt posts one ``UpdateRequest`` to a top-level widget
for each repaint it flushes to the screen. With Super Frame Rate Optimization on, the
count can exceed the screen's refresh rate; the system shows only as many as it
refreshes.
"""

import weakref

from PySide6.QtCore import QElapsedTimer, QEvent, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import QWidget

SAMPLE_INTERVAL_MS = 1000
CORNER_INSET = 8

_trackedWindows = weakref.WeakSet()
_shown = False


class FrameRateLabel(QWidget):
    """White on translucent black, readable over any background; never takes input."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        font = QFont(self.font())
        font.setPixelSize(12)
        # 等宽数字，位数变了也不晃。
        font.setFeature(QFont.Tag("tnum"), 1)
        self.setFont(font)
        self._fitSize()
        self._text = ""
        self._frames = 0
        self._ownRepaints = 0
        self._clock = QElapsedTimer()
        self._clock.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._sample)
        self._timer.start(SAMPLE_INTERVAL_MS)
        self._setFramesPerSecond(0)
        window.installEventFilter(self)
        self._place()
        self.show()

    def _fitSize(self) -> None:
        metrics = QFontMetrics(self.font())
        self.setFixedSize(
            metrics.horizontalAdvance("0000 FPS") + 12, metrics.height() + 6
        )

    def changeEvent(self, event):
        # App Font 换了家族，宽度按新字体重算。
        if event.type() == QEvent.Type.FontChange:
            self._fitSize()
        super().changeEvent(event)

    def text(self) -> str:
        return self._text

    def eventFilter(self, obj, event):
        eventType = event.type()
        if eventType == QEvent.Type.UpdateRequest:
            self._frames += 1
        elif eventType == QEvent.Type.ChildAdded:
            # 蒙层弹窗、InfoBar 和启动页都是后来的子控件，会叠到标签上面。
            if event.child().isWidgetType():
                QTimer.singleShot(0, self, self._raiseAboveSiblings)
        elif eventType in (QEvent.Type.Resize, QEvent.Type.ContentsRectChange):
            self._place()
        return False

    def detach(self) -> None:
        self.parentWidget().removeEventFilter(self)
        # 先离开窗口，删掉之前马上又打开时才会换上新的。
        self.setParent(None)
        self.deleteLater()

    def _sample(self):
        elapsed = max(self._clock.restart(), 1)
        frames = max(self._frames - self._ownRepaints, 0)
        self._frames = 0
        self._ownRepaints = 0
        self._setFramesPerSecond(round(frames * 1000 / elapsed))

    def _setFramesPerSecond(self, framesPerSecond: int) -> None:
        text = f"{framesPerSecond} FPS"
        if text == self._text:
            return
        self._text = text
        if self.isVisible():
            # 换数字要重画这个窗口一次，那一次不是窗口自己的帧。
            self._ownRepaints += 1
        self.update()

    def _place(self):
        self.move(self.parentWidget().contentsRect().topLeft() + QPoint(CORNER_INSET, CORNER_INSET))

    def _raiseAboveSiblings(self):
        siblings = [
            child for child in self.parentWidget().children() if child.isWidgetType()
        ]
        if siblings[-1] is not self:
            self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 153))
        painter.drawRoundedRect(QRectF(self.rect()), 4, 4)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


def isFrameRateShown() -> bool:
    return _shown


def setFrameRateShown(shown: bool) -> None:
    """Show or remove the label on every tracked window at once; idempotent."""
    global _shown
    _shown = bool(shown)
    for window in tuple(_trackedWindows):
        _syncLabel(window)


def trackFrameRate(window: QWidget) -> None:
    """Let ``window`` carry the label whenever 显示帧率 is on."""
    _trackedWindows.add(window)
    _syncLabel(window)


def _syncLabel(window):
    try:
        label = window.findChild(
            FrameRateLabel, options=Qt.FindChildOption.FindDirectChildrenOnly
        )
    except RuntimeError:
        _trackedWindows.discard(window)
        return
    if _shown and label is None:
        FrameRateLabel(window)
    elif not _shown and label is not None:
        label.detach()
