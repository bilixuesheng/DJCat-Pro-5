from __future__ import annotations

from PySide6.QtCore import QPoint
from qfluentwidgets.components.widgets.menu import (
    DropDownMenuAnimationManager,
    MenuAnimationManager,
    MenuAnimationType,
    PullUpMenuAnimationManager,
)


MENU_ANIMATION_DURATION_MS = 160
MENU_ANIMATION_OFFSET = 8


class _SmoothMenuAnimation:
    _offset = 0

    def __init__(self, menu):
        super().__init__(menu)
        self.ani.setDuration(MENU_ANIMATION_DURATION_MS)
        self.ani.finished.connect(self._finishAnimation)

    def exec(self, pos):
        endPosition = self._endPosition(pos)
        self.ani.setStartValue(endPosition + QPoint(0, self._offset))
        self.ani.setEndValue(endPosition)
        self.ani.start()

    def _onValueChanged(self):
        pass

    def _updateMenuViewport(self):
        pass

    def _finishAnimation(self):
        MenuAnimationManager._updateMenuViewport(self)


class _SmoothDropDownMenuAnimation(
    _SmoothMenuAnimation,
    DropDownMenuAnimationManager,
):
    _offset = -MENU_ANIMATION_OFFSET


class _SmoothPullUpMenuAnimation(
    _SmoothMenuAnimation,
    PullUpMenuAnimationManager,
):
    _offset = MENU_ANIMATION_OFFSET


def optimizeFluentMenus() -> None:
    MenuAnimationManager.managers[MenuAnimationType.DROP_DOWN] = (
        _SmoothDropDownMenuAnimation
    )
    MenuAnimationManager.managers[MenuAnimationType.PULL_UP] = (
        _SmoothPullUpMenuAnimation
    )
