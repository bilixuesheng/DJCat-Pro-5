import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    DrillInTransitionStackedWidget,
    HorizontalFlipView,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PipsPager,
    Pivot,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    ToggleToolButton,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.application_store import (
    ApplicationStore,
    ApplicationStoreError,
    downloadWorker,
)
from app.common.home_cards import (
    DIRECT_APPLICATION_PRESET_ID,
    normalize_pinned_cards,
)
from app.config.cfg import cfg
from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import LabelElideFilter
from app.view.components.tool_tip import setFluentToolTip

SHUTDOWN_WAIT_SECONDS = 0.5


class CatalogWorker(QObject):
    finished = Signal(object, object, str)
    imageLoaded = Signal(str, str)
    completed = Signal()

    def __init__(self, store: ApplicationStore):
        super().__init__()
        self.store = store
        self._cancelEvent = threading.Event()

    def cancel(self):
        self._cancelEvent.set()

    def run(self):
        try:
            payload = self.store.fetchCatalog()
            if self._cancelEvent.is_set():
                return
            self.finished.emit(payload, {}, "")
            imagePaths = {}
            urls = {
                item.get("icon_url", "")
                for item in payload.get("apps", [])
                if isinstance(item, dict)
            }
            urls.update(
                item.get("image_url", "")
                for item in payload.get("ads", [])
                if isinstance(item, dict)
            )
            for url in urls:
                if self._cancelEvent.is_set():
                    return
                if not url:
                    continue
                try:
                    imagePaths[url] = str(self.store.imagePath(url))
                except Exception:
                    continue
                if not self._cancelEvent.is_set():
                    self.imageLoaded.emit(url, imagePaths[url])
        except Exception as error:
            if not self._cancelEvent.is_set():
                self.finished.emit({}, {}, str(error))
        finally:
            self.completed.emit()


class ApplicationCard(CardWidget):
    actionClicked = Signal()
    pinClicked = Signal()
    uninstallClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setClickEnabled(True)
        self.setFixedHeight(168)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.appId = None
        self.appData = {}
        self.installedPage = False
        self._pressPosition = None
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(54, 54)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.iconLabel.setStyleSheet("border-radius: 12px; background: transparent;")
        self.titleLabel = SubtitleLabel(self)
        self.titleLabel.setWordWrap(False)
        self.titleLabel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.descriptionLabel = BodyLabel(self)
        self.descriptionLabel.setWordWrap(True)
        self.descriptionLabel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        descriptionHeight = self.descriptionLabel.fontMetrics().lineSpacing() * 2
        self.descriptionLabel.setFixedHeight(descriptionHeight)
        self._elideFilter = LabelElideFilter(maximumLines=1)
        self._descriptionElideFilter = LabelElideFilter(maximumLines=2)
        self.titleLabel.installEventFilter(self._elideFilter)
        self.descriptionLabel.installEventFilter(self._descriptionElideFilter)
        self.pinButton = ToggleToolButton(FIF.PIN, self)
        self.pinButton.setFixedSize(40, 40)
        self.pinButton.setAccessibleName("固定到主页")
        setFluentToolTip(self.pinButton, "固定到主页")
        self.pinButton.hide()
        self.actionButton = PrimaryPushButton(self)
        self.actionButton.setFixedHeight(40)
        self.removeButton = ToolButton(FIF.DELETE, self)
        self.removeButton.setFixedSize(40, 40)
        setFluentToolTip(self.removeButton, "卸载")
        self.removeButton.setStyleSheet(
            "ToolButton { color: #d13438; border: 1px solid #d13438; border-radius: 8px; }"
            "ToolButton:hover { background: #d13438; color: white; }"
        )
        self.removeButton.hide()

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.iconLabel)
        top.addWidget(self.titleLabel, 1)
        top.addWidget(self.pinButton)
        body = QVBoxLayout()
        body.setContentsMargins(14, 14, 14, 12)
        body.setSpacing(7)
        body.addLayout(top)
        body.addWidget(self.descriptionLabel)
        body.addStretch(1)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(self.actionButton, 1)
        actions.addWidget(self.removeButton)
        body.addLayout(actions)
        self.setLayout(body)

        self.actionButton.clicked.connect(self.actionClicked)
        self.pinButton.clicked.connect(self.pinClicked)
        self.removeButton.clicked.connect(self.uninstallClicked)

    def setApplication(self, app: dict, imagePath: str = "") -> None:
        self.appId = int(app["id"])
        self.appData = app
        self.titleLabel.setText(str(app.get("name", "")))
        setFluentToolTip(self.titleLabel, str(app.get("name", "")))
        self.descriptionLabel.setText(str(app.get("description", "")))
        setFluentToolTip(
            self.descriptionLabel,
            str(app.get("description", "")),
        )
        self.setImage(imagePath)

    def setImage(self, imagePath: str = "") -> None:
        if imagePath and Path(imagePath).exists():
            pixmap = QPixmap(imagePath).scaled(
                54,
                54,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.iconLabel.setPixmap(pixmap)
        else:
            self.iconLabel.setPixmap(
                FIF.APPLICATION.icon().pixmap(QSize(32, 32))
            )

    def setState(
        self,
        text: str,
        removable: bool = False,
        enabled: bool = True,
        pinnable: bool = False,
        pinned: bool = False,
    ) -> None:
        self.actionButton.setText(text)
        self.actionButton.setEnabled(enabled)
        self.removeButton.setVisible(removable)
        self.removeButton.setEnabled(enabled)
        self.pinButton.setVisible(removable)
        self.pinButton.setEnabled(enabled and pinnable)
        self.pinButton.setChecked(pinned)
        tooltip = "取消固定" if pinned else (
            "固定到主页" if pinnable else "该软件未配置打开动作"
        )
        self.pinButton.setAccessibleName(tooltip)
        setFluentToolTip(self.pinButton, tooltip)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressPosition = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            releasePosition = event.globalPosition().toPoint()
            shouldClick = (
                self._pressPosition is not None
                and self.rect().contains(event.position().toPoint())
                and (releasePosition - self._pressPosition).manhattanLength()
                < QApplication.startDragDistance()
            )
            self._pressPosition = None
            if not shouldClick:
                self.isPressed = False
                self._updateBackgroundColor()
                event.accept()
                return
        super().mouseReleaseEvent(event)


class AdvertisementFrame(QWidget):
    entered = Signal()
    left = Signal()
    resized = Signal()

    def sizeHint(self):
        return QSize(1000, 220)

    def resizeEvent(self, event):
        self.resized.emit()
        super().resizeEvent(event)

    def enterEvent(self, event):
        self.entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.left.emit()
        super().leaveEvent(event)


class AdvertisementOverlay(QWidget):
    previousRequested = Signal()
    nextRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressPosition = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressPosition = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressPosition is not None:
            distance = event.position().toPoint().x() - self._pressPosition.x()
            self._pressPosition = None
            if abs(distance) >= QApplication.startDragDistance():
                (self.previousRequested if distance > 0 else self.nextRequested).emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)


