from copy import deepcopy

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

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.config.paths import ASSET_DIR


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
            self._onShowMenuTimeOut()
            return
        super()._onItemClicked(item)

class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None, homeCards=None):
        super().__init__(parent=parent)
        self.setIcon(QIcon(str(ASSET_DIR / "logo.png")))

        self._updateTrayTooltip(cfg.trayTooltip.value)

        cfg.trayTooltip.valueChanged.connect(self._updateTrayTooltip)

        self._homeCards = []
        self.setHomeCards(homeCards)
        cfg.broadcastTasks.valueChanged.connect(self._refreshBroadcastAction)
        cfg.shutdownTasks.valueChanged.connect(self._refreshShutdownAction)
        cfg.showBroadcastTrayAction.valueChanged.connect(self._rebuildMenu)
        cfg.showShutdownTrayAction.valueChanged.connect(self._rebuildMenu)
        cfg.trayHomeCardKeys.valueChanged.connect(self._rebuildMenu)
        cfg.trayHomeCardsInSubmenu.valueChanged.connect(self._rebuildMenu)
        self._rebuildMenu()
        self.activated.connect(self.onTrayIconClick)

    def _updateTrayTooltip(self, text):
        self.setToolTip(text.strip() or APP_NAME)

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
            QIcon(str(ASSET_DIR / "logo_cat.png")),
            "主页",
            menu,
        )
        self.showAction.triggered.connect(self._onShowActionTriggered)
        menu.addAction(self.showAction)

        if cfg.showBroadcastTrayAction.value:
            self.broadcastAction = Action(FIF.PLAY, "", menu)
            self.broadcastAction.triggered.connect(self._toggleBroadcastTasks)
            menu.addAction(self.broadcastAction)
            self._refreshTaskAction(
                self.broadcastAction,
                cfg.broadcastTasks.value,
                "关闭所有播报",
                "开启所有播报",
                FIF.PLAY,
            )
        else:
            self.broadcastAction = None

        if cfg.showShutdownTrayAction.value:
            self.shutdownAction = Action(FIF.POWER_BUTTON, "", menu)
            self.shutdownAction.triggered.connect(self._toggleShutdownTasks)
            menu.addAction(self.shutdownAction)
            self._refreshTaskAction(
                self.shutdownAction,
                cfg.shutdownTasks.value,
                "关闭所有关机",
                "开启所有关机",
                FIF.POWER_BUTTON,
            )
        else:
            self.shutdownAction = None

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

    def _toggleBroadcastTasks(self):
        self._toggleTasks(cfg.broadcastTasks)

    def _toggleShutdownTasks(self):
        self._toggleTasks(cfg.shutdownTasks)

    def _refreshBroadcastAction(self, tasks):
        if self.broadcastAction is not None:
            self._refreshTaskAction(
                self.broadcastAction,
                tasks,
                "关闭所有播报",
                "开启所有播报",
                FIF.PLAY,
            )

    def _refreshShutdownAction(self, tasks):
        if self.shutdownAction is not None:
            self._refreshTaskAction(
                self.shutdownAction,
                tasks,
                "关闭所有关机",
                "开启所有关机",
                FIF.POWER_BUTTON,
            )

    @staticmethod
    def _refreshTaskAction(
        action,
        tasks,
        enabledText,
        disabledText,
        disabledIcon,
    ):
        hasEnabledTask = any(task.get("enabled", False) for task in tasks)
        action.setText(enabledText if hasEnabledTask else disabledText)
        action.setIcon(FIF.PAUSE if hasEnabledTask else disabledIcon)
        action.setEnabled(bool(tasks))

    @staticmethod
    def _toggleTasks(configItem):
        tasks = deepcopy(configItem.value)
        enabled = not any(task.get("enabled", False) for task in tasks)
        for task in tasks:
            task["enabled"] = enabled
        cfg.set(configItem, tasks)

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
