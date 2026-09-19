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

from app.platform.dialog_animation import pauseDialogShadows, resumeDialogShadows


class _SmoothMenuAnimation:
    def __init__(self, menu):
        super().__init__(menu)
        self._maskOffset = None
        self._pausedShadows = []
        self.ani.finished.connect(self._finishAnimation)

    def exec(self, pos):
        self._pausedShadows = pauseDialogShadows()
        super().exec(pos)

    def _restoreShadows(self):
        if self._pausedShadows:
            resumeDialogShadows(self._pausedShadows)
            self._pausedShadows = []

    def _onValueChanged(self):
        # 菜单是顶层 Popup,setMask 会落到 SetWindowRgn:每次分配 GDI region 并强制整窗重绘。
        # 位移不足一像素时遮罩完全相同,跳过不改变任何观感。
        offset = self.ani.endValue().y() - self.ani.currentValue().y()
        if offset == self._maskOffset:
            return
        self._maskOffset = offset
        super()._onValueChanged()

    def _updateMenuViewport(self):
        # 只省掉每帧的 viewport 强制刷新；悬停态仍逐帧同步，否则展开途中光标下的项不会高亮。
        self.menu.view.setAttribute(Qt.WidgetAttribute.WA_UnderMouse, True)
        QApplication.sendEvent(
            self.menu.view,
            QHoverEvent(QEvent.Type.HoverEnter, QPoint(), QPoint(1, 1)),
        )

    def _finishAnimation(self):
        self._restoreShadows()
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
