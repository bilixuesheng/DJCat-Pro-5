import threading
import re
import requests
from PySide6.QtCore import Qt, Signal, QObject, QUrl, QPropertyAnimation
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect
from qfluentwidgets import (MSFluentWindow, NavigationItemPosition, FluentIcon as FIF, 
                            setTheme, Theme, SplashScreen, InfoBar, InfoBarPosition, 
                            PrimaryPushButton, PushButton, MessageBoxBase, SubtitleLabel, 
                            TextEdit, setThemeColor)

from app.common.config import cfg, APP_NAME, UPDATE_API
from app.common.signal_bus import signalBus
from app.view.home_page import HomePage
from app.view.setting_page import SettingPage
from app.view.broadcast_page import BroadcastEditPage
from app.view.components.tray import SystemTrayIcon

class CustomSplashScreen(SplashScreen):
    def finish(self):
        opacityEffect = QGraphicsOpacityEffect(self)
        opacityEffect.setOpacity(1)
        self.setGraphicsEffect(opacityEffect)
        opacityAni = QPropertyAnimation(opacityEffect, b'opacity', self)
        opacityAni.setStartValue(1)
        opacityAni.setEndValue(0)
        opacityAni.setDuration(200)
        opacityAni.finished.connect(self.deleteLater)
        opacityAni.start()

class UpdateWorker(QObject):
    finished = Signal(dict, str)
    def run(self, manual):
        try:
            response = requests.get(UPDATE_API, timeout=5)
            response.raise_for_status()
            data = response.json()
            self.finished.emit(data, "")
        except Exception as e:
            self.finished.emit({}, str(e))

class UpdateDialog(MessageBoxBase):
    def __init__(self, version, note, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(f"发现新版本: v{version}", self)
        self.textEdit = TextEdit(self)
        self.textEdit.setMarkdown(note)
        self.textEdit.setReadOnly(True)
        self.textEdit.setFixedSize(460, 260)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addSpacing(12)
        self.viewLayout.addWidget(self.textEdit)
        self.yesButton.setText("下载更新")
        self.cancelButton.setText("暂不更新")
        self.widget.setMinimumWidth(500)


class MainWindow(MSFluentWindow):
    def __init__(self):
        super().__init__(parent=None)
        
        setThemeColor(cfg.customThemeColor.value)
        self._toggleTheme(cfg.customThemeMode.value)
        cfg.customThemeMode.valueChanged.connect(self._toggleTheme)
        
        self.initWindow()
        self.initSplashScreen()
        QApplication.processEvents()

        self.initNavigation()
        self.tray = SystemTrayIcon(self)
        self.tray.show()
        
        signalBus.catchException.connect(self._onExceptionCaught)
        self.splashScreen.finish()

        if cfg.checkUpdateAtStartUp.value:
            self.checkForUpdates(manual=False)

    def initWindow(self):
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon('logo.png'))
        self.setMinimumSize(800, 400)
        self.resize(800, 400)
        desktop = QApplication.primaryScreen().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)

    def initSplashScreen(self):
        self.splashScreen = CustomSplashScreen(self.windowIcon(), self, enableShadow=False)
        self.splashScreen.raise_()
        self.show()

    def initNavigation(self):
        self.homePage = HomePage(self)
        self.settingPage = SettingPage(self)
        self.broadcastEditPage = BroadcastEditPage(self)
        self.broadcastEditPage.setObjectName("BroadcastEditPage")
        
        # 依次添加页面到主窗口系统
        self.addSubInterface(self.homePage, FIF.HOME, "主页")
        self.addSubInterface(self.settingPage, FIF.SETTING, "设置", position=NavigationItemPosition.BOTTOM)
        
        # 将投送页隐式添加到页面栈中 (自带正确的进入动画)
        self.stackedWidget.addWidget(self.broadcastEditPage)
        
        # 拦截点击并跳转
        broadcast_card = self.homePage.cardsWidget.layout().itemAt(0).widget()
        broadcast_card.clicked.connect(self._navToBroadcast)
        self.broadcastEditPage.backSignal.connect(self._navToHome)

    def _navToBroadcast(self):
        # 【关键修复】使用原生切换接口播放正确的载入动画，并清除左侧选中状态
        self.switchTo(self.broadcastEditPage)
        self.navigationInterface.setCurrentItem(None)
        
    def _navToHome(self):
        self.switchTo(self.homePage)
        self.navigationInterface.setCurrentItem(self.homePage.objectName())

    def _toggleTheme(self, value):
        if value == 'Dark': setTheme(Theme.DARK)
        elif value == 'Light': setTheme(Theme.LIGHT)
        else: setTheme(Theme.AUTO)

    def _onExceptionCaught(self, message: str):
        InfoBar.error(
            title="软件可能遇到异常", content="请将本地报错日志发送给开发者。",
            orient=Qt.Orientation.Horizontal, isClosable=True,
            duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self
        )

    def checkForUpdates(self, manual: bool = False):
        if manual: InfoBar.info("检查更新", "正在检查更新...", duration=1500, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self.worker = UpdateWorker()
        self.thread = threading.Thread(target=self.worker.run, args=(manual,))
        self.worker.finished.connect(lambda data, error: self._onUpdateChecked(data, error, manual))
        self.thread.start()

    def _onUpdateChecked(self, data, error, manual):
        if error:
            if manual: InfoBar.error("检查更新失败", "无法获取最新版本信息", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return

        version = data.get("latest_version", "未知")
        note = str(data.get("update_note", ""))
        if "\\u" in note:
            try: note = note.encode('utf-8').decode('unicode_escape')
            except: pass
        note = note.replace('\\n', '\n')
        note = re.sub(r'\n+', '\n\n', note)
            
        infoBar = InfoBar(
            icon=FIF.UPDATE, title=f"检测到新版本: v{version}",
            content="请及时下载更新以体验最新功能", orient=Qt.Orientation.Horizontal,
            isClosable=True, duration=-1, position=InfoBarPosition.BOTTOM_RIGHT, parent=self
        )
        infoBar.widgetLayout.addSpacing(10)
        downloadButton = PrimaryPushButton(FIF.DOWNLOAD, "下载更新")
        downloadButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://djcatpro.top/download.html")))
        infoBar.addWidget(downloadButton)
        detailButton = PushButton(FIF.DOCUMENT, "更新日志")
        detailButton.clicked.connect(lambda: self._showUpdateLog(version, note))
        infoBar.addWidget(detailButton)
        infoBar.show()

    def _showUpdateLog(self, version, note):
        w = UpdateDialog(version, note, self)
        if w.exec(): QDesktopServices.openUrl(QUrl("https://djcatpro.top/download.html"))

    def closeEvent(self, event):
        event.ignore()
        self.hide()
