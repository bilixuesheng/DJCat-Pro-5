import os
import sys
import threading
import re
import requests
from PySide6.QtCore import Qt, Signal, QObject, QUrl, QPropertyAnimation, QTimer, QDate, QTime
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtTextToSpeech import QTextToSpeech  # 新增 TTS 引擎
from qfluentwidgets import (MSFluentWindow, NavigationItemPosition, FluentIcon as FIF, 
                            setTheme, Theme, SplashScreen, InfoBar, InfoBarPosition, 
                            PrimaryPushButton, PushButton, MessageBoxBase, SubtitleLabel, 
                            TextEdit, setThemeColor)

from app.common.config import cfg, APP_NAME, UPDATE_API, VERSION
from app.common.signal_bus import signalBus
from app.view.home_page import HomePage
from app.view.setting_page import SettingPage
from app.view.broadcast_page import BroadcastEditPage
from app.view.components.tray import SystemTrayIcon
from app.view.schedule_page import SchedulePage

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
        self.setMinimumSize(700, 400)
        
        geometry = cfg.geometry.value
        if geometry.isEmpty() or geometry.width() <= 0:
            self.resize(800, 450)
            desktop = QApplication.primaryScreen().availableGeometry()
            w, h = desktop.width(), desktop.height()
            self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)
        else:
            self.resize(geometry.width(), geometry.height())
            self.move(geometry.x(), geometry.y())
            
        # === 音频播放器与循环控制 ===
        self.player = QMediaPlayer(self)
        self.audioOutput = QAudioOutput(self)
        self.audioOutput.setVolume(1.0)
        self.player.setAudioOutput(self.audioOutput)
        self.current_play_repeats = 0
        self.player.mediaStatusChanged.connect(self._onMediaStatusChanged)
        
        # === TTS 引擎 ===
        self.tts = QTextToSpeech(self)
        
        signalBus.testAudio.connect(self._playAudioTask)
        
        # 定时器：每秒触发一次检查
        self.scheduleTimer = QTimer(self)
        self.scheduleTimer.timeout.connect(self._checkSchedule)
        self.scheduleTimer.start(1000)
        self.last_triggered_time = ""

    def _playAudioTask(self, task_data):
        """ 执行真实的音频播放或 TTS 播报 """
        t = task_data["type"]
        repeat_count = task_data.get("repeat", 1)
        
        # 1. 拦截并处理 TTS (将文本根据 repeat_count 复制拼接，利用句号停顿)
        if "TTS" in t:
            content = task_data.get("content", "")
            if content:
                full_text = "。".join([content] * repeat_count)
                self.tts.say(full_text)
            return

        # 2. 处理本地/预设音频
        base_path = os.path.dirname(__file__) 
        path = ""
        if t == "预设: 12:30报时": path = os.path.join(base_path, "1230.mp3")
        elif t == "预设: 18:25报时": path = os.path.join(base_path, "1825.mp3")
        elif t == "预设: 上课铃": path = os.path.join(base_path, "class.mp3")
        elif t == "本地音频": path = task_data.get("file", "")
        
        if path and os.path.exists(path):
            self.current_play_repeats = repeat_count - 1 # 减去当前马上要播放的这一次
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()

    def _onMediaStatusChanged(self, status):
        """ 监听音频播放状态，实现真实的循环播放 """
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.current_play_repeats > 0:
                self.current_play_repeats -= 1
                self.player.setPosition(0) # 回到开头
                self.player.play()

    def _checkSchedule(self):
        """ 定时检测核心 """
        now_time = QTime.currentTime().toString("HH:mm:ss")
        if now_time == self.last_triggered_time:
            return 
            
        today_week = QDate.currentDate().dayOfWeek() - 1 
        
        for task in cfg.broadcastTasks.value:
            if not task.get("enabled", False): continue
            
            # 由于 TimePicker 强制存为 HH:mm:00，所以任务永远会在秒数为00时精准触发
            if today_week in task["weeks"] and task["time"] == now_time:
                self.last_triggered_time = now_time
                self._playAudioTask(task)
                break 

    def initSplashScreen(self):
        self.splashScreen = CustomSplashScreen(self.windowIcon(), self, enableShadow=False)
        self.splashScreen.raise_()
        
        # === 核心：像 GD 一样拦截静默启动 ===
        is_silently = "--silence" in sys.argv
        if not is_silently:
            # 只有手动点击打开时，才显示主窗口
            self.show()
        else:
            # 如果是自启，直接把闪屏动画结束掉，不调用 self.show()
            self.splashScreen.finish()

    def initNavigation(self):
        self.homePage = HomePage(self)
        self.settingPage = SettingPage(self)
        self.broadcastEditPage = BroadcastEditPage(self)
        self.broadcastEditPage.setObjectName("BroadcastEditPage")
        
        self.schedulePage = SchedulePage(self)
        self.schedulePage.setObjectName("SchedulePage")
        
        self.addSubInterface(self.homePage, FIF.HOME, "主页")
        self.addSubInterface(self.settingPage, FIF.SETTING, "设置", position=NavigationItemPosition.BOTTOM)
        
        self.stackedWidget.addWidget(self.broadcastEditPage)
        self.stackedWidget.addWidget(self.schedulePage)
        
        if "全屏投送" in self.homePage.all_cards:
            self.homePage.all_cards["全屏投送"].clicked.connect(self._navToBroadcast)
        if "定时播报" in self.homePage.all_cards:
            self.homePage.all_cards["定时播报"].clicked.connect(self._navToSchedule)
        
        self.broadcastEditPage.backSignal.connect(self._navToHome)
        self.schedulePage.backSignal.connect(self._navToHome) 

    def _navToBroadcast(self):
        self.switchTo(self.broadcastEditPage)
        self.navigationInterface.setCurrentItem(None)
        
    def _navToSchedule(self):
        self.switchTo(self.schedulePage)
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

        latest_version = data.get("latest_version", "未知")
        
        if latest_version == VERSION:
            if manual: 
                InfoBar.success("已是最新版本", f"当前运行的 v{VERSION} 已经是最新版本啦", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return

        note = str(data.get("update_note", ""))
        if "\\u" in note:
            try: note = note.encode('utf-8').decode('unicode_escape')
            except: pass
        note = note.replace('\\n', '\n')
        note = re.sub(r'\n+', '\n\n', note)
            
        infoBar = InfoBar(
            icon=FIF.UPDATE, title=f"检测到新版本: v{latest_version}",
            content="请及时下载更新以体验最新功能", orient=Qt.Orientation.Horizontal,
            isClosable=True, duration=-1, position=InfoBarPosition.BOTTOM_RIGHT, parent=self
        )
        infoBar.widgetLayout.addSpacing(10)
        downloadButton = PrimaryPushButton(FIF.DOWNLOAD, "下载更新")
        downloadButton.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOWNLOAD_URL)))
        infoBar.addWidget(downloadButton)
        detailButton = PushButton(FIF.DOCUMENT, "更新日志")
        detailButton.clicked.connect(lambda: self._showUpdateLog(latest_version, note))
        infoBar.addWidget(detailButton)
        infoBar.show()

    def _showUpdateLog(self, version, note):
        w = UpdateDialog(version, note, self)
        if w.exec(): QDesktopServices.openUrl(QUrl(DOWNLOAD_URL))

    def closeEvent(self, event):
        cfg.set(cfg.geometry, self.geometry())
        event.ignore()
        self.hide()

#DOWNLOAD_URL = "https://djcatpro.top/download.html"
DOWNLOAD_URL = "https://pan.xueshg.top/s/AMCo" # beta版更新链接