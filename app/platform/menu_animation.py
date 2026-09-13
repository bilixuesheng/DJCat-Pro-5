from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QHoverEvent
from PySide6.QtWidgets import QApplication
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
        # 只省掉每帧的 viewport 强制刷新；悬停态仍逐帧同步，否则展开途中光标下的项不会高亮。
        self.menu.view.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        QApplication.sendEvent(
            self.menu.view,
            QHoverEvent(QEvent.Type.HoverEnter, QPoint(), QPoint(1, 1)),
        )

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
