import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, QTimer, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStackedLayout,
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
    Pivot,
    PipsPager,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.application_store import (
    ApplicationStore,
    ApplicationStoreError,
    downloadWorker,
)
from app.config.cfg import cfg
from app.view.components.setting_card_group import LabelElideFilter
from app.view.components.scroll_area import ScrollArea


class CatalogWorker(QObject):
    finished = Signal(object, object, str)

    def __init__(self, store: ApplicationStore):
        super().__init__()
        self.store = store

    def run(self):
        try:
            payload = self.store.fetchCatalog()
            imagePaths = {}
            urls = {
                item.get("icon_url", "")
                for item in payload.get("apps", [])
            }
            urls.update(item.get("image_url", "") for item in payload.get("ads", []))
            for url in urls:
                if not url:
                    continue
                try:
                    imagePaths[url] = str(self.store.imagePath(url))
                except Exception:
                    continue
            self.finished.emit(payload, imagePaths, "")
        except Exception as error:
            self.finished.emit({}, {}, str(error))


class ApplicationCard(CardWidget):
    actionClicked = Signal()
    uninstallClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setClickEnabled(True)
        self.setFixedHeight(156)
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
        self.descriptionLabel = BodyLabel(self)
        self.descriptionLabel.setWordWrap(False)
        self.descriptionLabel.setMaximumHeight(22)
        self._elideFilter = LabelElideFilter()
        self.titleLabel.installEventFilter(self._elideFilter)
        self.descriptionLabel.installEventFilter(self._elideFilter)
        self.actionButton = PrimaryPushButton(self)
        self.actionButton.setFixedHeight(34)
        self.removeButton = ToolButton(FIF.DELETE, self)
        self.removeButton.setFixedSize(34, 34)
        self.removeButton.setToolTip("卸载")
        self.removeButton.setStyleSheet(
            "ToolButton { color: #d13438; border: 1px solid #d13438; border-radius: 8px; }"
            "ToolButton:hover { background: #d13438; color: white; }"
        )
        self.removeButton.hide()

        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(self.iconLabel)
        top.addWidget(self.titleLabel, 1)
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
        self.removeButton.clicked.connect(self.uninstallClicked)

    def setApplication(self, app: dict, imagePath: str = "") -> None:
        self.appId = int(app["id"])
        self.appData = app
        self.titleLabel.setText(str(app.get("name", "")))
        self.titleLabel.setToolTip(str(app.get("name", "")))
        self.descriptionLabel.setText(str(app.get("description", "")))
        self.descriptionLabel.setToolTip(str(app.get("description", "")))
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

    def setState(self, text: str, removable: bool = False, enabled: bool = True) -> None:
        self.actionButton.setText(text)
        self.actionButton.setEnabled(enabled)
        self.removeButton.setVisible(removable)
        self.removeButton.setEnabled(enabled)

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

    def enterEvent(self, event):
        self.entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.left.emit()
        super().leaveEvent(event)


