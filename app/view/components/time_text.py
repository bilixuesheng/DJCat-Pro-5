"""Display Window 的时间：每个数字占一格，格宽是当前字体里最宽的数字。

比例字体里 "1" 比 "0" 窄，按原宽排字的话每走一秒整串都会重新居中。字体自带的等宽数字
（OpenType `tnum`）不是每种系统字体都有，所以按格自己排；冒号和空格保持原宽。
"""

from itertools import groupby

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QLabel

DIGITS = "0123456789"


def _layout(metrics: QFontMetricsF, text: str) -> tuple[list[tuple[float, str]], float]:
    cell = max(metrics.horizontalAdvance(digit) for digit in DIGITS)
    pieces = []
    x = 0.0
    for isDigit, chars in groupby(text, DIGITS.__contains__):
        if isDigit:
            for digit in chars:
                pieces.append((x + (cell - metrics.horizontalAdvance(digit)) / 2, digit))
                x += cell
        else:
            run = "".join(chars)
            pieces.append((x, run))
            x += metrics.horizontalAdvance(run)
    return pieces, x


def timeTextWidth(font: QFont, text: str) -> float:
    return _layout(QFontMetricsF(font), text)[1]


def paintTimeText(painter: QPainter, rect: QRectF, text: str) -> None:
    """Centre the time in rect with the painter's font and pen."""
    metrics = QFontMetricsF(painter.font())
    pieces, width = _layout(metrics, text)
    left = rect.center().x() - width / 2
    baseline = rect.center().y() + (metrics.ascent() - metrics.descent()) / 2
    for x, piece in pieces:
        painter.drawText(QPointF(left + x, baseline), piece)


class TimeLabel(QLabel):
    """Centred time in fixed digit cells, drawn in the label's text colour."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        paintTimeText(painter, QRectF(self.contentsRect()), self.text())
