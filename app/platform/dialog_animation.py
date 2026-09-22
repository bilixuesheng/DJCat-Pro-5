from __future__ import annotations

import weakref

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
)
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

_SHADOW_FADE_MS = 150
_activeMaskDialogs = weakref.WeakSet()


def pauseDialogShadows():
    paused = []
    for dialog in list(_activeMaskDialogs):
        try:
            shadow = dialog.widget.graphicsEffect()
        except RuntimeError:
            continue
        if isinstance(shadow, QGraphicsDropShadowEffect) and shadow.isEnabled():
            shadow.setEnabled(False)
            paused.append(shadow)
    return paused


def resumeDialogShadows(paused):
    for shadow in paused:
        try:
            shadow.setEnabled(True)
        except RuntimeError:
            pass


def _findCardShadow(widget):
    """The shadow on the enclosing MaskDialogBase's card, or None.

    Deliberately not "the first drop shadow up the parent chain": that would let a
    caller outside a dialog seize an unrelated shadow, such as WindowBackground's.
    """
    node = widget
    while node is not None:
        if isinstance(node, MaskDialogBase):
            effect = node.widget.graphicsEffect()
            return effect if isinstance(effect, QGraphicsDropShadowEffect) else None
        node = node.parentWidget()
    return None


def fadeDialogShadow(widget, visible):
    """Fade the mask dialog card shadow above `widget` in or out.

    A QGraphicsEffect re-rasterises its whole subtree whenever any descendant repaints,
    so a lit card shadow would re-run its blur on every frame of a long-running child
    animation. Returns None when there is no card shadow to fade.
    """
    effect = _findCardShadow(widget)
    if effect is None:
        return None

    target = getattr(effect, "_djcatShadowColor", None)
    if target is None:
        target = QColor(effect.color())
        effect._djcatShadowColor = target

    end = QColor(target)
    if not visible:
        end.setAlpha(0)

    animation = QPropertyAnimation(effect, b"color", effect)
    animation.setStartValue(QColor(effect.color()))
    animation.setEndValue(end)
    animation.setDuration(_SHADOW_FADE_MS)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


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
    _activeMaskDialogs.add(self)
    shadow = self.widget.graphicsEffect()
    hasShadow = isinstance(shadow, QGraphicsDropShadowEffect)
    shadowColor = shadow.color() if hasShadow else None
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
        if not hasShadow:
            return
        transparent = QColor(shadowColor)
        transparent.setAlpha(0)
        shadow.setColor(transparent)
        shadow.setEnabled(True)
        colorAni = QPropertyAnimation(shadow, b"color", self)
        colorAni.setStartValue(transparent)
        colorAni.setEndValue(shadowColor)
        colorAni.setDuration(_SHADOW_FADE_MS)
        colorAni.setEasingCurve(QEasingCurve.OutCubic)
        colorAni.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    opacityAni.finished.connect(onFinished)
    opacityAni.start()
    QDialog.showEvent(self, e)


def _done(self, code):
    _activeMaskDialogs.discard(self)
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
