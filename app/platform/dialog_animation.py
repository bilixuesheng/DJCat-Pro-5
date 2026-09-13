from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase


# 淡入淡出保持 qfluentwidgets 原实现：蒙层弹窗是父窗口的子控件，
# QWidget::setWindowOpacity 对非顶层控件直接 return，换成窗口透明度会让动画彻底失效。
def _setDialogShadow(
    dialog,
    blurRadius=60,
    offset=(0, 10),
    color=QColor(0, 0, 0, 100),
):
    shadow = dialog.widget.graphicsEffect()
    if not isinstance(shadow, QGraphicsDropShadowEffect):
        shadow = QGraphicsDropShadowEffect(dialog.widget)
        dialog.widget.setGraphicsEffect(shadow)

    shadow.setBlurRadius(blurRadius)
    shadow.setOffset(*offset)
    shadow.setColor(color)


def optimizeFluentDialogs() -> None:
    MaskDialogBase.setShadowEffect = _setDialogShadow
