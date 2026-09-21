import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter
from PySide6.QtWidgets import (
    QApplication,
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

from app.common.application_icon import applicationIcon, trayHomeIcon
from app.config.cfg import cfg
from app.config.constants import APP_NAME



# 三类任务总开关在建菜单和刷新时共用同一组名称与图标，集中在这里，改名时不会再漏掉某一处。
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
        self.setStyle(CustomMenuStyle())

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
        is_dark = isDarkTheme() if cfg.customThemeMode.value == "System" else cfg.customThemeMode.value == "Dark"
        self.windowEffect.setAcrylicEffect(self.winId(), "00000030" if is_dark else "FFFFFF30")
        self.adjustPosition()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        return super().showEvent(event)

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

class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None, homeCards=None):
        super().__init__(parent=parent)
        self._updateApplicationIcon()

        self._updateTrayTooltip(cfg.trayTooltip.value)

        cfg.applicationIconSource.valueChanged.connect(self._updateApplicationIcon)
        cfg.applicationIconPath.valueChanged.connect(self._updateApplicationIcon)
        cfg.trayTooltip.valueChanged.connect(self._updateTrayTooltip)

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

    def _updateApplicationIcon(self, _value=None):
        self.setIcon(applicationIcon())
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
        menu = AcrylicMenu(parent=self.parent())

        self.showAction = Action(
            self._homeIcon,
            "主页",
            menu,
        )
        self.showAction.triggered.connect(self._onShowActionTriggered)
        menu.addAction(self.showAction)

        for name, showItem, enabledItem, label, icon in TRAY_TASK_ACTIONS:
            if not showItem.value:
                setattr(self, name, None)
                continue
            action = Action(icon, "", menu)
            action.triggered.connect(
                lambda _checked=False, item=enabledItem: self._toggleTasks(item)
            )
            menu.addAction(action)
            setattr(self, name, action)
            self._refreshTaskAction(action, enabledItem.value, label, icon)

        selected = {
            key
            for key in cfg.trayHomeCardKeys.value
            if isinstance(key, str)
        } if isinstance(cfg.trayHomeCardKeys.value, list) else set()
        cards = [entry for entry in self._homeCards if entry["key"] in selected]
        if cards:
            menu.addSeparator()
            if cfg.trayHomeCardsInSubmenu.value:
                submenu = AcrylicMenu("主页卡片", menu)
                submenu.setIcon(FIF.HOME)
                for entry in cards:
                    submenu.addAction(self._cardAction(entry, submenu))
                menu.addMenu(submenu)
            else:
                for entry in cards:
                    menu.addAction(self._cardAction(entry, menu))

        menu.addSeparator()
        self.quitAction = Action(FIF.CLOSE, "退出程序", menu)
        self.quitAction.triggered.connect(self._onQuitActionTriggered)
        menu.addAction(self.quitAction)

        self.menu = menu
        self.setContextMenu(menu)
        if oldMenu is not None:
            oldMenu.close()
            oldMenu.deleteLater()

    def _cardAction(self, entry, parent):
        action = Action(entry["icon"], entry["title"], parent)
        action.triggered.connect(
            lambda _checked=False, key=entry["key"]: self._onHomeCardTriggered(key)
        )
        return action

    def _onHomeCardTriggered(self, key: str) -> None:
        parent = self.parent()
        handler = getattr(parent, "_onTrayHomeCardTriggered", None)
        if handler is not None:
            handler(key)

    def _onShowActionTriggered(self):
        parent = self.parent()
        if parent:
            showMainWindow = getattr(parent, "_showMainWindow", None)
            if callable(showMainWindow):
                showMainWindow()
                return
            parent.show()
            parent.raise_()
            parent.activateWindow()

    def _refreshTaskActions(self, _value=None):
        for name, _showItem, enabledItem, label, icon in TRAY_TASK_ACTIONS:
            action = getattr(self, name, None)
            if action is not None:
                self._refreshTaskAction(action, enabledItem.value, label, icon)

    @staticmethod
    def _refreshTaskAction(action, enabled, label, icon):
        action.setText(("关闭" if enabled else "开启") + label)
        action.setIcon(FIF.PAUSE if enabled else icon)

    @staticmethod
    def _toggleTasks(configItem):
        cfg.set(configItem, not configItem.value)

    def _onQuitActionTriggered(self):
        if self.parent():
            requestQuit = getattr(self.parent(), "requestQuit", None)
            if requestQuit is not None:
                requestQuit()
                return
        QApplication.quit()

    def onTrayIconClick(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if cfg.trayLeftClickAction.value == "ShowMenu":
                self.menu.exec(QCursor.pos())
            else:
                self._onShowActionTriggered()
