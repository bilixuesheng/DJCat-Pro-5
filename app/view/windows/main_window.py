import re
import threading
from pathlib import Path

import requests
from PySide6.QtCore import (
    QDate,
    QObject,
    QPropertyAnimation,
    QProcess,
    Qt,
    QTime,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtTextToSpeech import QTextToSpeech
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    DrillInTransitionStackedWidget,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    MSFluentWindow,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SplashScreen,
    SubtitleLabel,
    TextEdit,
    Theme,
    setTheme,
    setThemeColor,
)

from app.config.cfg import cfg
from app.config.constants import (
    APP_NAME,
    DOWNLOAD_URL,
    UPDATE_API,
    VERSION,
)
from app.config.paths import ASSET_DIR
from app.signal_bus import signalBus
from app.view.pages.broadcast_page import BroadcastEditPage
from app.view.pages.countdown_page import CountdownEditPage
from app.view.pages.credits_page import CreditsPage
from app.view.pages.home_page import HomePage
from app.view.pages.schedule_page import SchedulePage
from app.view.pages.setting_page import SettingPage
from app.view.pages.shutdown_page import (
    SHUTDOWN_RESULT,
    WAIT_RESULT,
    ShutdownPage,
    show_shutdown_prompt,
)
from app.view.shell.tray import SystemTrayIcon


class CustomSplashScreen(SplashScreen):
    def finish(self):
        opacityEffect = QGraphicsOpacityEffect(self)
        opacityEffect.setOpacity(1)
        self.setGraphicsEffect(opacityEffect)
        opacityAnimation = QPropertyAnimation(opacityEffect, b"opacity", self)
        opacityAnimation.setStartValue(1)
        opacityAnimation.setEndValue(0)
        opacityAnimation.setDuration(200)
        opacityAnimation.finished.connect(self.deleteLater)
        opacityAnimation.start()


