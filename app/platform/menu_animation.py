from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QHoverEvent
from PySide6.QtWidgets import QApplication
from qfluentwidgets.components.widgets.menu import (
    DropDownMenuAnimationManager,
    MenuAnimationManager,
    MenuAnimationType,
    PullUpMenuAnimationManager,
    RoundMenu,
)

from app.platform.shadow_effect import SilhouetteShadowEffect

# 与 QFluentWidgets MenuActionListWidget 的 border-radius 一致。
MENU_PANEL_RADIUS = 9


class _SmoothMenuAnimation:
    def __init__(self, menu):
        super().__init__(menu)
        self._maskOffset = None
        self.ani.finished.connect(self._finishAnimation)

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


def _setMenuShadow(self, blurRadius=30, offset=(0, 8), color=QColor(0, 0, 0, 30)):
    # 原版阴影挂在菜单面板上，悬停任何一项都会把整块面板离屏重画并重新模糊；
    # 轮廓阴影只在面板尺寸变化时模糊一次，观感与原版一致。
    self.shadowEffect = SilhouetteShadowEffect(MENU_PANEL_RADIUS, self.view)
    self.shadowEffect.setBlurRadius(blurRadius)
    self.shadowEffect.setOffset(*offset)
    self.shadowEffect.setColor(color)
    self.view.setGraphicsEffect(None)
    self.view.setGraphicsEffect(self.shadowEffect)


def optimizeFluentMenus() -> None:
    RoundMenu.setShadowEffect = _setMenuShadow
    MenuAnimationManager.managers[MenuAnimationType.DROP_DOWN] = (
        _SmoothDropDownMenuAnimation
    )
    MenuAnimationManager.managers[MenuAnimationType.PULL_UP] = (
        _SmoothPullUpMenuAnimation
    )
