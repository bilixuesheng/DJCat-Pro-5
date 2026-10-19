import sys
from typing import NamedTuple

from loguru import logger
from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QSystemTrayIcon,
)
from qfluentwidgets import Action, FluentStyleSheet, RoundMenu, isDarkTheme
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets.common.screen import getCurrentScreenGeometry
from qfluentwidgets.components.widgets.menu import MenuActionListWidget
from qframelesswindow import WindowEffect

from app.common.application_icon import TRAY_ICON_ITEMS, trayHomeIcon, trayIcon
from app.config.cfg import cfg
from app.config.constants import APP_NAME

# 三类任务总开关：建菜单和刷新文字共用这一份名称与图标。
TRAY_TASK_ACTIONS = (
    (
        "broadcastAction",
        cfg.showBroadcastTrayAction,
        cfg.broadcastTasksEnabled,
        "定时播报",
        FIF.PLAY,
    ),
    (
        "homeCardTaskAction",
        cfg.showHomeCardTaskTrayAction,
        cfg.homeCardTasksEnabled,
        "自动任务",
        FIF.HISTORY,
    ),
    (
        "shutdownAction",
        cfg.showShutdownTrayAction,
        cfg.shutdownTasksEnabled,
        "定时关机",
        FIF.POWER_BUTTON,
    ),
)


def _isWindows11() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000


class CustomMenuStyle(QProxyStyle):
    def __init__(self, iconSize=14):
        super().__init__()
        self.iconSize = iconSize
    def pixelMetric(self, metric, option, widget):
        if metric == QStyle.PixelMetric.PM_SmallIconSize:
            return self.iconSize
        return super().pixelMetric(metric, option, widget)
    def polish(self, app, /):
        QStyleFactory.create("fusion").polish(app)
    def unpolish(self, app, /):
        QStyleFactory.create("fusion").polish(app)


class _TrayMenuActionListWidget(MenuActionListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewport().removeEventFilter(self.scrollDelegate)

    def wheelEvent(self, event):
        event.accept()


class AcrylicMenu(RoundMenu):
    # setStyle() 不接管样式对象，菜单的样式表还会把它包进 QStyleSheetStyle、只留一个裸指针。
    # 不在 Python 这边留着，它在菜单建好时就被回收，之后菜单一用样式（比如析构时清焦点）
    # 就踩到已释放的内存，整个进程崩溃。所有托盘菜单共用这一份，留到进程结束。
    _menuStyle = None

    def __init__(self, title="", parent=None):
        QMenu.__init__(self, parent)
        self._useSquareCorners = (
            sys.platform == "win32" and sys.getwindowsversion().build < 22000
        )
        self.setTitle(title)
        self._icon = QIcon()
        self._actions = []
        self._subMenus = []
        self.isSubMenu = False
        self.parentMenu = None
        self.menuItem = None
        self.lastHoverItem = None
        self.lastHoverSubMenuItem = None
        self.isHideBySystem = True
        self.itemHeight = 28

        self.hBoxLayout = QHBoxLayout(self)
        self.view = _TrayMenuActionListWidget(self)
        self.windowEffect = WindowEffect(self)
        self.timer = QTimer(self)
        self.__initWidgets()

    def __initWidgets(self):
        self.setWindowFlags(
            Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        if AcrylicMenu._menuStyle is None:
            AcrylicMenu._menuStyle = CustomMenuStyle()
        self.setStyle(AcrylicMenu._menuStyle)

        self.hBoxLayout.addWidget(self.view, 1, Qt.AlignmentFlag.AlignCenter)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        FluentStyleSheet.MENU.apply(self)
        self.view.setProperty("transparent", True)
        if self._useSquareCorners:
            self.view.setStyleSheet("border-radius: 0px;")
        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._onShowMenuTimeOut)
        self.view.itemClicked.connect(self._onItemClicked)
        self.view.itemEntered.connect(self._onItemEntered)

    def adjustPosition(self):
        if self.isSubMenu:
            return super().adjustPosition()
        m = self.hBoxLayout.contentsMargins()
        rect = getCurrentScreenGeometry()
        w = self.hBoxLayout.sizeHint().width() + 5
        x = max(rect.left(), min(self.x() - m.left(), rect.right() - w))
        y = max(
            rect.top(),
            min(self.y() - 45, rect.bottom() - self.height() + 1),
        )
        self.move(x, y)

    def showEvent(self, event):
        self.windowEffect.addMenuShadowEffect(self.winId())
        self.windowEffect.addShadowEffect(self.winId())
        self.windowEffect.enableBlurBehindWindow(self.winId())
        self.windowEffect.setAcrylicEffect(self.winId(), "00000030" if isDarkTheme() else "FFFFFF30")
        self.adjustPosition()
        if not self.isSubMenu:
            logger.info(
                "托盘菜单摆在 {}，设备像素比 {}",
                self.geometry().getRect(),
                self.devicePixelRatioF(),
            )
        self.raise_()
        self.activateWindow()
        self.setFocus()
        return super().showEvent(event)

    def hideEvent(self, e):
        super().hideEvent(e)
        # RoundMenu.hideEvent 不调 QMenu.hideEvent，而原生 QMenu.exec() 的事件循环只在那里退出。
        # 不补这一句，托盘菜单和它的二级菜单每 exec() 一次，就留下一个永远退不出去的事件循环。
        QMenu.hideEvent(self, e)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 1))
        painter.drawRect(self.rect())

    def _onItemClicked(self, item):
        submenu = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(submenu, RoundMenu):
            self.lastHoverItem = item
            self.lastHoverSubMenuItem = item
            self.timer.stop()
            self._onShowMenuTimeOut()
            return
        super()._onItemClicked(item)

