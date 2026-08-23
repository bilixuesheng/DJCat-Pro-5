from __future__ import annotations

from qfluentwidgets.components.widgets.menu import (
    DropDownMenuAnimationManager,
    MenuAnimationManager,
    MenuAnimationType,
    PullUpMenuAnimationManager,
)


class _SmoothMenuAnimation:
    def __init__(self, menu):
        super().__init__(menu)
        self.ani.finished.connect(self._finishAnimation)

    def _updateMenuViewport(self):
        pass

    def _finishAnimation(self):
        MenuAnimationManager._updateMenuViewport(self)


class _SmoothDropDownMenuAnimation(
    _SmoothMenuAnimation,
    DropDownMenuAnimationManager,
):
    pass


class _SmoothPullUpMenuAnimation(
    _SmoothMenuAnimation,
    PullUpMenuAnimationManager,
):
    pass


def optimizeFluentMenus() -> None:
    MenuAnimationManager.managers[MenuAnimationType.DROP_DOWN] = (
        _SmoothDropDownMenuAnimation
    )
    MenuAnimationManager.managers[MenuAnimationType.PULL_UP] = (
        _SmoothPullUpMenuAnimation
    )