class AppStorePage(ScrollArea):
    pinnedCardsChanged = Signal(object)
    _downloadProgressSignal = Signal(int, int, int)
    _downloadRetrySignal = Signal(str)
    _downloadFinishedSignal = Signal(object, str, str, bool)
    _uninstallFinished = Signal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = ApplicationStore()
        self.catalog = []
        self.ads = []
        self.imagePaths = {}
        self.currentApp = None
        self.searchText = ""
        self._catalogLoading = False
        self._catalogLoaded = False
        self._catalogThread = None
        self._catalogWorker = None
        self._shuttingDown = False
        self._downloadJobs = {}
        self._downloadStates = {}
        self._installing = set()
        self._uninstalling = set()
        self._fileOperationThreads = set()
        self._fileOperationLock = threading.Lock()
        self._installationCancelEvent = threading.Event()
        self._pendingProgress = {}
        self._progressTimer = QTimer(self)
        self._progressTimer.setInterval(100)
        self._progressTimer.timeout.connect(self._flushDownloadProgress)
        self._currentPage = 0
        self._catalogScrollPosition = 0
        self._renderingAll = False
        self._downloadProgressSignal.connect(self._queueDownloadProgress)
        self._downloadRetrySignal.connect(self._showDownloadRetry)
        self._downloadFinishedSignal.connect(self._onDownloadFinished)
        self._installFinished.connect(self._onInstallFinished)
        self._uninstallFinished.connect(self._onUninstallFinished)
        self.setObjectName("AppStorePage")
        self._buildUi()
        cfg.pinnedHomeCards.valueChanged.connect(self._refreshPinStates)

    def _buildUi(self):
        self.container = QWidget()
        self.rootLayout = QVBoxLayout(self.container)
        self.rootLayout.setContentsMargins(12, 8, 20, 24)
        self.rootLayout.setSpacing(8)

        self.pivot = Pivot(self.container)
        self.pivot.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.pivot.addItem("installed", "已安装", lambda: self._switchCatalogTab(0))
        self.pivot.addItem("all", "全部应用", lambda: self._switchCatalogTab(1))
        self.pivot.setCurrentItem("installed")

        header = QHBoxLayout()
        header.addWidget(self.pivot)
        header.addStretch(1)
        self.refreshButton = ToolButton(FIF.SYNC, self.container)
        setFluentToolTip(self.refreshButton, "刷新应用目录")
        self.refreshButton.clicked.connect(self._loadCatalog)
        header.addWidget(self.refreshButton)
        self.rootLayout.addLayout(header)

        self.stack = DrillInTransitionStackedWidget(self.container)
        self.catalogPage = QWidget(self.stack)
        catalogLayout = QVBoxLayout(self.catalogPage)
        catalogLayout.setContentsMargins(0, 0, 0, 0)
        self.catalogStack = QStackedWidget(self.catalogPage)
        catalogLayout.addWidget(self.catalogStack)

        self.overview = QWidget(self.catalogStack)
        overviewLayout = QVBoxLayout(self.overview)
        overviewLayout.setContentsMargins(0, 0, 0, 0)
        overviewLayout.setSpacing(8)
        overviewLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.installedTitle = BodyLabel("已安装的软件", self.overview)
        overviewLayout.addWidget(self.installedTitle)
        self.installedEmpty = BodyLabel("还没有已安装的应用。可以切换到“全部应用”开始下载。", self.overview)
        self.installedEmpty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overviewLayout.addWidget(self.installedEmpty)
        self.installedGridWidget, self.installedGrid = self._createGrid(self.overview)
        overviewLayout.addWidget(self.installedGridWidget)

        self.allPage = QWidget(self.catalogStack)
        allLayout = QVBoxLayout(self.allPage)
        allLayout.setContentsMargins(0, 0, 0, 0)
        allLayout.setSpacing(8)
        allLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.adFrame = AdvertisementFrame(self.allPage)
        self.adFrame.setMinimumHeight(200)
        self.adFrame.setMaximumHeight(240)
        self.adFrame.setMaximumWidth(1000)
        adLayout = QVBoxLayout(self.adFrame)
        adLayout.setContentsMargins(0, 0, 0, 0)
        self.adFlipView = HorizontalFlipView(self.adFrame)
        self.adFlipView.setMouseTracking(True)
        self.adFlipView.setMinimumSize(0, 0)
        self.adFlipView.setAspectRatioMode(
            Qt.AspectRatioMode.KeepAspectRatioByExpanding
        )
        self.adFlipView.setBorderRadius(12)
        adLayout.addWidget(self.adFlipView)
        self.adOverlay = AdvertisementOverlay(self.adFlipView)
        self.adOverlay.setObjectName("AdvertisementOverlay")
        self.adOverlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.adOverlay.setStyleSheet(
            "QWidget#AdvertisementOverlay {"
            "background: qlineargradient(y1: 0, y2: 1, stop: 0.38 transparent, "
            "stop: 0.48 rgba(0,0,0,45), stop: 0.58 rgba(0,0,0,95), "
            "stop: 0.74 rgba(0,0,0,175), stop: 1 rgba(0,0,0,245));"
            "border-radius: 12px;"
            "}"
        )
        overlayLayout = QVBoxLayout(self.adOverlay)
        overlayLayout.setContentsMargins(20, 12, 20, 16)
        overlayLayout.setSpacing(6)
        overlayLayout.addStretch(1)
        self.adTitle = SubtitleLabel(self.adOverlay)
        self.adTitle.setStyleSheet("color: white;")
        self.adDescription = BodyLabel(self.adOverlay)
        self.adDescription.setStyleSheet("color: rgba(255,255,255,220);")
        self.adDescription.setWordWrap(True)
        overlayLayout.addWidget(self.adTitle)
        overlayLayout.addWidget(self.adDescription)
        self.adButton = PrimaryPushButton("查看软件", self.adOverlay)
        self.adButton.setMinimumHeight(40)
        self.adButton.clicked.connect(self._openAdApp)
        overlayLayout.addWidget(self.adButton, 0, Qt.AlignmentFlag.AlignLeft)
        self.adPrevious = self.adFlipView.preButton
        self.adNext = self.adFlipView.nextButton
        for button in (self.adPrevious, self.adNext):
            button.setFixedSize(40, 40)
        self.adOverlay.previousRequested.connect(self._previousAd)
        self.adOverlay.nextRequested.connect(self._nextAd)
        self.adFrame.entered.connect(self._pauseAds)
        self.adFrame.left.connect(self._resumeAds)
        self.adFrame.resized.connect(
            lambda: QTimer.singleShot(0, self._syncAdImageSize)
        )
        self.adTimer = QTimer(self)
        self.adTimer.setInterval(6000)
        self.adTimer.timeout.connect(self._nextAd)
        self.adFlipView.currentIndexChanged.connect(self._onAdChanged)
        allLayout.addWidget(self.adFrame, 0, Qt.AlignmentFlag.AlignHCenter)

        self.categoryPivot = Pivot(self.allPage)
        self.categoryPivot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.categoryPivot.addItem("recommended", "推荐", lambda: self._switchCategory(0))
        self.categoryPivot.addItem("all", "全部", lambda: self._switchCategory(1))
        self.categoryPivot.setCurrentItem("recommended")
        allLayout.addWidget(self.categoryPivot)
        self.allGridWidget, self.allGrid = self._createGrid(self.allPage)
        allLayout.addWidget(self.allGridWidget)
        self.pagerBar = QWidget(self.allPage)
        pagerLayout = QHBoxLayout(self.pagerBar)
        pagerLayout.setContentsMargins(0, 0, 0, 0)
        pagerLayout.setSpacing(8)
        self.pagerPrevious = ToolButton(FIF.LEFT_ARROW, self.pagerBar)
        self.pagerPrevious.setFixedSize(40, 40)
        setFluentToolTip(self.pagerPrevious, "上一页")
        self.pagerPrevious.clicked.connect(lambda: self._changePage(-1))
        pagerLayout.addWidget(self.pagerPrevious)
        self.pager = PipsPager(self.pagerBar)
        self.pager.currentIndexChanged.connect(self._onPageChanged)
        pagerLayout.addWidget(self.pager)
        self.pagerNext = ToolButton(FIF.RIGHT_ARROW, self.pagerBar)
        self.pagerNext.setFixedSize(40, 40)
        setFluentToolTip(self.pagerNext, "下一页")
        self.pagerNext.clicked.connect(lambda: self._changePage(1))
        pagerLayout.addWidget(self.pagerNext)
        allLayout.addWidget(self.pagerBar, 0, Qt.AlignmentFlag.AlignHCenter)

        self.catalogStack.addWidget(self.overview)
        self.catalogStack.addWidget(self.allPage)
        self.stack.addWidget(self.catalogPage)
        self.rootLayout.addWidget(self.stack)

        self.detail = QWidget(self.stack)
        self._buildDetail()
        self.stack.addWidget(self.detail)
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self.adFrame.hide()

    def _createGrid(self, parent):
        widget = QWidget(parent)
        layout = QGridLayout(widget)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        return widget, layout

    def _buildDetail(self):
        layout = QVBoxLayout(self.detail)
        layout.setContentsMargins(0, 0, 0, 0)
        back = PushButton(FIF.LEFT_ARROW, "返回应用列表", self.detail)
        back.clicked.connect(self._backToOverview)
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        columns = QHBoxLayout()
        columns.setSpacing(28)
        self.detailLeft = QFrame(self.detail)
        self.detailLeft.setMinimumWidth(300)
        leftLayout = QVBoxLayout(self.detailLeft)
        leftLayout.setContentsMargins(8, 8, 8, 8)
        self.detailIcon = QLabel(self.detailLeft)
        self.detailIcon.setFixedSize(112, 112)
        self.detailIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detailName = TitleLabel(self.detailLeft)
        self.detailDeveloper = BodyLabel(self.detailLeft)
        self.detailVersion = BodyLabel(self.detailLeft)
        self.detailAction = PrimaryPushButton(self.detailLeft)
        self.detailAction.setMinimumHeight(48)
        self.detailAction.clicked.connect(self._onDetailAction)
        self.detailDescription = BodyLabel(self.detailLeft)
        self.detailDescription.setWordWrap(True)
        leftLayout.addWidget(self.detailIcon, 0, Qt.AlignmentFlag.AlignLeft)
        leftLayout.addWidget(self.detailName)
        leftLayout.addWidget(self.detailDeveloper)
        leftLayout.addWidget(self.detailVersion)
        leftLayout.addSpacing(8)
        leftLayout.addWidget(self.detailAction)
        leftLayout.addSpacing(12)
        leftLayout.addWidget(self.detailDescription)
        leftLayout.addStretch(1)
        columns.addWidget(self.detailLeft, 1)

        self.presetPanel = QFrame(self.detail)
        presetLayout = QVBoxLayout(self.presetPanel)
        presetLayout.setContentsMargins(0, 8, 0, 8)
        presetLayout.addWidget(SubtitleLabel("预设卡片", self.presetPanel))
        self.announcementLabel = QLabel(self.presetPanel)
        self.announcementLabel.setWordWrap(True)
        self.announcementLabel.setStyleSheet(
            "padding: 10px 12px; border-radius: 8px; background: #fff4e6; color: #8a4b08;"
        )
        presetLayout.addWidget(self.announcementLabel)
        self.presetCards = QVBoxLayout()
        self.presetCards.setSpacing(10)
        presetLayout.addLayout(self.presetCards)
        presetLayout.addStretch(1)
        columns.addWidget(self.presetPanel, 2)
        layout.addLayout(columns)

    def _switchCatalogTab(self, index: int):
        self.catalogStack.setCurrentIndex(index)
        if index == 1:
            self._renderAll()
            self._resumeAds()
        else:
            self._pauseAds()
            self._renderInstalled()

    def _switchCategory(self, index: int):
        self._currentPage = 0
        self._renderAll()

    def setSearchText(self, text: str):
        self.searchText = text.strip().lower()
        if self.stack.currentWidget() is self.detail:
            return
        if self.catalogStack.currentIndex() == 0:
            self._renderInstalled()
        else:
            self._renderAll()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._catalogLoaded:
            self._loadCatalog()

    def hideEvent(self, event):
        self._pauseAds()
        super().hideEvent(event)

    def shutdown(self):
        if self._shuttingDown:
            return
        self._shuttingDown = True
        self._pauseAds()
        self._progressTimer.stop()
        self._pendingProgress.clear()
        self._catalogLoading = False
        catalogThread = self._catalogThread
        if self._catalogWorker is not None:
            self._catalogWorker.cancel()

        jobs = tuple(self._downloadJobs.items())
        for _appId, (thread, worker) in jobs:
            worker.cancel()
        self._installationCancelEvent.set()
        with self._fileOperationLock:
            fileOperationThreads = tuple(self._fileOperationThreads)

        deadline = time.monotonic() + SHUTDOWN_WAIT_SECONDS
        threads = [thread for _appId, (thread, _worker) in jobs]
        if catalogThread is not None:
            threads.insert(0, catalogThread)
        threads.extend(fileOperationThreads)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(max(0, deadline - time.monotonic()))

        if catalogThread is None or not catalogThread.is_alive():
            self._catalogWorker = None
            self._catalogThread = None

        for appId, (thread, worker) in jobs:
            if self._downloadJobs.pop(appId, None) is not None:
                self.store.downloadSlots.release()
            self._downloadStates.pop(appId, None)
            if thread.is_alive():
                continue
            for attribute in ("targetPath", "partialPath"):
                path = getattr(worker, attribute, None)
                if path:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except OSError:
                        pass

        for _appId in tuple(self._installing):
            self.store.downloadSlots.release()
        self._installing.clear()
        for appId in self._uninstalling:
            self._downloadStates.pop(appId, None)
        self._uninstalling.clear()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _loadCatalog(self):
        if self._shuttingDown or self._catalogLoading:
            return
        self._catalogLoading = True
        self.refreshButton.setEnabled(False)
        worker = CatalogWorker(self.store)
        self._catalogWorker = worker
        thread = threading.Thread(target=worker.run, daemon=True)
        self._catalogThread = thread
        worker.finished.connect(self._onCatalogLoaded)
        worker.imageLoaded.connect(self._onCatalogImageLoaded)
        worker.completed.connect(self._onCatalogCompleted)
        thread.start()

    def _onCatalogLoaded(self, payload, imagePaths, error):
        if self._shuttingDown:
            return
        if error:
            InfoBar.error("应用目录加载失败", error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._catalogLoaded = True
        self.catalog = list(payload.get("apps", []))
        self.ads = list(payload.get("ads", []))
        self.imagePaths.update(imagePaths)
        self._prepareAds()
        self._renderInstalled()
        self._renderAll()
        if self.currentApp:
            current = next((app for app in self._mergedApps() if app["id"] == self.currentApp["id"]), None)
            if current:
                self._showDetail(current)

    def _onCatalogImageLoaded(self, url, path):
        if self._shuttingDown:
            return
        self.imagePaths[url] = path
        for card in self.container.findChildren(ApplicationCard):
            if card.appData.get("icon_url") == url:
                card.setImage(path)

        if self.currentApp and self.currentApp.get("icon_url") == url:
            self.detailIcon.setPixmap(
                QPixmap(path).scaled(
                    112,
                    112,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        for index, ad in enumerate(self.ads):
            if ad.get("image_url") == url:
                self.adFlipView.setItemImage(index, QPixmap(path))

        pinnedCards = normalize_pinned_cards(cfg.pinnedHomeCards.value)
        pinnedChanged = pinnedCards != cfg.pinnedHomeCards.value
        updatedCards = []
        for item in pinnedCards:
            card = dict(item)
            if card.get("icon_url") == url and card.get("icon_path") != path:
                card["icon_path"] = path
                pinnedChanged = True
            updatedCards.append(card)
        if pinnedChanged:
            cfg.set(cfg.pinnedHomeCards, updatedCards)
            self.pinnedCardsChanged.emit(updatedCards)

    def _onCatalogCompleted(self):
        if self.sender() is not self._catalogWorker:
            return
        self._catalogLoading = False
        self._catalogWorker = None
        self._catalogThread = None
        if not self._shuttingDown:
            self.refreshButton.setEnabled(True)

    def _mergedApps(self):
        return self.store.mergeInstalled(self.catalog)

    def _filtered(self, apps):
        if not self.searchText:
            return list(apps)
        return [
            app for app in apps
            if self.searchText in str(app.get("name", "")).lower()
            or self.searchText in str(app.get("description", "")).lower()
            or self.searchText in str(app.get("developer", "")).lower()
        ]

    def _clearGrid(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def _columnCount(self):
        margins = self.rootLayout.contentsMargins()
        width = self.viewport().width() - margins.left() - margins.right()
        if width >= 900:
            return 3
        if width >= 640:
            return 2
        return 1

    @staticmethod
    def _setGridColumns(layout, columns):
        for column in range(3):
            layout.setColumnStretch(column, 1 if column < columns else 0)
            layout.setColumnMinimumWidth(column, 0)

    def _setCardState(self, card, app, installedPage=False):
        appId = int(app["id"])
        state = self._downloadStates.get(appId)
        supported = bool(app.get("architecture_supported"))
        if state:
            actionText = state
            enabled = False
        elif installedPage:
            actionText = "更新" if app.get("update_available") else "打开"
            enabled = True
        else:
            actionText = "更新" if app.get("update_available") else (
                "打开" if app.get("installed") else ("下载" if supported else "不支持")
            )
            enabled = supported or bool(app.get("installed") and not app.get("update_available"))
        directKey = (appId, DIRECT_APPLICATION_PRESET_ID)
        card.setState(
            actionText,
            installedPage,
            enabled,
            isinstance(app.get("open_action"), dict),
            directKey in self._pinnedKeys(),
        )

    def _renderGrid(self, layout, apps, installedPage=False):
        self._clearGrid(layout)
        columns = self._columnCount()
        for index, app in enumerate(apps):
            card = ApplicationCard(self)
            card.setApplication(app, self.imagePaths.get(app.get("icon_url", ""), ""))
            card.installedPage = installedPage
            self._setCardState(card, app, installedPage)
            card.clicked.connect(lambda appData=app: self._showDetail(appData))
            card.actionClicked.connect(lambda _checked=False, appData=app: self._onAppAction(appData))
            card.pinClicked.connect(
                lambda _checked=False, appData=app: self._toggleApplicationPin(
                    appData
                )
            )
            card.uninstallClicked.connect(lambda _checked=False, appData=app: self._confirmUninstall(appData))
            row, column = divmod(index, columns)
            layout.addWidget(card, row, column)
        self._setGridColumns(layout, columns)

    def _reflowGrid(self, layout):
        widgets = []
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                widgets.append(item.widget())
        columns = self._columnCount()
        for index, widget in enumerate(widgets):
            row, column = divmod(index, columns)
            layout.addWidget(widget, row, column)
        self._setGridColumns(layout, columns)

    def _reflowGrids(self):
        if not hasattr(self, "installedGrid") or not hasattr(self, "allGrid"):
            return
        self._reflowGrid(self.installedGrid)
        self._reflowGrid(self.allGrid)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._reflowGrids)
        QTimer.singleShot(0, self._syncAdImageSize)

    def _updateVisibleCardState(self, appId):
        for card in self.container.findChildren(ApplicationCard):
            if card.appId == appId:
                self._setCardState(card, card.appData, card.installedPage)

    def _refreshPinStates(self, _cards=None):
        if self._shuttingDown:
            return
        for card in self.container.findChildren(ApplicationCard):
            self._setCardState(card, card.appData, card.installedPage)
        if self.currentApp:
            self._renderPresets(self.currentApp)

    def _renderInstalled(self):
        apps = [app for app in self._filtered(self._mergedApps()) if app.get("installed")]
        self._renderGrid(self.installedGrid, apps, True)
        self.installedTitle.setText(f"已安装的软件（{len(apps)}）")
        self.installedEmpty.setVisible(not apps)

    def _allAppsForPage(self):
        apps = self._filtered(self._mergedApps())
        if self.categoryPivot.currentRouteKey() == "recommended":
            apps = [app for app in apps if app.get("recommended")]
        return apps

    def _renderAll(self):
        if self._renderingAll:
            return
        self._renderingAll = True
        self.pager.blockSignals(True)
        try:
            apps = self._allAppsForPage()
            paginated = self.categoryPivot.currentRouteKey() == "all"
            pageCount = max(1, (len(apps) + 14) // 15) if paginated else 1
            if self.pager.count() != pageCount:
                self.pager.setPageNumber(pageCount)
            self._currentPage = min(self._currentPage, pageCount - 1)
            if self.pager.currentIndex() != self._currentPage:
                self.pager.setCurrentIndex(self._currentPage)
            self.pager.setVisible(paginated)
            self.pagerBar.setVisible(paginated)
            self._updatePagerButtons()
            self._renderAllPage(apps)
        finally:
            self.pager.blockSignals(False)
            self._renderingAll = False

    def _renderAllPage(self, apps=None):
        apps = self._allAppsForPage() if apps is None else apps
        if self.categoryPivot.currentRouteKey() == "all":
            apps = apps[self._currentPage * 15 : (self._currentPage + 1) * 15]
        self._renderGrid(self.allGrid, apps)

    def _onPageChanged(self, index):
        if self._renderingAll:
            return
        self._currentPage = index
        self._updatePagerButtons()
        self._renderAllPage()

    def _changePage(self, offset):
        self.pager.setCurrentIndex(self._currentPage + offset)

    def _updatePagerButtons(self):
        self.pagerPrevious.setEnabled(self._currentPage > 0)
        self.pagerNext.setEnabled(self._currentPage + 1 < self.pager.count())

    def _prepareAds(self):
        self.adFlipView.clear()
        if not self.ads:
            self.adFrame.hide()
            self._pauseAds()
            return
        for ad in self.ads:
            path = self.imagePaths.get(ad.get("image_url", ""), "")
            if path and Path(path).exists():
                self.adFlipView.addImage(QPixmap(path))
            else:
                self.adFlipView.addImage(QPixmap())
        self.adFlipView.setCurrentIndex(0)
        self.adFrame.show()
        multipleAds = len(self.ads) > 1
        self.adPrevious.setVisible(multipleAds)
        self.adNext.setVisible(multipleAds)
        QTimer.singleShot(0, self._syncAdImageSize)
        self._onAdChanged(0)
        self._resumeAds()

    def _syncAdImageSize(self):
        if not hasattr(self, "adFlipView"):
            return
        size = self.adFlipView.viewport().size()
        if size.width() > 0 and size.height() > 0:
            self.adFlipView.setItemSize(size)
            self._positionAdOverlay()
            if self.adFlipView.currentIndex() >= 0:
                duration = self.adFlipView.scrollBar.duration
                self.adFlipView.scrollBar.duration = 0
                self.adFlipView.scrollToIndex(self.adFlipView.currentIndex())
                self.adFlipView.scrollBar.duration = duration

    def _positionAdOverlay(self):
        self.adOverlay.setGeometry(self.adFlipView.viewport().geometry())
        self.adOverlay.raise_()
        self.adPrevious.raise_()
        self.adNext.raise_()

    def _onAdChanged(self, index):
        if not self.ads:
            return
        index = max(0, min(index, len(self.ads) - 1))
        ad = self.ads[index]
        self.adTitle.setText(str(ad.get("title", "")))
        self.adDescription.setText(str(ad.get("description", "")))
        self.adButton.setVisible(bool(ad.get("app_id")))
        self._positionAdOverlay()

    def _nextAd(self):
        if self.ads:
            self.adFlipView.setCurrentIndex((self.adFlipView.currentIndex() + 1) % len(self.ads))

    def _previousAd(self):
        if self.ads:
            self.adFlipView.setCurrentIndex((self.adFlipView.currentIndex() - 1) % len(self.ads))

    def _openAdApp(self):
        if not self.ads:
            return
        index = self.adFlipView.currentIndex()
        if not 0 <= index < len(self.ads):
            return
        appId = self.ads[index].get("app_id")
        app = next((item for item in self._mergedApps() if item["id"] == appId), None)
        if app:
            self._showDetail(app)

    def _pauseAds(self):
        self.adTimer.stop()

    def _resumeAds(self):
        if (
            self.isVisible()
            and self.ads
            and self.currentApp is None
            and self.catalogStack.currentIndex() == 1
        ):
            self.adTimer.start()

    def _showDetail(self, app):
        if self.stack.currentWidget() is not self.detail:
            self._catalogScrollPosition = self.verticalScrollBar().value()
        self.currentApp = app
        self._pauseAds()
        self.pivot.hide()
        self.refreshButton.hide()
        self.stack.setCurrentWidget(self.detail)
        self.verticalScrollBar().setValue(0)
        self.detailName.setText(str(app.get("name", "")))
        self.detailDeveloper.setText(f"开发者：{app.get('developer') or '未填写'}")
        self.detailVersion.setText(f"版本：{app.get('version') or '未填写'}")
        self.detailDescription.setText(str(app.get("description", "")))
        iconPath = self.imagePaths.get(app.get("icon_url", ""), "")
        self.detailIcon.setPixmap(
            QPixmap(iconPath).scaled(112, 112, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            if iconPath and Path(iconPath).exists()
            else FIF.APPLICATION.icon().pixmap(QSize(72, 72))
        )
        self._updateDetailAction()
        self._renderPresets(app)

    def _backToOverview(self):
        self.currentApp = None
        self.pivot.show()
        self.refreshButton.show()
        target = 0 if self.pivot.currentRouteKey() == "installed" else 1
        self.catalogStack.setCurrentIndex(target)
        if target == 0:
            self._renderInstalled()
        else:
            self._renderAll()
        self.stack.setCurrentIndex(0, isBack=True)
        QTimer.singleShot(0, self._restoreCatalogScroll)
        if target == 1:
            self._resumeAds()

    def _restoreCatalogScroll(self):
        if self.currentApp is None:
            scrollBar = self.verticalScrollBar()
            scrollBar.setValue(min(self._catalogScrollPosition, scrollBar.maximum()))

    def _updateDetailAction(self):
        if not self.currentApp:
            return
        appId = int(self.currentApp["id"])
        if appId in self._downloadStates:
            self.detailAction.setText(self._downloadStates[appId])
        elif self.currentApp.get("update_available"):
            self.detailAction.setText("更新")
        elif self.currentApp.get("installed"):
            self.detailAction.setText("打开")
        else:
            self.detailAction.setText("下载")
        supported = self.store.architecture in {
            architecture
            for architecture, package in (self.currentApp.get("packages") or {}).items()
            if package.get("enabled")
        }
        self.detailAction.setEnabled(
            appId not in self._downloadJobs
            and appId not in self._installing
            and appId not in self._uninstalling
            and (
                supported
                or bool(self.currentApp.get("installed") and not self.currentApp.get("update_available"))
            )
        )

    def _onDetailAction(self):
        if self.currentApp:
            self._onAppAction(self.currentApp)

    def _onAppAction(self, app):
        appId = int(app["id"])
        if (
            appId in self._downloadJobs
            or appId in self._installing
            or appId in self._uninstalling
        ):
            return
        if app.get("installed") and not app.get("update_available"):
            try:
                local = self.store.installed().get(appId)
                self.store.executeAction(local or app, app.get("open_action") if local else None)
            except (ApplicationStoreError, OSError) as error:
                InfoBar.error("无法打开应用", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        try:
            self.store.downloadSlots.acquire()
        except ApplicationStoreError as error:
            InfoBar.warning("下载任务已满", str(error), duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        try:
            worker = downloadWorker(app, self.store)
        except Exception as error:
            self.store.downloadSlots.release()
            InfoBar.error("无法开始下载", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        thread = threading.Thread(target=worker.run, daemon=True)
        self._downloadJobs[appId] = (thread, worker)
        self._downloadStates[appId] = "下载中 0%"
        worker.progressChanged.connect(
            lambda done, total, _speed, _workers, appId=appId: self._downloadProgressSignal.emit(
                appId, done, total
            )
        )
        worker.retrying.connect(
            lambda _try, _total, message: self._downloadRetrySignal.emit(message)
        )
        worker.finished.connect(
            lambda path, error, canceled, appData=app: self._downloadFinishedSignal.emit(
                appData, path, error, canceled
            )
        )
        worker.finished.connect(worker.deleteLater)
        thread.start()
        self._updateVisibleCardState(appId)
        self._updateDetailAction()

    def _queueDownloadProgress(self, appId, done, total):
        if appId not in self._downloadJobs:
            return
        self._pendingProgress[appId] = (done, total)
        if not self._progressTimer.isActive():
            self._progressTimer.start()

    def _flushDownloadProgress(self):
        pending = self._pendingProgress
        self._pendingProgress = {}
        if not pending:
            self._progressTimer.stop()
            return
        for appId, (done, total) in pending.items():
            self._onDownloadProgress(appId, done, total)

    def _onDownloadProgress(self, appId, done, total):
        if appId not in self._downloadJobs:
            return
        percent = int(done * 100 / total) if total else 0
        self._downloadStates[appId] = f"下载中 {percent}%"
        self._updateVisibleCardState(appId)
        if self.currentApp and int(self.currentApp["id"]) == appId:
            self._updateDetailAction()

    def _showDownloadRetry(self, message):
        InfoBar.warning("下载重试", message, duration=2000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _onDownloadFinished(self, app, path, error, canceled):
        if self._shuttingDown:
            return
        appId = int(app["id"])
        if self._downloadJobs.pop(appId, None) is None:
            return
        self._pendingProgress.pop(appId, None)
        if not self._pendingProgress:
            self._progressTimer.stop()
        if canceled or error or not path:
            self.store.downloadSlots.release()
            self._downloadStates.pop(appId, None)
            self._updateVisibleCardState(appId)
            self._updateDetailAction()
            if error:
                InfoBar.error("下载失败", error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._installing.add(appId)
        self._downloadStates[appId] = "安装中"
        self._updateVisibleCardState(appId)
        self._updateDetailAction()
        thread = threading.Thread(
            target=self._installInBackground,
            args=(app, Path(path)),
            daemon=True,
        )
        with self._fileOperationLock:
            self._fileOperationThreads.add(thread)
        thread.start()

    def _installInBackground(self, app, path):
        try:
            installed = self.store.installZip(
                app,
                path,
                self._installationCancelEvent,
            )
            if not self._shuttingDown:
                self._installFinished.emit(int(app["id"]), installed, "")
        except Exception as error:
            if not self._shuttingDown:
                self._installFinished.emit(int(app["id"]), None, str(error))
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            with self._fileOperationLock:
                self._fileOperationThreads.discard(threading.current_thread())

    _installFinished = Signal(int, object, str)

    def _onInstallFinished(self, appId, installed, error):
        if self._shuttingDown:
            return
        if appId not in self._installing:
            return
        self._installing.discard(appId)
        self.store.downloadSlots.release()
        self._downloadStates.pop(appId, None)
        if error:
            InfoBar.error("安装失败", error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            self._updateVisibleCardState(appId)
            self._updateDetailAction()
            return
        self._reloadState()
        InfoBar.success("安装完成", f"{installed.name} 已安装到 Program/{installed.installDir}。", duration=3500, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _confirmUninstall(self, app):
        appId = int(app["id"])
        if (
            appId in self._downloadJobs
            or appId in self._installing
            or appId in self._uninstalling
        ):
            return
        box = MessageBox("确认卸载", f"将删除 {app.get('name', '')} 的安装目录，是否继续？", self)
        if not box.exec():
            return
        self._uninstalling.add(appId)
        self._downloadStates[appId] = "卸载中"
        self._updateVisibleCardState(appId)
        self._updateDetailAction()
        thread = threading.Thread(
            target=self._uninstallInBackground,
            args=(app,),
            daemon=True,
        )
        with self._fileOperationLock:
            self._fileOperationThreads.add(thread)
        thread.start()

    def _uninstallInBackground(self, app):
        appId = int(app["id"])
        try:
            local = self.store.installed().get(appId)
            self.store.uninstall(local or app)
            if not self._shuttingDown:
                self._uninstallFinished.emit(appId, app, "")
        except Exception as error:
            if not self._shuttingDown:
                self._uninstallFinished.emit(appId, app, str(error))
        finally:
            with self._fileOperationLock:
                self._fileOperationThreads.discard(threading.current_thread())

    def _onUninstallFinished(self, appId, app, error):
        if self._shuttingDown or appId not in self._uninstalling:
            return
        self._uninstalling.discard(appId)
        self._downloadStates.pop(appId, None)
        if error:
            InfoBar.error("卸载失败", error, duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            self._updateVisibleCardState(appId)
            self._updateDetailAction()
            return
        self._reloadState()
        InfoBar.success("已卸载", f"{app.get('name', '')} 已从本机删除。", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _reloadState(self):
        self.catalog = self.store.mergeInstalled(self.catalog)
        self._renderInstalled()
        self._renderAll()
        if self.currentApp:
            current = next((app for app in self.catalog if app["id"] == self.currentApp["id"]), None)
            if current:
                self.currentApp = current
                self._updateDetailAction()
                self._renderPresets(current)

    def _renderPresets(self, app):
        while self.presetCards.count():
            item = self.presetCards.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        announcement = str(app.get("announcement", "")).strip()
        self.announcementLabel.setText(announcement)
        self.announcementLabel.setVisible(bool(announcement))
        presets = app.get("presets") or []
        if not presets:
            self.presetCards.addWidget(BodyLabel("该应用暂不支持预设卡片", self.presetPanel))
            return
        pinned = self._pinnedKeys()
        for preset in presets:
            card = CardWidget(self.presetPanel)
            row = QHBoxLayout(card)
            row.setContentsMargins(14, 12, 14, 12)
            copy = QVBoxLayout()
            copy.addWidget(SubtitleLabel(str(preset.get("title", "")), card))
            copy.addWidget(BodyLabel(str(preset.get("description", "")), card))
            row.addLayout(copy, 1)
            key = (int(app["id"]), int(preset["id"]))
            pin = PushButton(FIF.PIN, "取消固定" if key in pinned else "固定到主页", card)
            pin.setEnabled(bool(app.get("installed")))
            pin.clicked.connect(lambda _checked=False, appData=app, presetData=preset: self._togglePin(appData, presetData))
            row.addWidget(pin)
            self.presetCards.addWidget(card)

    def _pinnedKeys(self):
        return {
            (item["app_id"], item["preset_id"])
            for item in normalize_pinned_cards(cfg.pinnedHomeCards.value)
        }

    def _togglePin(self, app, preset):
        self._togglePinnedCard(
            app,
            preset["id"],
            preset.get("title", ""),
            preset.get("description", ""),
            preset.get("action"),
        )

    def _toggleApplicationPin(self, app):
        action = app.get("open_action")
        if not isinstance(action, dict):
            return
        self._togglePinnedCard(
            app,
            DIRECT_APPLICATION_PRESET_ID,
            app.get("name", ""),
            app.get("description", ""),
            action,
        )
        self._updateVisibleCardState(int(app["id"]))

    def _togglePinnedCard(self, app, presetId, title, description, action):
        cards = normalize_pinned_cards(cfg.pinnedHomeCards.value)
        key = (int(app["id"]), int(presetId))
        existing = next(
            (
                item
                for item in cards
                if (item["app_id"], item["preset_id"]) == key
            ),
            None,
        )
        if existing:
            cards.remove(existing)
        else:
            cards.append(
                {
                    "app_id": key[0],
                    "preset_id": key[1],
                    "title": title,
                    "description": description,
                    "action": action,
                    "install_dir": app.get("install_dir", ""),
                    "icon_url": app.get("icon_url", ""),
                    "icon_path": self.imagePaths.get(app.get("icon_url", ""), ""),
                }
            )
        cfg.set(cfg.pinnedHomeCards, cards)
        self.pinnedCardsChanged.emit(cards)

    def executePinnedCard(self, item):
        cards = normalize_pinned_cards([item])
        if not cards:
            InfoBar.warning("预设卡片无效", "请重新固定这张主页卡片。", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        item = cards[0]
        appId = item["app_id"]
        installed = self.store.installed().get(appId)
        if not installed:
            InfoBar.warning("应用尚未安装", "请先安装对应应用后再使用主页预设卡片。", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        try:
            self.store.executeAction(installed, item.get("action"))
        except (ApplicationStoreError, OSError) as error:
            InfoBar.error("执行预设失败", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def refreshPinnedCards(self):
        cards = normalize_pinned_cards(cfg.pinnedHomeCards.value)
        self._refreshPinStates(cards)
        self.pinnedCardsChanged.emit(cards)
