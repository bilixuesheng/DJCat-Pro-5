import re
import threading
import time
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
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtTextToSpeech import QTextToSpeech
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget
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
    StateToolTip,
    SubtitleLabel,
    TextEdit,
    Theme,
    setTheme,
    setThemeColor,
)

from app.common.ai_markdown import registerMachine
from app.common.edge_tts import DEFAULT_EDGE_VOICE, EdgeSpeechWorker
from app.common.update_download import UpdateDownloadWorker, clearUpdateDirectory
from app.config.cfg import cfg
from app.config.constants import (
    APP_NAME,
    DOWNLOAD_URL,
    UPDATE_API,
    VERSION,
)
from app.config.paths import ASSET_DIR, UPDATE_INSTALLER_PATH
from app.platform.memory import emptyWorkingSet
from app.signal_bus import signalBus
from app.view.pages.credits_page import CreditsPage
from app.view.pages.home_page import HomePage
from app.view.pages.setting_page import SettingPage
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
    finished = Signal(int, dict, str)

    RETRY_COUNT = 3

    def __init__(self, requestId):
        super().__init__()
        self.requestId = requestId

    def run(self):
        for retry in range(self.RETRY_COUNT + 1):
            try:
                response = requests.get(UPDATE_API, timeout=5)
                response.raise_for_status()
                data = response.json()
                self.finished.emit(self.requestId, data, "")
                return
            except (requests.RequestException, ValueError) as error:
                if retry == self.RETRY_COUNT:
                    self.finished.emit(self.requestId, {}, str(error))
                    return
                time.sleep(1)


