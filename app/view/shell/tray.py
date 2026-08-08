from copy import deepcopy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
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
        self.view = MenuActionListWidget(self)
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

        self.view.itemClicked.connect(self._onItemClicked)
        self.view.itemEntered.connect(self._onItemEntered)

    def adjustPosition(self):
        m = self.hBoxLayout.contentsMargins()
        rect = getCurrentScreenGeometry()
        w = self.hBoxLayout.sizeHint().width() + 5
        x = min(self.x() - m.left(), rect.right() - w)
        y = self.y() - 45
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

class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setIcon(QIcon(str(ASSET_DIR / "logo.png")))

        self.setToolTip(cfg.trayTooltip.value)

        cfg.trayTooltip.valueChanged.connect(self.setToolTip)

        self.menu = AcrylicMenu(parent=parent)

        self.showAction = Action(
            QIcon(str(ASSET_DIR / "logo_cat.png")),
            "主页",
            self.menu,
        )
        self.showAction.triggered.connect(self._onShowActionTriggered)
        self.menu.addAction(self.showAction)

        self.broadcastAction = Action(FIF.PLAY, "", self.menu)
        self.broadcastAction.triggered.connect(self._toggleBroadcastTasks)
        self.menu.addAction(self.broadcastAction)
        cfg.broadcastTasks.valueChanged.connect(self._refreshBroadcastAction)
        self._refreshTaskAction(
            self.broadcastAction,
            cfg.broadcastTasks.value,
            "关闭所有播报",
            "开启所有播报",
            FIF.PLAY,
        )

        self.shutdownAction = Action(FIF.POWER_BUTTON, "", self.menu)
        self.shutdownAction.triggered.connect(self._toggleShutdownTasks)
        self.menu.addAction(self.shutdownAction)
        cfg.shutdownTasks.valueChanged.connect(self._refreshShutdownAction)
        self._refreshTaskAction(
            self.shutdownAction,
            cfg.shutdownTasks.value,
            "关闭所有关机",
            "开启所有关机",
            FIF.POWER_BUTTON,
        )

        self.menu.addSeparator()

        self.quitAction = Action(FIF.CLOSE, "退出程序", self.menu)
        self.quitAction.triggered.connect(self._onQuitActionTriggered)
        self.menu.addAction(self.quitAction)

        self.setContextMenu(self.menu)
        self.activated.connect(self.onTrayIconClick)

    def _onShowActionTriggered(self):
        if self.parent():
            self.parent().show()
            self.parent().raise_()
            self.parent().activateWindow()

    def _toggleBroadcastTasks(self):
        self._toggleTasks(cfg.broadcastTasks)

    def _toggleShutdownTasks(self):
        self._toggleTasks(cfg.shutdownTasks)

    def _refreshBroadcastAction(self, tasks):
        self._refreshTaskAction(
            self.broadcastAction,
            tasks,
            "关闭所有播报",
            "开启所有播报",
            FIF.PLAY,
        )

    def _refreshShutdownAction(self, tasks):
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
            self._onShowActionTriggered()
