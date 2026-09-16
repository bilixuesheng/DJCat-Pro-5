from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
)
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase


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


def _showEvent(self, e):
    shadow = self.widget.graphicsEffect()
    hasShadow = isinstance(shadow, QGraphicsDropShadowEffect)
    if hasShadow:
        shadow.setEnabled(False)

    opacityEffect = QGraphicsOpacityEffect(self)
    self.setGraphicsEffect(opacityEffect)
    opacityAni = QPropertyAnimation(opacityEffect, b"opacity", self)
    opacityAni.setStartValue(0)
    opacityAni.setEndValue(1)
    opacityAni.setDuration(200)
    opacityAni.setEasingCurve(QEasingCurve.InSine)

    def onFinished():
        self.setGraphicsEffect(None)
        if hasShadow:
            shadow.setEnabled(True)

    opacityAni.finished.connect(onFinished)
    opacityAni.start()
    QDialog.showEvent(self, e)


def _done(self, code):
    shadow = self.widget.graphicsEffect()
    if isinstance(shadow, QGraphicsDropShadowEffect):
        shadow.setEnabled(False)
    else:
        self.widget.setGraphicsEffect(None)

    opacityEffect = QGraphicsOpacityEffect(self)
    self.setGraphicsEffect(opacityEffect)
    opacityAni = QPropertyAnimation(opacityEffect, b"opacity", self)
    opacityAni.setStartValue(1)
    opacityAni.setEndValue(0)
    opacityAni.setDuration(100)
    opacityAni.finished.connect(lambda: self._onDone(code))
    opacityAni.start()


def optimizeFluentDialogs() -> None:
    MaskDialogBase.setShadowEffect = _setDialogShadow
    MaskDialogBase.showEvent = _showEvent
    MaskDialogBase.done = _done