class AppStorePage(ScrollArea):
    pinnedCardsChanged = Signal(object)
    _downloadProgressSignal = Signal(int, int, int)
    _downloadRetrySignal = Signal(str)
    _downloadFinishedSignal = Signal(object, str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = ApplicationStore()
        self.catalog = []
        self.ads = []
        self.imagePaths = {}
        self.currentApp = None
        self.searchText = ""
        self._catalogLoading = False
        self._catalogThread = None
        self._catalogWorker = None
        self._shuttingDown = False
        self._downloadJobs = {}
        self._downloadStates = {}
        self._installing = set()
        self._installationThreads = set()
        self._installationLock = threading.Lock()
        self._pendingProgress = {}
        self._progressTimer = QTimer(self)
        self._progressTimer.setInterval(100)
        self._progressTimer.timeout.connect(self._flushDownloadProgress)
        self._currentPage = 0
        self._renderingAll = False
        self._downloadProgressSignal.connect(self._queueDownloadProgress)
        self._downloadRetrySignal.connect(self._showDownloadRetry)
        self._downloadFinishedSignal.connect(self._onDownloadFinished)
        self._installFinished.connect(self._onInstallFinished)
        self.setObjectName("AppStorePage")
        self._buildUi()

    def _buildUi(self):
        self.container = QWidget()
        self.rootLayout = QVBoxLayout(self.container)
        self.rootLayout.setContentsMargins(30, 24, 30, 36)
        self.rootLayout.setSpacing(12)

        self.pivot = Pivot(self.container)
        self.pivot.addItem("installed", "已安装", lambda: self._switchCatalogTab(0))
        self.pivot.addItem("all", "全部应用", lambda: self._switchCatalogTab(1))
        self.pivot.setCurrentItem("installed")

        header = QHBoxLayout()
        header.addWidget(self.pivot)
        header.addStretch(1)
        self.refreshButton = ToolButton(FIF.SYNC, self.container)
        self.refreshButton.setToolTip("刷新应用目录")
        self.refreshButton.clicked.connect(self._loadCatalog)
        header.addWidget(self.refreshButton)
        self.rootLayout.addLayout(header)

        self.stack = DrillInTransitionStackedWidget(self.container)
        self.overview = QWidget(self.stack)
        overviewLayout = QVBoxLayout(self.overview)
        overviewLayout.setContentsMargins(0, 0, 0, 0)
        self.installedTitle = BodyLabel("已安装的软件", self.overview)
        overviewLayout.addWidget(self.installedTitle)
        self.installedEmpty = BodyLabel("还没有已安装的应用。可以切换到“全部应用”开始下载。", self.overview)
        self.installedEmpty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overviewLayout.addWidget(self.installedEmpty)
        self.installedGridWidget, self.installedGrid = self._createGrid(self.overview)
        overviewLayout.addWidget(self.installedGridWidget)

        self.allPage = QWidget(self.stack)
        allLayout = QVBoxLayout(self.allPage)
        allLayout.setContentsMargins(0, 0, 0, 0)
        self.adFrame = AdvertisementFrame(self.allPage)
        self.adFrame.setMinimumHeight(238)
        self.adFrame.setMaximumHeight(300)
        adStack = QStackedLayout(self.adFrame)
        self.adFlipView = HorizontalFlipView(self.adFrame)
        self.adFlipView.setMouseTracking(True)
        adStack.addWidget(self.adFlipView)
        self.adOverlay = QWidget(self.adFrame)
        self.adOverlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.adOverlay.setStyleSheet(
            "background: qlineargradient(y1: 0, y2: 1, stop: 0 transparent, stop: 1 rgba(0,0,0,220));"
        )
        overlayLayout = QVBoxLayout(self.adOverlay)
        overlayLayout.setContentsMargins(20, 20, 20, 16)
        overlayLayout.addStretch(1)
        self.adTitle = SubtitleLabel(self.adOverlay)
        self.adTitle.setStyleSheet("color: white;")
        self.adDescription = BodyLabel(self.adOverlay)
        self.adDescription.setStyleSheet("color: rgba(255,255,255,220);")
        self.adDescription.setWordWrap(True)
        overlayLayout.addWidget(self.adTitle)
        overlayLayout.addWidget(self.adDescription)
        adActions = QHBoxLayout()
        self.adButton = PushButton("查看软件", self.adOverlay)
        self.adButton.clicked.connect(self._openAdApp)
        adActions.addWidget(self.adButton, 0, Qt.AlignmentFlag.AlignLeft)
        adActions.addStretch(1)
        self.adPrevious = ToolButton(FIF.LEFT_ARROW, self.adOverlay)
        self.adNext = ToolButton(FIF.RIGHT_ARROW, self.adOverlay)
        for button in (self.adPrevious, self.adNext):
            button.setStyleSheet("color: white; background: rgba(0,0,0,100); border-radius: 8px;")
        self.adPrevious.clicked.connect(self._previousAd)
        self.adNext.clicked.connect(self._nextAd)
        adActions.addWidget(self.adPrevious)
        adActions.addWidget(self.adNext)
        overlayLayout.addLayout(adActions)
        adStack.addWidget(self.adOverlay)
        self.adFrame.entered.connect(self._pauseAds)
        self.adFrame.left.connect(self._resumeAds)
        self.adTimer = QTimer(self)
        self.adTimer.setInterval(6000)
        self.adTimer.timeout.connect(self._nextAd)
        self.adFlipView.currentIndexChanged.connect(self._onAdChanged)
        allLayout.addWidget(self.adFrame)

        self.categoryPivot = Pivot(self.allPage)
        self.categoryPivot.addItem("recommended", "推荐", lambda: self._switchCategory(0))
        self.categoryPivot.addItem("all", "全部", lambda: self._switchCategory(1))
        self.categoryPivot.setCurrentItem("recommended")
        allLayout.addWidget(self.categoryPivot)
        self.allGridWidget, self.allGrid = self._createGrid(self.allPage)
        allLayout.addWidget(self.allGridWidget)
        self.pager = PipsPager(self.allPage)
        self.pager.currentIndexChanged.connect(self._onPageChanged)
        allLayout.addWidget(self.pager, 0, Qt.AlignmentFlag.AlignHCenter)

        self.stack.addWidget(self.overview)
        self.stack.addWidget(self.allPage)
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
        self.stack.setCurrentIndex(index)
        if index == 1:
            self._renderAll()
        else:
            self._renderInstalled()

    def _switchCategory(self, index: int):
        self._currentPage = 0
        self._renderAll()

    def setSearchText(self, text: str):
        self.searchText = text.strip().lower()
        if self.stack.currentIndex() == 0:
            self._renderInstalled()
        elif self.stack.currentIndex() == 1:
            self._renderAll()

    def showEvent(self, event):
        super().showEvent(event)
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
        self._catalogWorker = None
        self._catalogThread = None

        jobs = tuple(self._downloadJobs.items())
        for _appId, (thread, worker) in jobs:
            worker.cancel()
            thread.quit()
        for appId, (thread, worker) in jobs:
            if thread.isRunning():
                thread.wait()
            if self._downloadJobs.pop(appId, None) is not None:
                self.store.downloadSlots.release()
            self._downloadStates.pop(appId, None)
            for attribute in ("targetPath", "partialPath"):
                path = getattr(worker, attribute, None)
                if path:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except OSError:
                        pass

        with self._installationLock:
            installationThreads = tuple(self._installationThreads)
        for thread in installationThreads:
            thread.join()
        for _appId in tuple(self._installing):
            self.store.downloadSlots.release()
        self._installing.clear()

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
        thread.start()

    def _onCatalogLoaded(self, payload, imagePaths, error):
        self._catalogLoading = False
        self.refreshButton.setEnabled(True)
        self._catalogWorker = None
        self._catalogThread = None
        if self._shuttingDown:
            return
        if error:
            InfoBar.error("应用目录加载失败", error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.catalog = list(payload.get("apps", []))
        self.ads = list(payload.get("ads", []))
        self.imagePaths = dict(imagePaths)
        self._prepareAds()
        self._renderInstalled()
        self._renderAll()
        if self.currentApp:
            current = next((app for app in self._mergedApps() if app["id"] == self.currentApp["id"]), None)
            if current:
                self._showDetail(current)

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
                item.widget().deleteLater()

    def _columnCount(self, layout):
        width = layout.parentWidget().width()
        if width >= 900:
            return 3
        if width >= 640:
            return 2
        return 1

    @staticmethod
    def _setGridColumns(layout, columns):
        for column in range(3):
            layout.setColumnStretch(column, 1 if column < columns else 0)

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
        card.setState(actionText, installedPage, enabled)

    def _renderGrid(self, layout, apps, installedPage=False):
        self._clearGrid(layout)
        columns = self._columnCount(layout)
        for index, app in enumerate(apps):
            card = ApplicationCard(self)
            card.setApplication(app, self.imagePaths.get(app.get("icon_url", ""), ""))
            card.installedPage = installedPage
            self._setCardState(card, app, installedPage)
            card.clicked.connect(lambda appData=app: self._showDetail(appData))
            card.actionClicked.connect(lambda _checked=False, appData=app: self._onAppAction(appData))
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
        columns = self._columnCount(layout)
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

    def _updateVisibleCardState(self, appId):
        for card in self.container.findChildren(ApplicationCard):
            if card.appId == appId:
                self._setCardState(card, card.appData, card.installedPage)

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
            pageCount = max(1, (len(apps) + 14) // 15)
            if self.pager.count() != pageCount:
                self.pager.setPageNumber(pageCount)
            self._currentPage = min(self._currentPage, pageCount - 1)
            if self.pager.currentIndex() != self._currentPage:
                self.pager.setCurrentIndex(self._currentPage)
            self.pager.setVisible(pageCount > 1)
            self._renderAllPage(apps)
        finally:
            self.pager.blockSignals(False)
            self._renderingAll = False

    def _renderAllPage(self, apps=None):
        apps = self._allAppsForPage() if apps is None else apps
        self._renderGrid(self.allGrid, apps[self._currentPage * 15 : (self._currentPage + 1) * 15])

    def _onPageChanged(self, index):
        if self._renderingAll:
            return
        self._currentPage = index
        self._renderAllPage()

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
        self.adFrame.show()
        self._onAdChanged(0)
        self._resumeAds()

    def _onAdChanged(self, index):
        if not self.ads:
            return
        index = max(0, min(index, len(self.ads) - 1))
        ad = self.ads[index]
        self.adTitle.setText(str(ad.get("title", "")))
        self.adDescription.setText(str(ad.get("description", "")))
        self.adButton.setVisible(bool(ad.get("app_id")))

    def _nextAd(self):
        if self.ads:
            self.adFlipView.setCurrentIndex((self.adFlipView.currentIndex() + 1) % len(self.ads))

    def _previousAd(self):
        if self.ads:
            self.adFlipView.setCurrentIndex((self.adFlipView.currentIndex() - 1) % len(self.ads))

    def _openAdApp(self):
        if not self.ads:
            return
        appId = self.ads[self.adFlipView.currentIndex()].get("app_id")
        app = next((item for item in self._mergedApps() if item["id"] == appId), None)
        if app:
            self._showDetail(app)

    def _pauseAds(self):
        self.adTimer.stop()

    def _resumeAds(self):
        if self.isVisible() and self.ads:
            self.adTimer.start()

    def _showDetail(self, app):
        self.currentApp = app
        self.pivot.hide()
        self.stack.setCurrentWidget(self.detail)
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
        target = 0 if self.pivot.currentRouteKey() == "installed" else 1
        self.stack.setCurrentIndex(target, isBack=True)
        if target == 0:
            self._renderInstalled()
        else:
            self._renderAll()

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
        if appId in self._downloadJobs or appId in self._installing:
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
        thread = QThread(self)
        worker.moveToThread(thread)
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
        thread.started.connect(worker.run)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
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
        with self._installationLock:
            self._installationThreads.add(thread)
        thread.start()

    def _installInBackground(self, app, path):
        try:
            installed = self.store.installZip(app, path)
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
            with self._installationLock:
                self._installationThreads.discard(threading.current_thread())

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
        if appId in self._downloadJobs or appId in self._installing:
            return
        box = MessageBox("确认卸载", f"将删除 {app.get('name', '')} 的安装目录，是否继续？", self)
        if not box.exec():
            return
        try:
            local = self.store.installed().get(int(app["id"]))
            self.store.uninstall(local or app)
        except (ApplicationStoreError, OSError) as error:
            InfoBar.error("卸载失败", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
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
            (int(item.get("app_id")), int(item.get("preset_id")))
            for item in cfg.pinnedHomeCards.value
            if isinstance(item, dict) and item.get("app_id") is not None and item.get("preset_id") is not None
        }

    def _togglePin(self, app, preset):
        cards = [dict(item) for item in cfg.pinnedHomeCards.value if isinstance(item, dict)]
        key = (int(app["id"]), int(preset["id"]))
        existing = next((item for item in cards if (int(item.get("app_id", -1)), int(item.get("preset_id", -1))) == key), None)
        if existing:
            cards.remove(existing)
        else:
            cards.append(
                {
                    "app_id": key[0],
                    "preset_id": key[1],
                    "title": preset.get("title", ""),
                    "description": preset.get("description", ""),
                    "action": preset.get("action"),
                    "install_dir": app.get("install_dir", ""),
                    "icon_url": app.get("icon_url", ""),
                    "icon_path": self.imagePaths.get(app.get("icon_url", ""), ""),
                }
            )
        cfg.set(cfg.pinnedHomeCards, cards)
        self.pinnedCardsChanged.emit(cards)
        self._renderPresets(app)

    def executePinnedCard(self, item):
        appId = int(item.get("app_id", -1))
        installed = self.store.installed().get(appId)
        if not installed:
            InfoBar.warning("应用尚未安装", "请先安装对应应用后再使用主页预设卡片。", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        try:
            self.store.executeAction(installed, item.get("action"))
        except (ApplicationStoreError, OSError) as error:
            InfoBar.error("执行预设失败", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def refreshPinnedCards(self):
        cards = []
        for item in cfg.pinnedHomeCards.value:
            if isinstance(item, dict):
                cards.append(dict(item))
        self.pinnedCardsChanged.emit(cards)