def selectedShortcutKeys(value) -> set[str]:
    """The Home Card keys chosen as Tray Card Shortcuts, tolerating a damaged config."""
    if not isinstance(value, list):
        return set()
    return {key for key in value if isinstance(key, str)}


def _refreshTaskAction(action, enabled, label, icon):
    action.setText(("关闭" if enabled else "开启") + label)
    action.setIcon(FIF.PAUSE if enabled else icon)


class TrayMenuParts(NamedTuple):
    menu: AcrylicMenu
    showAction: Action
    taskActions: dict
    cardActions: list
    quitAction: Action
    submenu: AcrylicMenu | None


def buildTrayMenu(homeCards, homeIcon, parent=None) -> TrayMenuParts:
    """The Tray Menu as the current settings shape it, without any wiring.

    The tray connects the actions; the Setting Preview only draws the menu, so
    both always show the same rows, icons and texts.
    """
    menu = AcrylicMenu(parent=parent)
    showAction = Action(homeIcon, "主页", menu)
    menu.addAction(showAction)

    taskActions = {}
    for name, showItem, enabledItem, label, icon in TRAY_TASK_ACTIONS:
        if not showItem.value:
            taskActions[name] = None
            continue
        action = Action(icon, "", menu)
        _refreshTaskAction(action, enabledItem.value, label, icon)
        menu.addAction(action)
        taskActions[name] = action

    selected = selectedShortcutKeys(cfg.trayHomeCardKeys.value)
    cards = [entry for entry in homeCards if entry["key"] in selected]
    cardActions = []
    submenu = None
    if cards:
        menu.addSeparator()
        if cfg.trayHomeCardsInSubmenu.value:
            submenu = AcrylicMenu("主页卡片", menu)
            submenu.setIcon(FIF.HOME)
        owner = menu if submenu is None else submenu
        for entry in cards:
            action = Action(entry["icon"], entry["title"], owner)
            owner.addAction(action)
            cardActions.append((entry["key"], action))
        if submenu is not None:
            menu.addMenu(submenu)

    menu.addSeparator()
    quitAction = Action(FIF.CLOSE, "退出程序", menu)
    menu.addAction(quitAction)
    return TrayMenuParts(menu, showAction, taskActions, cardActions, quitAction, submenu)