class UpdateWorker(QObject):
    finished = Signal(dict, str)

    def run(self):
        try:
            response = requests.get(UPDATE_API, timeout=5)
            response.raise_for_status()
            data = response.json()
            self.finished.emit(data, "")
        except (requests.RequestException, ValueError) as error:
            self.finished.emit({}, str(error))


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
    def __init__(self, isSilent: bool = False):
        self.searchEdit = None
        super().__init__(parent=None)
        self.splashScreen = None

        # MSFluentWindow 固定使用弹出式页面栈，快照过渡可避免目标页在动画前闪现。
        oldView = self.stackedWidget.view
        self.stackedWidget.view = DrillInTransitionStackedWidget(self.stackedWidget)
        self.stackedWidget.hBoxLayout.replaceWidget(oldView, self.stackedWidget.view)
        self.stackedWidget.view.currentChanged.connect(self.stackedWidget.currentChanged)
        oldView.hide()
        oldView.deleteLater()

        setThemeColor(cfg.customThemeColor.value)
        self._toggleTheme(cfg.customThemeMode.value)
        cfg.customThemeMode.valueChanged.connect(self._toggleTheme)

        self.initWindow()
        if not isSilent:
            self.initSplashScreen()
            QApplication.processEvents()

        self.initNavigation()
        self.tray = SystemTrayIcon(self)
        self.tray.show()

        signalBus.catchException.connect(self._onExceptionCaught)
        if self.splashScreen:
            self.splashScreen.finish()

        if cfg.checkUpdateAtStartUp.value:
            self.checkForUpdates(manual=False)

    def initWindow(self):
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(ASSET_DIR / "logo.png")))
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

        self.player = QMediaPlayer(self)
        self.audioOutput = QAudioOutput(self)
        self.player.setAudioOutput(self.audioOutput)
        self.current_play_repeats = 0
        self.player.mediaStatusChanged.connect(self._onMediaStatusChanged)

        self.tts = QTextToSpeech(self)
        self._setBroadcastVolume(100)

        signalBus.testAudio.connect(self._playAudioTask)

        self.scheduleTimer = QTimer(self)
        self.scheduleTimer.timeout.connect(self._checkSchedule)
        self.scheduleTimer.start(1000)
        self.last_triggered_time = ""
        self.last_shutdown_triggered_time = ""

    def initSplashScreen(self):
        self.splashScreen = CustomSplashScreen(
            self.windowIcon(),
            self,
            enableShadow=False,
        )
        self.splashScreen.raise_()
        self.show()

    def _setBroadcastVolume(self, volume):
        volume /= 100
        self.audioOutput.setVolume(volume)
        self.tts.setVolume(volume)

    def _playAudioTask(self, task_data):
        self._setBroadcastVolume(task_data.get("volume", 100))
        t = task_data["type"]
        repeat_count = task_data.get("repeat", 1)

        if "TTS" in t:
            content = task_data.get("content", "")
            if content:
                full_text = "。".join([content] * repeat_count)
                self.tts.say(full_text)
            return

        presetFiles = {
            "预设: 12:30报时": "1230.mp3",
            "预设: 18:25报时": "1825.mp3",
            "预设: 上课铃": "class.mp3",
        }
        path = (
            str(ASSET_DIR / presetFiles[t])
            if t in presetFiles
            else task_data.get("file", "")
        )

        if path and Path(path).exists():
            self.current_play_repeats = repeat_count - 1
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()

    def _onMediaStatusChanged(self, status):
        if (
            status == QMediaPlayer.MediaStatus.EndOfMedia
            and self.current_play_repeats > 0
        ):
            self.current_play_repeats -= 1
            self.player.setPosition(0)
            self.player.play()

    def _checkSchedule(self):
        now_time = QTime.currentTime().toString("HH:mm:ss")
        today_week = QDate.currentDate().dayOfWeek() - 1

        if now_time != self.last_triggered_time:
            task = self._scheduledTask(
                cfg.broadcastTasks.value,
                now_time,
                today_week,
            )
            if task:
                self.last_triggered_time = now_time
                self._playAudioTask(task)

        if now_time != self.last_shutdown_triggered_time:
            task = self._scheduledTask(
                cfg.shutdownTasks.value,
                now_time,
                today_week,
            )
            if task:
                self.last_shutdown_triggered_time = now_time
                self._handleShutdownTask(task)

    @staticmethod
    def _scheduledTask(tasks, now_time, today_week):
        return next(
            (
                task
                for task in tasks
                if task.get("enabled", False)
                and today_week in task.get("weeks", [])
                and task.get("time") == now_time
            ),
            None,
        )

    def _handleShutdownTask(self, task):
        if not task.get("notify", True):
            self._shutdownNow()
            return

        result = show_shutdown_prompt(task)
        if result == SHUTDOWN_RESULT:
            self._shutdownNow()
        elif result == WAIT_RESULT:
            QTimer.singleShot(
                60_000,
                lambda: self._handleShutdownTask(task),
            )

    @staticmethod
    def _shutdownNow():
        QProcess.startDetached("shutdown.exe", ["/s", "/t", "0"])

    def initNavigation(self):
        self.homePage = HomePage(self)
        self.creditsPage = CreditsPage(self)
        self.settingPage = SettingPage(self)
        self.searchEdit = SearchLineEdit(self.titleBar)
        self.searchEdit.setClearButtonEnabled(True)
        self.searchEdit.setPlaceholderText("搜索设置")
        self.searchEdit.hide()
        self.searchEdit.raise_()
        self.searchEdit.textChanged.connect(self.settingPage.setSearchText)
        self.stackedWidget.currentChanged.connect(self._updateSearchEdit)
        self.broadcastEditPage = BroadcastEditPage(self)
        self.broadcastEditPage.setObjectName("BroadcastEditPage")
        self.countdownPage = CountdownEditPage(self)
        self.countdownPage.setObjectName("CountdownPage")

        self.schedulePage = SchedulePage(self)
        self.schedulePage.setObjectName("SchedulePage")
        self.shutdownPage = ShutdownPage(self)
        self.shutdownPage.setObjectName("ShutdownPage")

        self.addSubInterface(self.homePage, FIF.HOME, "主页")
        self.addSubInterface(
            self.creditsPage,
            FIF.HEART,
            "特别鸣谢",
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settingPage,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

        self.stackedWidget.addWidget(self.broadcastEditPage)
        self.stackedWidget.addWidget(self.countdownPage)
        self.stackedWidget.addWidget(self.schedulePage)
        self.stackedWidget.addWidget(self.shutdownPage)

        if "全屏投送" in self.homePage.all_cards:
            self.homePage.all_cards["全屏投送"].clicked.connect(self._navToBroadcast)
        if "考试倒计时" in self.homePage.all_cards:
            self.homePage.all_cards["考试倒计时"].clicked.connect(self._navToCountdown)
        if "定时播报" in self.homePage.all_cards:
            self.homePage.all_cards["定时播报"].clicked.connect(self._navToSchedule)
        if "定时关机" in self.homePage.all_cards:
            self.homePage.all_cards["定时关机"].clicked.connect(self._navToShutdown)

        self.broadcastEditPage.backSignal.connect(self._navToHome)
        self.countdownPage.backSignal.connect(self._navToHome)
        self.schedulePage.backSignal.connect(self._navToHome)
        self.shutdownPage.backSignal.connect(self._navToHome)
        self._updateSearchEdit()

    def _updateSearchEdit(self, *args):
        isSettingPage = self.stackedWidget.currentWidget() is self.settingPage
        if not isSettingPage:
            self.searchEdit.clear()
        self.searchEdit.setVisible(isSettingPage)
        if isSettingPage:
            self._refreshSearchEditGeometry()

    def _refreshSearchEditGeometry(self):
        width = max(200, min(360, self.titleBar.width() - 300))
        self.searchEdit.setFixedWidth(width)
        self.searchEdit.move(
            (self.titleBar.width() - width) // 2,
            (self.titleBar.height() - self.searchEdit.height()) // 2,
        )

    def _navToBroadcast(self):
        self.switchTo(self.broadcastEditPage)
        self.navigationInterface.setCurrentItem(None)

    def _navToCountdown(self):
        self.switchTo(self.countdownPage)
        self.navigationInterface.setCurrentItem(None)

    def _navToSchedule(self):
        self.switchTo(self.schedulePage)
        self.navigationInterface.setCurrentItem(None)

    def _navToShutdown(self):
        self.switchTo(self.shutdownPage)
        self.navigationInterface.setCurrentItem(None)

    def _navToHome(self):
        self.stackedWidget.view.setCurrentWidget(self.homePage, isBack=True)
        self.navigationInterface.setCurrentItem(self.homePage.objectName())

    def _toggleTheme(self, value):
        if value == "Dark":
            setTheme(Theme.DARK)
        elif value == "Light":
            setTheme(Theme.LIGHT)
        else:
            setTheme(Theme.AUTO)

    def _onExceptionCaught(self, message: str):
        InfoBar.error(
            title="软件可能遇到异常",
            content="请将本地报错日志发送给开发者。",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            duration=5000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self,
        )

    def checkForUpdates(self, manual: bool = False):
        if manual:
            InfoBar.info(
                "检查更新",
                "正在检查更新...",
                duration=1500,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
        self.worker = UpdateWorker()
        self.thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker.finished.connect(
            lambda data, error: self._onUpdateChecked(data, error, manual)
        )
        self.thread.start()

    def _onUpdateChecked(self, data, error, manual):
        if error:
            if manual:
                InfoBar.error(
                    "检查更新失败",
                    "无法获取最新版本信息",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self,
                )
            return

        latest_version = data.get("latest_version", "未知")

        if latest_version == VERSION:
            if manual:
                InfoBar.success(
                    "已是最新版本",
                    f"当前运行的 v{VERSION} 已经是最新版本啦",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self,
                )
            return

        note = str(data.get("update_note", ""))
        if "\\u" in note:
            try:
                note = note.encode("utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                pass
        note = note.replace("\\n", "\n")
        note = re.sub(r"\n+", "\n\n", note)

        infoBar = InfoBar(
            icon=FIF.UPDATE,
            title=f"检测到新版本: v{latest_version}",
            content="请及时下载更新以体验最新功能",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            duration=-1,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self,
        )
        infoBar.widgetLayout.addSpacing(10)
        downloadButton = PrimaryPushButton(FIF.DOWNLOAD, "下载更新")
        downloadButton.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(DOWNLOAD_URL))
        )
        infoBar.addWidget(downloadButton)
        detailButton = PushButton(FIF.DOCUMENT, "更新日志")
        detailButton.clicked.connect(lambda: self._showUpdateLog(latest_version, note))
        infoBar.addWidget(detailButton)
        infoBar.show()

    def _showUpdateLog(self, version, note):
        w = UpdateDialog(version, note, self)
        if w.exec():
            QDesktopServices.openUrl(QUrl(DOWNLOAD_URL))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.searchEdit is not None and self.searchEdit.isVisible():
            self._refreshSearchEditGeometry()

    def closeEvent(self, event):
        cfg.set(cfg.geometry, self.geometry())
        event.ignore()
        self.hide()
