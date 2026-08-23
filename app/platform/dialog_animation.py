from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QGraphicsDropShadowEffect
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase


def _animateDialogOpacity(dialog, start, end, duration):
    previous = getattr(dialog, "_dialogOpacityAnimation", None)
    if previous is not None:
        previous.stop()

    animation = QPropertyAnimation(dialog, b"windowOpacity", dialog)
    animation.setStartValue(start)
    animation.setEndValue(end)
    animation.setDuration(duration)
    dialog._dialogOpacityAnimation = animation
    return animation


def _showDialog(dialog, event):
    animation = _animateDialogOpacity(dialog, 0.0, 1.0, 200)
    animation.setEasingCurve(QEasingCurve.Type.InSine)
    animation.start()
    QDialog.showEvent(dialog, event)


def _finishDialog(dialog, code):
    dialog.widget.setGraphicsEffect(None)
    animation = _animateDialogOpacity(dialog, 1.0, 0.0, 100)
    animation.finished.connect(lambda: dialog._onDone(code))
    animation.start()


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
    MaskDialogBase.showEvent = _showDialog
    MaskDialogBase.done = _finishDialog
    MaskDialogBase.setShadowEffect = _setDialogShadow