class SystemTrayIcon(QSystemTrayIcon):
    showRequested = Signal()
    homeCardTriggered = Signal(str)
    quitRequested = Signal()

    def __init__(self, parent=None, homeCards=None):
        super().__init__(parent=parent)
        self._updateTrayIcon()

        self._updateTrayTooltip(cfg.trayTooltip.value)

        for item in TRAY_ICON_ITEMS:
            item.valueChanged.connect(self._updateTrayIcon)
        cfg.trayTooltip.valueChanged.connect(self._updateTrayTooltip)

        self._menuOpen = False
        self._reopenMenu = False
        self._homeCards = []
        self.setHomeCards(homeCards)
        for _name, showItem, enabledItem, _label, _icon in TRAY_TASK_ACTIONS:
            enabledItem.valueChanged.connect(self._refreshTaskActions)
            showItem.valueChanged.connect(self._rebuildMenu)
        cfg.trayHomeCardKeys.valueChanged.connect(self._rebuildMenu)
        cfg.trayHomeCardsInSubmenu.valueChanged.connect(self._rebuildMenu)
        self._rebuildMenu()
        self.activated.connect(self.onTrayIconClick)

    def _updateTrayTooltip(self, text):
        self.setToolTip(text.strip() or APP_NAME)

    def _updateTrayIcon(self, _value=None):
        self.setIcon(trayIcon())
        self._homeIcon = trayHomeIcon()
        if hasattr(self, "showAction"):
            self.showAction.setIcon(self._homeIcon)

    def setHomeCards(self, entries) -> None:
        self._homeCards = []
        keys = set()
        for entry in entries or []:
            key = entry.get("key") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not key or key in keys:
                continue
            keys.add(key)
            self._homeCards.append(dict(entry))
        if hasattr(self, "menu"):
            self._rebuildMenu()

    def _rebuildMenu(self, _value=None) -> None:
        oldMenu = getattr(self, "menu", None)
        parts = buildTrayMenu(self._homeCards, self._homeIcon, self.parent())

        self.showAction = parts.showAction
        self.showAction.triggered.connect(self.showRequested)
        for name, _showItem, enabledItem, _label, _icon in TRAY_TASK_ACTIONS:
            action = parts.taskActions[name]
            setattr(self, name, action)
            if action is not None:
                action.triggered.connect(
                    lambda _checked=False, item=enabledItem: self._toggleTasks(item)
                )
        for key, action in parts.cardActions:
            action.triggered.connect(
                lambda _checked=False, cardKey=key: self.homeCardTriggered.emit(cardKey)
            )
        self.quitAction = parts.quitAction
        self.quitAction.triggered.connect(self.quitRequested)

        self.menu = parts.menu
        self.setContextMenu(self.menu)
        if oldMenu is not None:
            oldMenu.close()
            oldMenu.deleteLater()

    def _refreshTaskActions(self, _value=None):
        for name, _showItem, enabledItem, label, icon in TRAY_TASK_ACTIONS:
            action = getattr(self, name, None)
            if action is not None:
                _refreshTaskAction(action, enabledItem.value, label, icon)

    @staticmethod
    def _toggleTasks(configItem):
        cfg.set(configItem, not configItem.value)

    def onTrayIconClick(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if cfg.trayLeftClickAction.value == "ShowMenu":
                self._openMenu()
            else:
                self.showRequested.emit()

    def _openMenu(self):
        # Win11 上手指点任务栏不会让菜单失去焦点收起，菜单开着时再点托盘，这一下就落在上一次
        # exec() 的事件循环里。在开着的菜单上再 exec() 会嵌套：菜单收起时只退出最里层，外层那个
        # 事件循环再也退不出来。所以这里只收起菜单，回到外层再在新位置打开。
        if self._menuOpen:
            logger.info("托盘菜单开着时又点了托盘，收起后重新打开")
            self._reopenMenu = True
            self.menu.hide()
            return
        self._menuOpen = True
        try:
            self._reopenMenu = True
            while self._reopenMenu:
                self._reopenMenu = False
                # 长按弹出的菜单还开着时，先收起才会重新走 showEvent() 的位置调整。
                self.menu.hide()
                self.menu.exec(self._menuPosition())
        finally:
            self._menuOpen = False

    def _menuPosition(self) -> QPoint:
        # Win11 的任务栏被手指点时不移动鼠标指针，指针还停在上一次在别处点过的地方。指针不在
        # 图标上就当作点了图标正中；Windows 给不出图标位置时照旧按指针。
        cursor = QCursor.pos()
        icon = self.geometry() if _isWindows11() else None
        anchor = cursor
        if icon is not None and not icon.isEmpty() and not icon.contains(cursor):
            anchor = icon.center()
        logger.info(
            "点托盘打开菜单：指针 {}，图标 {}，按 {} 打开",
            (cursor.x(), cursor.y()),
            icon.getRect() if icon is not None else None,
            (anchor.x(), anchor.y()),
        )
        return anchor