class MachineRegistrationWorker(QObject):
    finished = Signal(str)

    def run(self):
        self.finished.emit(registerMachine() or "")


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
        self._geometryApplied = False
        super().__init__(parent=None)
        self.splashScreen = None
        self._updateInfoBar = None
        self._updateCheckInfoBar = None
        self._downloadStateToolTip = None
        self._downloadWorker = None
        self._downloadThread = None
        self._downloadVersion = ""
        self._quitAfterDownload = False
        self._navigationTarget = None
        self._pendingNavigation = None
        self._updateRequestId = 0
        self._updateJobs = {}
        self._resourcesShutdown = False
        self.machineRegistrationWorker = None
        self.machineRegistrationThread = None

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
        cfg.windowTitle.valueChanged.connect(self._updateWindowTitle)

        self.initWindow()
        if not isSilent:
            self.initSplashScreen()
            QApplication.processEvents()

        self.initNavigation()
        self._startMachineRegistration()
        self.tray = SystemTrayIcon(self)
        self.tray.show()

        signalBus.catchException.connect(self._onExceptionCaught)
        if self.splashScreen:
            splashScreen = self.splashScreen
            self.splashScreen = None
            splashScreen.finish()

        if cfg.checkUpdateAtStartUp.value:
            self.checkForUpdates(manual=False)

    def _startMachineRegistration(self):
        if cfg.aiMarkdownMachineCode.value:
            return
        self.machineRegistrationWorker = MachineRegistrationWorker()
        self.machineRegistrationWorker.finished.connect(self._onMachineRegistered)
        self.machineRegistrationThread = threading.Thread(
            target=self.machineRegistrationWorker.run,
            daemon=True,
        )
        self.machineRegistrationThread.start()

    def _onMachineRegistered(self, machineCode):
        worker = self.machineRegistrationWorker
        self.machineRegistrationWorker = None
        self.machineRegistrationThread = None
        if worker is not None:
            worker.deleteLater()
        if machineCode and not self._resourcesShutdown:
            cfg.set(cfg.aiMarkdownMachineCode, machineCode)

    def initWindow(self):
        self._updateWindowTitle(cfg.windowTitle.value)
        self.setWindowIcon(QIcon(str(ASSET_DIR / "logo.png")))
        self.setMinimumSize(700, 400)

        self.player = QMediaPlayer(self)
        self.audioOutput = QAudioOutput(self)
        self.player.setAudioOutput(self.audioOutput)
        self.current_play_repeats = 0
        self.player.mediaStatusChanged.connect(self._onMediaStatusChanged)
        self._edge_tts_request_id = 0
        self._edge_tts_jobs = {}
        self._edge_tts_temp_path = ""

        self.tts = QTextToSpeech(self)
        self._setBroadcastVolume(100)

        signalBus.testAudio.connect(self._playAudioTask)

        self.scheduleTimer = QTimer(self)
        self.scheduleTimer.timeout.connect(self._checkSchedule)
        self.scheduleTimer.start(1000)
        self.last_triggered_time = ""
        self.last_shutdown_triggered_time = ""

    def _updateWindowTitle(self, title):
        self.setWindowTitle(title.strip() or APP_NAME)

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
        if self._resourcesShutdown:
            return

        volume = task_data.get("volume", 100)
        self._setBroadcastVolume(volume)
        t = task_data["type"]
        repeat_count = task_data.get("repeat", 1)

        if t == "Edge TTS（需要联网）":
            content = task_data.get("content", "").strip()
            if content:
                self._startEdgeTts(
                    content,
                    task_data.get("voice", DEFAULT_EDGE_VOICE),
                    repeat_count,
                    volume,
                )
            else:
                self._invalidatePendingEdgeTts()
            return

        self._invalidatePendingEdgeTts()
        self._cleanupEdgeTtsFile()

        if t == "系统TTS":
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

    def _startEdgeTts(self, content, voice, repeat_count, volume):
        self._edge_tts_request_id += 1
        request_id = self._edge_tts_request_id
        worker = EdgeSpeechWorker(request_id, content, voice)
        thread = threading.Thread(target=worker.run, daemon=True)
        self._edge_tts_jobs[request_id] = (
            worker,
            thread,
            repeat_count,
            volume,
        )
        worker.finished.connect(self._onEdgeTtsReady)
        thread.start()

    def _onEdgeTtsReady(self, request_id, path, error):
        job = self._edge_tts_jobs.pop(request_id, None)
        if job:
            job[0].deleteLater()
        if request_id != self._edge_tts_request_id:
            if path:
                self._removeTempFile(path)
            return

        if error or not path or not job:
            if path:
                self._removeTempFile(path)
            InfoBar.error(
                title="Edge TTS 播报失败",
                content="请检查网络连接后重试。",
                duration=5000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
            return

        _, _, repeat_count, volume = job
        self._setBroadcastVolume(volume)
        self._cleanupEdgeTtsFile()
        self._edge_tts_temp_path = path
        self.current_play_repeats = repeat_count - 1
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def _invalidatePendingEdgeTts(self):
        self._edge_tts_request_id += 1

    def _cancelPendingEdgeTts(self):
        self._invalidatePendingEdgeTts()
        for worker, *_ in self._edge_tts_jobs.values():
            worker.cancel()

    def _cleanupEdgeTtsFile(self):
        if not self._edge_tts_temp_path:
            return

        path = self._edge_tts_temp_path
        self._edge_tts_temp_path = ""
        if self.player.source().toLocalFile() == path:
            self.player.setSource(QUrl())
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            QTimer.singleShot(1000, self, lambda: self._removeTempFile(path))

    @staticmethod
    def _removeTempFile(path):
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass

    def _onMediaStatusChanged(self, status):
        if (
            status == QMediaPlayer.MediaStatus.EndOfMedia
            and self.current_play_repeats > 0
        ):
            self.current_play_repeats -= 1
            self.player.setPosition(0)
            self.player.play()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            QTimer.singleShot(0, self, self._cleanupEdgeTtsFile)

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
        if self._resourcesShutdown:
            return

        if not task.get("notify", True):
            self._shutdownNow()
            return

        from app.view.pages.shutdown_page import (
            SHUTDOWN_RESULT,
            WAIT_RESULT,
            show_shutdown_prompt,
        )

        result = show_shutdown_prompt(task)
        if result == SHUTDOWN_RESULT:
            self._shutdownNow()
        elif result == WAIT_RESULT:
            QTimer.singleShot(
                60_000,
                self,
                lambda: self._handleShutdownTask(task),
            )

    @staticmethod
    def _shutdownNow():
        QProcess.startDetached("shutdown.exe", ["/s", "/t", "0"])

    def initNavigation(self):
        self.homePage = HomePage(self)
        self.creditsPage = CreditsPage(self)
        self.settingPage = SettingPage(self)
        self.broadcastEditPage = None
        self.countdownPage = None
        self.schedulePage = None
        self.shutdownPage = None
        self.searchEdit = SearchLineEdit(self.titleBar)
        self.searchEdit.setClearButtonEnabled(True)
        self.searchEdit.setPlaceholderText("搜索设置")
        self.searchEdit.hide()
        self.searchEdit.raise_()
        self.searchEdit.textChanged.connect(self.settingPage.setSearchText)
        self.stackedWidget.currentChanged.connect(self._updateSearchEdit)
        self.stackedWidget.currentChanged.connect(self._onNavigationCompleted)
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

        if "全屏投送" in self.homePage.all_cards:
            self.homePage.all_cards["全屏投送"].clicked.connect(self._navToBroadcast)
        if "考试倒计时" in self.homePage.all_cards:
            self.homePage.all_cards["考试倒计时"].clicked.connect(self._navToCountdown)
        if "定时播报" in self.homePage.all_cards:
            self.homePage.all_cards["定时播报"].clicked.connect(self._navToSchedule)
        if "定时关机" in self.homePage.all_cards:
            self.homePage.all_cards["定时关机"].clicked.connect(self._navToShutdown)

        self._updateSearchEdit()

    def _getTaskPage(self, attribute, pageClass, objectName):
        page = getattr(self, attribute)
        if page is not None:
            return page, False

        page = pageClass(self)
        page.setObjectName(objectName)
        page.backSignal.connect(self._navToHome)
        self.stackedWidget.addWidget(page)
        setattr(self, attribute, page)
        return page, True

    def _getBroadcastEditPage(self):
        from app.view.pages.broadcast_page import BroadcastEditPage

        page, created = self._getTaskPage(
            "broadcastEditPage",
            BroadcastEditPage,
            "BroadcastEditPage",
        )
        if created:
            page.editSignal.connect(self._navToBroadcast)
        return page

    def _getCountdownPage(self):
        from app.view.pages.countdown_page import CountdownEditPage

        page, _ = self._getTaskPage(
            "countdownPage",
            CountdownEditPage,
            "CountdownPage",
        )
        return page

    def _getSchedulePage(self):
        from app.view.pages.schedule_page import SchedulePage

        page, _ = self._getTaskPage(
            "schedulePage",
            SchedulePage,
            "SchedulePage",
        )
        return page

    def _getShutdownPage(self):
        from app.view.pages.shutdown_page import ShutdownPage

        page, _ = self._getTaskPage(
            "shutdownPage",
            ShutdownPage,
            "ShutdownPage",
        )
        return page

    def _updateSearchEdit(self, *args):
        pendingTarget = (
            self._pendingNavigation[0]
            if self._pendingNavigation is not None
            else self._navigationTarget
        )
        interface = pendingTarget or self.stackedWidget.currentWidget()
        isSettingPage = interface is self.settingPage
        self._setSearchEditVisible(isSettingPage)

    def _onNavigationCompleted(self, *args):
        if self.stackedWidget.currentWidget() is not self._navigationTarget:
            return

        self._navigationTarget = None
        pending = self._pendingNavigation
        self._pendingNavigation = None
        if pending is not None:
            QTimer.singleShot(0, self, lambda: self._navigateTo(*pending))

    def _setSearchEditVisible(self, isSettingPage: bool) -> None:
        if not isSettingPage:
            self.searchEdit.clear()
        self.searchEdit.setVisible(isSettingPage)
        if isSettingPage:
            self._refreshSearchEditGeometry()

    def switchTo(self, interface: QWidget) -> None:
        self._navigateTo(interface)

    def _navigateTo(self, interface: QWidget, isBack: bool = False) -> None:
        # currentWidget changes only when the snapshot animation finishes.
        # Queue one latest destination so a second click cannot stop and rebuild
        # the in-flight snapshots in an inconsistent state.
        if self._resourcesShutdown:
            return
        self._setSearchEditVisible(interface is self.settingPage)
        if interface is self._navigationTarget:
            self._pendingNavigation = None
            return
        if self._navigationTarget is not None:
            self._pendingNavigation = (interface, isBack)
            return
        if interface is self.stackedWidget.currentWidget():
            return

        self._navigationTarget = interface
        if isBack:
            self.stackedWidget.view.setCurrentWidget(interface, isBack=True)
        else:
            super().switchTo(interface)

    def _refreshSearchEditGeometry(self):
        width = max(200, min(360, self.titleBar.width() - 300))
        self.searchEdit.setFixedWidth(width)
        self.searchEdit.move(
            (self.titleBar.width() - width) // 2,
            (self.titleBar.height() - self.searchEdit.height()) // 2,
        )

    def _navToBroadcast(self):
        self.switchTo(self._getBroadcastEditPage())
        self.navigationInterface.setCurrentItem(None)

    def _navToCountdown(self):
        self.switchTo(self._getCountdownPage())
        self.navigationInterface.setCurrentItem(None)

    def _navToSchedule(self):
        self.switchTo(self._getSchedulePage())
        self.navigationInterface.setCurrentItem(None)

    def _navToShutdown(self):
        self.switchTo(self._getShutdownPage())
        self.navigationInterface.setCurrentItem(None)

    def _navToHome(self):
        self._navigateTo(self.homePage, isBack=True)
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
        if self._resourcesShutdown:
            return
        if manual:
            self._closeUpdateCheckInfoBar()
            infoBar = InfoBar.info(
                "检查更新",
                "正在检查更新...",
                isClosable=False,
                duration=-1,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
            self._updateCheckInfoBar = infoBar
            infoBar.destroyed.connect(self._clearUpdateCheckInfoBar)
        self._updateRequestId += 1
        requestId = self._updateRequestId
        worker = UpdateWorker(requestId)
        thread = threading.Thread(target=worker.run, daemon=True)
        self._updateJobs[requestId] = (worker, thread, manual)
        worker.finished.connect(self._onUpdateCheckFinished)
        thread.start()

    def _onUpdateCheckFinished(self, requestId, data, error):
        job = self._updateJobs.pop(requestId, None)
        if job is None:
            return

        worker, _, manual = job
        worker.deleteLater()
        if requestId != self._updateRequestId or self._resourcesShutdown:
            return
        if manual:
            self._closeUpdateCheckInfoBar()
        self._onUpdateChecked(data, error, manual)

    def _closeUpdateCheckInfoBar(self):
        infoBar = self._updateCheckInfoBar
        if infoBar is None:
            return
        self._updateCheckInfoBar = None
        infoBar.close()

    def _clearUpdateCheckInfoBar(self, infoBar=None):
        if infoBar is None or self._updateCheckInfoBar is infoBar:
            self._updateCheckInfoBar = None

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

        if self._updateInfoBar is not None:
            self._updateInfoBar.close()

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
            lambda: self._startUpdateDownload(latest_version)
        )
        infoBar.addWidget(downloadButton)
        detailButton = PushButton(FIF.DOCUMENT, "更新日志")
        detailButton.clicked.connect(lambda: self._showUpdateLog(latest_version, note))
        infoBar.addWidget(detailButton)
        self._updateInfoBar = infoBar
        infoBar.destroyed.connect(self._clearUpdateInfoBar)
        infoBar.show()

    def _clearUpdateInfoBar(self, infoBar):
        if self._updateInfoBar is infoBar:
            self._updateInfoBar = None

    def _showUpdateLog(self, version, note):
        w = UpdateDialog(version, note, self)
        try:
            if w.exec():
                self._startUpdateDownload(version)
        finally:
            w.deleteLater()

    def _startUpdateDownload(self, version):
        if self._downloadWorker is not None:
            return

        if self._updateInfoBar is not None:
            self._updateInfoBar.close()
            self._updateInfoBar = None

        self._downloadVersion = str(version)
        self._quitAfterDownload = False
        toolTip = StateToolTip(
            "正在下载更新",
            "正在连接下载服务器...",
            self,
        )
        self._downloadStateToolTip = toolTip
        toolTip.move(toolTip.getSuitablePos())
        toolTip.show()
        toolTip.closedSignal.connect(self._onDownloadStateToolTipClosed)
        toolTip.destroyed.connect(
            lambda: self._clearDownloadStateToolTip(toolTip)
        )

        self._downloadWorker = UpdateDownloadWorker(
            DOWNLOAD_URL,
            UPDATE_INSTALLER_PATH,
        )
        self._downloadWorker.progressChanged.connect(
            self._onUpdateDownloadProgress
        )
        self._downloadWorker.retrying.connect(self._onUpdateDownloadRetrying)
        self._downloadWorker.finished.connect(self._onUpdateDownloadFinished)
        self._downloadThread = threading.Thread(
            target=self._downloadWorker.run,
            daemon=True,
        )
        self._downloadThread.start()

    def _onUpdateDownloadProgress(self, downloaded, total, speed, threads):
        if self._downloadStateToolTip is None:
            return

        downloadedText = self._formatDownloadSize(downloaded)
        if total > 0:
            percent = min(100, int(downloaded * 100 / total))
            totalText = self._formatDownloadSize(total)
            progressText = f"{percent}% · {downloadedText} / {totalText}"
        else:
            progressText = f"已下载 {downloadedText}"
        speedText = self._formatDownloadSize(speed)
        content = f"{progressText} · {speedText}/s · {threads} 线程"
        self._downloadStateToolTip.setContent(content)
        contentWidth = self._downloadStateToolTip.contentLabel.sizeHint().width()
        titleWidth = self._downloadStateToolTip.titleLabel.sizeHint().width()
        self._downloadStateToolTip.setFixedWidth(
            max(256, contentWidth + 56, titleWidth + 56)
        )
        self._downloadStateToolTip.closeButton.move(
            self._downloadStateToolTip.width() - 24,
            19,
        )
        self._downloadStateToolTip.move(
            self.width() - self._downloadStateToolTip.width() - 24,
            self._downloadStateToolTip.y(),
        )

    def _onUpdateDownloadRetrying(self, retry, retryCount, _error):
        if self._downloadStateToolTip is not None:
            self._downloadStateToolTip.setContent(
                f"下载失败，正在重试 {retry}/{retryCount}..."
            )

    def _onDownloadStateToolTipClosed(self):
        toolTip = self._downloadStateToolTip
        if toolTip is not None:
            self._downloadStateToolTip = None
            toolTip.deleteLater()

    def _clearDownloadStateToolTip(self, toolTip=None):
        if toolTip is None or self._downloadStateToolTip is toolTip:
            self._downloadStateToolTip = None

    def _disposeDownloadStateToolTip(self):
        toolTip = self._downloadStateToolTip
        if toolTip is None:
            return
        self._downloadStateToolTip = None
        toolTip.hide()
        toolTip.deleteLater()

    @staticmethod
    def _formatDownloadSize(size):
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                if unit == "B":
                    return f"{value:.0f} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def _onUpdateDownloadFinished(self, installerPath, error, canceled):
        worker = self._downloadWorker
        self._downloadWorker = None
        self._downloadThread = None
        if worker is not None:
            worker.deleteLater()

        if self._quitAfterDownload:
            self._quitAfterDownload = False
            clearUpdateDirectory()
            QApplication.quit()
            return

        if canceled:
            self._disposeDownloadStateToolTip()
            return

        self._restoreForUpdateMessage()

        if error:
            self._disposeDownloadStateToolTip()
            InfoBar.error(
                "更新下载失败",
                error,
                duration=5000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
            return

        if self._downloadStateToolTip is not None:
            self._downloadStateToolTip.setContent("安装程序下载完成")
            self._downloadStateToolTip.setState(True)

        self._showInstallUpdateInfoBar(Path(installerPath))

    def _restoreForUpdateMessage(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _showInstallUpdateInfoBar(self, installerPath):
        infoBar = InfoBar(
            icon=FIF.UPDATE,
            title=f"v{self._downloadVersion} 下载完成",
            content="是否立即安装更新？",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            duration=-1,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self,
        )
        infoBar.widgetLayout.addSpacing(10)

        installButton = PrimaryPushButton(FIF.UPDATE, "立即更新")
        installButton.clicked.connect(
            lambda: self._launchUpdateInstaller(installerPath, infoBar)
        )
        infoBar.addWidget(installButton)

        laterButton = PushButton("稍后更新")
        laterButton.clicked.connect(infoBar.close)
        infoBar.addWidget(laterButton)
        infoBar.show()

    def _launchUpdateInstaller(self, installerPath, infoBar):
        if not installerPath.is_file():
            InfoBar.error(
                "无法安装更新",
                "安装程序已不存在，请重新下载。",
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
            return

        result = QProcess.startDetached(str(installerPath), [])
        started = result[0] if isinstance(result, tuple) else bool(result)
        if not started:
            InfoBar.error(
                "无法启动安装程序",
                "请重新下载后再试。",
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )
            return

        infoBar.close()
        self._shutdownResources()
        QApplication.quit()

    def requestQuit(self):
        self._saveGeometry()
        self._shutdownResources()
        if self._downloadWorker is not None:
            self._quitAfterDownload = True
            self._downloadWorker.cancel()
            return
        QApplication.quit()

    def _shutdownResources(self):
        if self._resourcesShutdown:
            return
        self._resourcesShutdown = True
        self._updateRequestId += 1
        self._pendingNavigation = None
        self.stackedWidget.view._stopAnimation()
        self._navigationTarget = None
        self.scheduleTimer.stop()
        self._cancelPendingEdgeTts()
        self.tts.stop()
        self.player.stop()
        self._cleanupEdgeTtsFile()
        if self._downloadWorker is not None:
            self._downloadWorker.cancel()

        if self._updateInfoBar is not None:
            self._updateInfoBar.close()
            self._updateInfoBar = None
        self._closeUpdateCheckInfoBar()
        self._disposeDownloadStateToolTip()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.searchEdit is not None and self.searchEdit.isVisible():
            self._refreshSearchEditGeometry()

    def showEvent(self, event):
        super().showEvent(event)
        if self._geometryApplied:
            return
        self._geometryApplied = True
        geometry = cfg.geometry.value
        if (
            geometry.isValid()
            and QApplication.screenAt(geometry.center()) is not None
        ):
            self.setGeometry(geometry)
            return

        self.resize(800, 450)
        desktop = QApplication.primaryScreen().availableGeometry()
        self.move(desktop.center() - self.rect().center())

    def _saveGeometry(self):
        if not self.isMaximized():
            cfg.set(cfg.geometry, self.geometry())

    def closeEvent(self, event):
        self._saveGeometry()
        event.ignore()
        self.hide()
        QTimer.singleShot(0, self, emptyWorkingSet)
