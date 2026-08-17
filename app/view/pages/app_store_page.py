import threading
import time
from queue import Empty, PriorityQueue, Queue
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScroller,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    HorizontalFlipView,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PipsPager,
    Pivot,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    ToggleToolButton,
    ToolButton,
    TransitionStackedWidget,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.application_store import (
    ApplicationStore,
    ApplicationStoreError,
    beginAppStorePackageOperation,
    downloadWorker,
    endAppStorePackageOperation,
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
QWIDGETSIZE_MAX = (1 << 24) - 1
_packageOperationReleaseLock = threading.Lock()


def _releasePackageOperation(downloadSlots):
    with _packageOperationReleaseLock:
        downloadSlots.release()
        endAppStorePackageOperation()


def _deferPackageOperationRelease(thread, downloadSlots):
    def releaseAfterExit():
        thread.join()
        _releasePackageOperation(downloadSlots)

    threading.Thread(
        target=releaseAfterExit,
        daemon=True,
        name="app-store-package-reaper",
    ).start()


class HorizontalTransitionStackedWidget(TransitionStackedWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._currentSlide = QPropertyAnimation(self._currentSnapshot, b"pos", self)
        self._nextSlide = QPropertyAnimation(self._nextSnapshot, b"pos", self)
        self._currentFade = QPropertyAnimation(
            self._currentSnapshot.graphicsEffect(), b"opacity", self
        )
        self._nextFade = QPropertyAnimation(
            self._nextSnapshot.graphicsEffect(), b"opacity", self
        )
        for animation in (
            self._currentSlide,
            self._nextSlide,
            self._currentFade,
            self._nextFade,
        ):
            self._aniGroup.addAnimation(animation)

    def setCurrentIndex(self, index, duration=None, isBack=False):
        if index < 0 or index >= self.count():
            return
        if self._aniGroup.state() == QAbstractAnimation.State.Running:
            if index == self._nextIndex:
                return
            self._stopAnimation()
        super().setCurrentIndex(index, duration, isBack)

    def _setUpTransitionAnimation(self, nextIndex, duration, isBack):
        current = self.currentWidget()
        nextWidget = self.widget(nextIndex)
        if current is None or nextWidget is None:
            return
        self._renderSnapshot(current, self._currentSnapshot)
        self._renderSnapshot(nextWidget, self._nextSnapshot)
        current.hide()
        nextWidget.hide()

        direction = -1 if isBack else (1 if nextIndex > self.currentIndex() else -1)
        offset = max(48, min(120, self.width() // 8))
        animationDuration = duration or 180
        curve = QEasingCurve(QEasingCurve.Type.OutCubic)
        for animation in (
            self._currentSlide,
            self._nextSlide,
            self._currentFade,
            self._nextFade,
        ):
            animation.setDuration(animationDuration)
            animation.setEasingCurve(curve)

        self._currentSnapshot.move(0, 0)
        self._nextSnapshot.move(direction * offset, 0)
        self._currentSlide.setStartValue(QPoint(0, 0))
        self._currentSlide.setEndValue(QPoint(-direction * offset, 0))
        self._nextSlide.setStartValue(QPoint(direction * offset, 0))
        self._nextSlide.setEndValue(QPoint(0, 0))
        self._currentFade.setStartValue(1.0)
        self._currentFade.setEndValue(0.0)
        self._nextFade.setStartValue(0.35)
        self._nextFade.setEndValue(1.0)

    def _onAniFinished(self):
        super()._onAniFinished()
        self._currentSnapshot.clear()
        self._nextSnapshot.clear()

    def resizeEvent(self, event):
        self._stopAnimation()
        super().resizeEvent(event)


class CatalogWorker(QObject):
    finished = Signal(object, object, str)
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
        except Exception as error:
            if not self._cancelEvent.is_set():
                self.finished.emit({}, {}, str(error))
        finally:
            self.completed.emit()


class CatalogImageWorker(QObject):
    imageLoaded = Signal(str, str)
    completed = Signal()
    # New catalog generations must not wait behind canceled pages' queued URLs.
    _jobs = PriorityQueue()
    _poolLock = threading.Lock()
    _poolThreads = set()
    _threadSequence = 0
    _generationSequence = 0
    _jobSequence = 0
    _poolSize = 4
    _poolIdleTimeout = 0.5

    def __init__(self, store: ApplicationStore, urls):
        super().__init__()
        self.store = store
        self.urls = tuple(
            dict.fromkeys(
                url for url in urls if isinstance(url, str) and url
            )
        )
        self._cancelEvent = threading.Event()
        with self._poolLock:
            type(self)._generationSequence += 1
            self._generation = type(self)._generationSequence

    def cancel(self):
        self._cancelEvent.set()

    @classmethod
    def _ensurePool(cls):
        with cls._poolLock:
            cls._poolThreads = {
                thread for thread in cls._poolThreads if thread.is_alive()
            }
            while len(cls._poolThreads) < cls._poolSize:
                cls._threadSequence += 1
                thread = threading.Thread(
                    target=cls._consume,
                    daemon=True,
                    name=f"app-store-image-{cls._threadSequence}",
                )
                cls._poolThreads.add(thread)
                try:
                    thread.start()
                except Exception:
                    cls._poolThreads.discard(thread)
                    raise

    @classmethod
    def _consume(cls):
        current = threading.current_thread()
        while True:
            try:
                _priority, _jobSequence, store, url, cancelEvent, results = cls._jobs.get(
                    timeout=cls._poolIdleTimeout
                )
            except Empty:
                with cls._poolLock:
                    cls._poolThreads.discard(current)
                return
            try:
                result = None
                if not cancelEvent.is_set():
                    try:
                        result = url, str(store.imagePath(url))
                    except Exception:
                        pass
                if not cancelEvent.is_set():
                    results.put(result)
            finally:
                cls._jobs.task_done()
                store = url = cancelEvent = results = None

    def run(self):
        try:
            if not self.urls:
                return
            results = Queue()
            for url in self.urls:
                with self._poolLock:
                    type(self)._jobSequence += 1
                    jobSequence = type(self)._jobSequence
                self._jobs.put(
                    (
                        -self._generation,
                        jobSequence,
                        self.store,
                        url,
                        self._cancelEvent,
                        results,
                    )
                )
            self._ensurePool()

            completed = 0
            while completed < len(self.urls):
                if self._cancelEvent.is_set():
                    return
                try:
                    result = results.get(timeout=0.05)
                except Empty:
                    continue
                completed += 1
                if result is not None and not self._cancelEvent.is_set():
                    self.imageLoaded.emit(*result)
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
        self.descriptionLabel.setText(str(app.get("description", "")))
        self.setImage(imagePath)

    def setImage(self, imagePath: str = "") -> None:
        if imagePath and Path(imagePath).exists():
            source = QPixmap(imagePath)
            if not source.isNull():
                self.iconLabel.setPixmap(
                    source.scaled(
                        54,
                        54,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                return
        self.iconLabel.setPixmap(FIF.APPLICATION.icon().pixmap(QSize(32, 32)))

    def setState(
        self,
        text: str,
        removable: bool = False,
        enabled: bool = True,
        pinnable: bool = False,
        pinned: bool = False,
        removeEnabled: bool | None = None,
    ) -> None:
        if removeEnabled is None:
            removeEnabled = enabled
        self.actionButton.setText(text)
        self.actionButton.setEnabled(enabled)
        self.removeButton.setVisible(removable)
        self.removeButton.setEnabled(removeEnabled)
        self.pinButton.setVisible(removable)
        self.pinButton.setEnabled((enabled and pinnable) or pinned)
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
        return QSize(1000, 190)

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
        self._touchAxis = None
        self._touchButton = None
        self._scrollBar = None
        self._scrollStart = 0
        self._touchButtons = ()
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)

    def setTouchButtons(self, buttons):
        self._touchButtons = tuple(buttons)

    def _buttonAt(self, position):
        child = self.childAt(position)
        while child is not None and child is not self:
            if isinstance(child, QAbstractButton):
                return child
            child = child.parentWidget()
        globalPosition = self.mapToGlobal(position)
        for button in self._touchButtons:
            if button.isEnabled() and button.rect().contains(
                button.mapFromGlobal(globalPosition)
            ):
                return button
        return None

    def _outerScrollBar(self):
        scrollArea = None
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QAbstractScrollArea):
                scrollArea = parent
            parent = parent.parentWidget()
        return scrollArea.verticalScrollBar() if scrollArea else None

    def eventFilter(self, obj, event):
        if event.type() not in (
            QEvent.Type.TouchBegin,
            QEvent.Type.TouchUpdate,
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        ):
            return False
        if not self.isVisible() and self._pressPosition is None:
            return False
        if not event.points():
            return self.event(event) if self._pressPosition is not None else False
        position = self.mapFromGlobal(
            event.points()[0].globalPosition().toPoint()
        )
        if self._pressPosition is None and not self.rect().contains(position):
            return False
        return self.event(event)

    def event(self, event):
        if event.type() == QEvent.Type.TouchBegin and event.points():
            position = self.mapFromGlobal(
                event.points()[0].globalPosition().toPoint()
            )
            self._pressPosition = position
            self._touchAxis = None
            self._touchButton = self._buttonAt(position)
            if self._touchButton is not None:
                self._touchButton.setDown(True)
            self._scrollBar = self._outerScrollBar()
            self._scrollStart = self._scrollBar.value() if self._scrollBar else 0
            event.accept()
            return True
        if event.type() == QEvent.Type.TouchUpdate and event.points():
            if self._pressPosition is None:
                return super().event(event)
            position = self.mapFromGlobal(
                event.points()[0].globalPosition().toPoint()
            )
            delta = position - self._pressPosition
            if self._touchButton is not None:
                if delta.manhattanLength() < QApplication.startDragDistance():
                    self._touchButton.setDown(
                        self._buttonAt(position) is self._touchButton
                    )
                    event.accept()
                    return True
                self._touchButton.setDown(False)
                self._touchButton = None
            if self._touchAxis is None:
                if delta.manhattanLength() < QApplication.startDragDistance():
                    event.accept()
                    return True
                self._touchAxis = (
                    "horizontal"
                    if abs(delta.x()) >= abs(delta.y())
                    else "vertical"
                )
            if self._touchAxis == "vertical" and self._scrollBar is not None:
                self._scrollBar.setValue(self._scrollStart - delta.y())
            event.accept()
            return True
        if event.type() in (QEvent.Type.TouchEnd, QEvent.Type.TouchCancel):
            position = (
                self.mapFromGlobal(
                    event.points()[0].globalPosition().toPoint()
                )
                if event.points()
                else self._pressPosition
            )
            if self._touchButton is not None:
                button = self._touchButton
                shouldClick = (
                    event.type() == QEvent.Type.TouchEnd and button.isDown()
                )
                button.setDown(False)
                if shouldClick:
                    button.click()
            elif (
                event.type() == QEvent.Type.TouchEnd
                and self._touchAxis == "horizontal"
                and position is not None
                and self._pressPosition is not None
            ):
                distance = position.x() - self._pressPosition.x()
                if abs(distance) >= QApplication.startDragDistance():
                    (
                        self.previousRequested
                        if distance > 0
                        else self.nextRequested
                    ).emit()
            self._pressPosition = None
            self._touchAxis = None
            self._touchButton = None
            self._scrollBar = None
            event.accept()
            return True
        return super().event(event)

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
    _launchFailed = Signal(str)
    _downloadProgressSignal = Signal(int, int, int)
    _downloadRetrySignal = Signal(str)
    _downloadFinishedSignal = Signal(object, str, str, bool)
    _uninstallFinished = Signal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._launchFailed.connect(self._onLaunchFailed)
        self.store = ApplicationStore(onLaunchFailure=self._launchFailed.emit)
        self._catalog = []
        self._mergedCatalog = None
        self.ads = []
        self.imagePaths = {}
        self.currentApp = None
        self.searchText = ""
        self._catalogLoading = False
        self._catalogLoaded = False
        self._catalogThread = None
        self._catalogWorker = None
        self._imageJobs = {}
        self._shuttingDown = False
        self._downloadJobs = {}
        self._downloadStates = {}
        self._installing = set()
        self._installThreads = {}
        self._uninstalling = set()
        self._presetActionButtons = []
        self._fileOperationThreads = set()
        self._fileOperationLock = threading.Lock()
        self._installationCancelEvent = threading.Event()
        self._pendingProgress = {}
        self._progressTimer = QTimer(self)
        self._progressTimer.setInterval(100)
        self._progressTimer.timeout.connect(self._flushDownloadProgress)
        self._layoutTimer = QTimer(self)
        self._layoutTimer.setSingleShot(True)
        self._layoutTimer.setInterval(8)
        self._layoutTimer.timeout.connect(self._applyLayoutUpdate)
        self._adSyncTimer = QTimer(self)
        self._adSyncTimer.setSingleShot(True)
        self._adSyncTimer.timeout.connect(self._syncAdImageSize)
        self._viewportUpdateTimer = QTimer(self)
        self._viewportUpdateTimer.setSingleShot(True)
        self._viewportUpdateTimer.timeout.connect(self._finishViewportUpdate)
        self._currentPage = 0
        self._catalogScrollPosition = 0
        self._renderingAll = False
        self._viewportUpdatePending = False
        self._frozenScrollPosition = 0
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

        self.stack = HorizontalTransitionStackedWidget(self.container)
        self.catalogPage = QWidget(self.stack)
        catalogLayout = QVBoxLayout(self.catalogPage)
        catalogLayout.setContentsMargins(0, 0, 0, 0)
        self.catalogStack = HorizontalTransitionStackedWidget(self.catalogPage)
        catalogLayout.addWidget(self.catalogStack)

        self.overview = QWidget(self.catalogStack)
        overviewLayout = QVBoxLayout(self.overview)
        overviewLayout.setContentsMargins(0, 0, 0, 0)
        overviewLayout.setSpacing(8)
        overviewLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.installedTitle = BodyLabel("已安装的软件", self.overview)
        overviewLayout.addWidget(self.installedTitle)
        self.installedEmpty = CardWidget(self.overview)
        self.installedEmpty.setMinimumHeight(220)
        emptyLayout = QVBoxLayout(self.installedEmpty)
        emptyLayout.setContentsMargins(24, 28, 24, 28)
        emptyLayout.setSpacing(10)
        emptyLayout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.installedEmptyIcon = QLabel(self.installedEmpty)
        self.installedEmptyIcon.setFixedSize(64, 64)
        self.installedEmptyIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.installedEmptyIcon.setPixmap(
            FIF.APPLICATION.icon().pixmap(QSize(48, 48))
        )
        self.installedEmptyTitle = SubtitleLabel(
            "还没有已安装的应用", self.installedEmpty
        )
        self.installedEmptyDescription = BodyLabel(
            "去全部应用看看，安装后可以在这里快速打开、更新或固定到主页。",
            self.installedEmpty,
        )
        self.installedEmptyDescription.setWordWrap(True)
        self.installedEmptyDescription.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.installedEmptyButton = PrimaryPushButton(
            "浏览全部应用", self.installedEmpty
        )
        self.installedEmptyButton.setMinimumHeight(40)
        self.installedEmptyButton.clicked.connect(self._handleInstalledEmptyAction)
        emptyLayout.addWidget(
            self.installedEmptyIcon, 0, Qt.AlignmentFlag.AlignHCenter
        )
        emptyLayout.addWidget(
            self.installedEmptyTitle, 0, Qt.AlignmentFlag.AlignHCenter
        )
        emptyLayout.addWidget(self.installedEmptyDescription)
        emptyLayout.addWidget(
            self.installedEmptyButton, 0, Qt.AlignmentFlag.AlignHCenter
        )
        overviewLayout.addWidget(self.installedEmpty)
        self.installedGridWidget, self.installedGrid = self._createGrid(self.overview)
        overviewLayout.addWidget(self.installedGridWidget)

        self.allPage = QWidget(self.catalogStack)
        allLayout = QVBoxLayout(self.allPage)
        allLayout.setContentsMargins(0, 0, 0, 0)
        allLayout.setSpacing(8)
        allLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.adFrame = AdvertisementFrame(self.allPage)
        self.adFrame.setMinimumHeight(170)
        self.adFrame.setMaximumHeight(200)
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
        QScroller.ungrabGesture(self.adFlipView.viewport())
        adLayout.addWidget(self.adFlipView)
        self.adOverlay = AdvertisementOverlay(self.adFlipView)
        for touchTarget in (
            self.viewport(),
            self.adFlipView,
            self.adFlipView.viewport(),
        ):
            touchTarget.installEventFilter(self.adOverlay)
        QApplication.instance().installEventFilter(self.adOverlay)
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
        overlayLayout.setContentsMargins(52, 0, 52, 10)
        overlayLayout.setSpacing(4)
        overlayLayout.addStretch(1)
        self.adTitle = SubtitleLabel(self.adOverlay)
        self.adTitle.setStyleSheet("color: white;")
        self.adDescription = BodyLabel(self.adOverlay)
        self.adDescription.setStyleSheet("color: rgba(255,255,255,220);")
        self.adDescription.setWordWrap(True)
        self.adTitle.setFixedHeight(self.adTitle.fontMetrics().lineSpacing())
        self.adDescription.setFixedHeight(
            self.adDescription.fontMetrics().lineSpacing() * 2
        )
        self._adTitleElide = LabelElideFilter(maximumLines=1)
        self._adDescriptionElide = LabelElideFilter(maximumLines=2)
        self.adTitle.installEventFilter(self._adTitleElide)
        self.adDescription.installEventFilter(self._adDescriptionElide)
        overlayLayout.addWidget(self.adTitle)
        overlayLayout.addWidget(self.adDescription)
        self.adButton = PrimaryPushButton("查看软件", self.adOverlay)
        self.adButton.setFixedHeight(32)
        self.adButton.clicked.connect(self._openAdApp)
        overlayLayout.addWidget(self.adButton, 0, Qt.AlignmentFlag.AlignLeft)
        self.adPrevious = self.adFlipView.preButton
        self.adNext = self.adFlipView.nextButton
        self.adOverlay.setTouchButtons((self.adPrevious, self.adNext))
        for button in (self.adPrevious, self.adNext):
            button.setFixedSize(32, 32)
        self.adOverlay.previousRequested.connect(self._previousAd)
        self.adOverlay.nextRequested.connect(self._nextAd)
        self.adFrame.entered.connect(self._pauseAds)
        self.adFrame.left.connect(self._resumeAds)
        self.adFrame.resized.connect(self._adSyncTimer.start)
        self.adTimer = QTimer(self)
        self.adTimer.setInterval(5000)
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
        self.pagerPrevious.clicked.connect(lambda: self._changePage(-1))
        pagerLayout.addWidget(self.pagerPrevious)
        self.pager = PipsPager(self.pagerBar)
        self.pager.currentIndexChanged.connect(self._onPageChanged)
        pagerLayout.addWidget(self.pager)
        self.pagerNext = ToolButton(FIF.RIGHT_ARROW, self.pagerBar)
        self.pagerNext.setFixedSize(40, 40)
        self.pagerNext.clicked.connect(lambda: self._changePage(1))
        pagerLayout.addWidget(self.pagerNext)
        allLayout.addWidget(self.pagerBar, 0, Qt.AlignmentFlag.AlignHCenter)

        self.catalogStack.addWidget(self.overview)
        self.catalogStack.addWidget(self.allPage)
        self.catalogStack.aniFinished.connect(self._resumeAds)
        self.stack.addWidget(self.catalogPage)
        self.rootLayout.addWidget(self.stack)

        self.detail = QWidget(self.stack)
        self._buildDetail()
        self.stack.addWidget(self.detail)
        self.stack.aniFinished.connect(self._restoreCatalogScroll)
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self.adFrame.hide()
        self._renderInstalled()

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
        layout.setSpacing(8)
        back = PushButton(FIF.LEFT_ARROW, "返回应用列表", self.detail)
        back.setMinimumHeight(40)
        back.clicked.connect(self._backToOverview)
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        columns = QHBoxLayout()
        columns.setSpacing(16)

        self.detailLeftScroll = ScrollArea(self.detail)
        self.detailLeftScroll.setWidgetResizable(True)
        self.detailLeftScroll.setMinimumWidth(220)
        self.detailLeftScroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.detailLeftScroll.enableTransparentBackground()
        self.detailLeft = QFrame()
        leftLayout = QVBoxLayout(self.detailLeft)
        leftLayout.setContentsMargins(8, 8, 16, 8)
        leftLayout.setSpacing(8)
        self.detailIcon = QLabel(self.detailLeft)
        self.detailIcon.setFixedSize(112, 112)
        self.detailIcon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detailName = TitleLabel(self.detailLeft)
        self.detailName.setWordWrap(True)
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
        self.detailLeftScroll.setWidget(self.detailLeft)
        columns.addWidget(self.detailLeftScroll, 1)

        self.presetScroll = ScrollArea(self.detail)
        self.presetScroll.setWidgetResizable(True)
        self.presetScroll.setMinimumWidth(300)
        self.presetScroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.presetScroll.enableTransparentBackground()
        self.presetPanel = QFrame()
        presetLayout = QVBoxLayout(self.presetPanel)
        presetLayout.setContentsMargins(8, 8, 8, 8)
        presetLayout.setSpacing(10)
        presetLayout.addWidget(SubtitleLabel("主页预设卡片", self.presetPanel))
        self.announcementLabel = QLabel(self.presetPanel)
        self.announcementLabel.setWordWrap(True)
        self.announcementLabel.setStyleSheet(
            "padding: 10px 12px; border-radius: 8px; background: #fff4e6; color: #8a4b08;"
        )
        presetLayout.addWidget(self.announcementLabel)

        self.presetGroup = CardWidget(self.presetPanel)
        groupLayout = QVBoxLayout(self.presetGroup)
        groupLayout.setContentsMargins(16, 4, 16, 4)
        groupLayout.setSpacing(0)
        self.presetCards = QVBoxLayout()
        self.presetCards.setContentsMargins(0, 0, 0, 0)
        self.presetCards.setSpacing(0)
        groupLayout.addLayout(self.presetCards)
        presetLayout.addWidget(self.presetGroup)
        presetLayout.addStretch(1)
        self.presetScroll.setWidget(self.presetPanel)
        columns.addWidget(self.presetScroll, 2)
        layout.addLayout(columns, 1)

    def _switchCatalogTab(self, index: int):
        self._beginViewportUpdate(0)
        if index == 1:
            self._renderAll()
            self._resumeAds()
        else:
            self._pauseAds()
            self._renderInstalled()
        self.catalogStack.setCurrentIndex(
            index,
            isBack=index < self.catalogStack.currentIndex(),
        )

    def _switchCategory(self, index: int):
        self._beginViewportUpdate()
        self._currentPage = 0
        self._renderAll()

    def _showAllApplications(self):
        searchEdit = getattr(self.window(), "searchEdit", None)
        if searchEdit is not None:
            searchEdit.clear()
        else:
            self.setSearchText("")
        self.pivot.setCurrentItem("all")
        self._switchCatalogTab(1)

    def _handleInstalledEmptyAction(self):
        if self.searchText:
            searchEdit = getattr(self.window(), "searchEdit", None)
            if searchEdit is not None:
                searchEdit.clear()
            else:
                self.setSearchText("")
            return
        self._showAllApplications()

    def _beginViewportUpdate(self, scrollPosition=None):
        scroller = QScroller.scroller(self.viewport())
        if scroller is not None:
            scroller.stop()
        if scrollPosition is not None or not self._viewportUpdatePending:
            self._frozenScrollPosition = (
                self.verticalScrollBar().value()
                if scrollPosition is None
                else scrollPosition
            )
        if self._viewportUpdatePending:
            return
        self._viewportUpdatePending = True
        self.viewport().setUpdatesEnabled(False)
        self._viewportUpdateTimer.start(0)

    def _finishViewportUpdate(self):
        if self._shuttingDown:
            self._viewportUpdatePending = False
            return
        self.rootLayout.activate()
        scrollBar = self.verticalScrollBar()
        scrollBar.setValue(min(self._frozenScrollPosition, scrollBar.maximum()))
        self.viewport().setUpdatesEnabled(True)
        self.viewport().update()
        self._viewportUpdatePending = False

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
        self.store.shutdown()
        self._viewportUpdateTimer.stop()
        self._progressTimer.stop()
        self._pendingProgress.clear()
        self._catalogLoading = False
        catalogThread = self._catalogThread
        if self._catalogWorker is not None:
            self._catalogWorker.cancel()
        imageJobs = tuple(self._imageJobs.items())
        for worker, _thread in imageJobs:
            worker.cancel()

        jobs = tuple(self._downloadJobs.items())
        for _appId, (thread, worker) in jobs:
            worker.cancel()
        self._installationCancelEvent.set()
        with self._fileOperationLock:
            fileOperationThreads = tuple(self._fileOperationThreads)
            installThreads = dict(self._installThreads)

        deadline = time.monotonic() + SHUTDOWN_WAIT_SECONDS
        threads = [thread for _appId, (thread, _worker) in jobs]
        if catalogThread is not None:
            threads.insert(0, catalogThread)
        threads.extend(thread for _worker, thread in imageJobs)
        threads.extend(fileOperationThreads)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(max(0, deadline - time.monotonic()))

        if catalogThread is None or not catalogThread.is_alive():
            self._catalogWorker = None
            self._catalogThread = None
        self._imageJobs.clear()

        for appId, (thread, worker) in jobs:
            threadAlive = thread.is_alive()
            if self._downloadJobs.pop(appId, None) is not None:
                if threadAlive:
                    _deferPackageOperationRelease(
                        thread,
                        self.store.downloadSlots,
                    )
                else:
                    _releasePackageOperation(self.store.downloadSlots)
            self._downloadStates.pop(appId, None)
            if threadAlive:
                continue
            for attribute in ("targetPath", "partialPath"):
                path = getattr(worker, attribute, None)
                if path:
                    try:
                        Path(path).unlink(missing_ok=True)
                    except OSError:
                        pass

        for appId in tuple(self._installing):
            thread = installThreads.get(appId)
            if thread is not None and thread.is_alive():
                _deferPackageOperationRelease(
                    thread,
                    self.store.downloadSlots,
                )
            else:
                _releasePackageOperation(self.store.downloadSlots)
        self._installing.clear()
        with self._fileOperationLock:
            self._installThreads.clear()
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
        worker.completed.connect(self._onCatalogCompleted)
        thread.start()

    def _onCatalogLoaded(self, payload, imagePaths, error):
        if self._shuttingDown:
            return
        if error:
            self._mergedCatalog = None
            self._renderInstalled()
            InfoBar.error("应用目录加载失败", error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._catalogLoaded = True
        apps = payload.get("apps")
        self.catalog = []
        for app in apps if isinstance(apps, list) else ():
            if not isinstance(app, dict):
                continue
            app = dict(app)
            if not isinstance(app.get("icon_url"), str):
                app["icon_url"] = ""
            self.catalog.append(app)
        self._mergedCatalog = None
        ads = payload.get("ads")
        self.ads = []
        for ad in ads if isinstance(ads, list) else ():
            if not isinstance(ad, dict):
                continue
            ad = dict(ad)
            if not isinstance(ad.get("image_url"), str):
                ad["image_url"] = ""
            self.ads.append(ad)
        self.imagePaths.update(imagePaths)
        self._startCatalogImages(payload)
        self._syncPinnedMetadata()
        self._prepareAds()
        self._renderInstalled()
        self._renderAll()
        if self.currentApp:
            current = next((app for app in self._mergedApps() if app["id"] == self.currentApp["id"]), None)
            if current:
                self._showDetail(current)
            else:
                self._backToOverview()

    def _startCatalogImages(self, payload):
        apps = payload.get("apps") if isinstance(payload.get("apps"), list) else []
        ads = payload.get("ads") if isinstance(payload.get("ads"), list) else []
        urls = [
            item.get("icon_url", "")
            for item in apps
            if isinstance(item, dict)
        ]
        urls.extend(
            item.get("image_url", "")
            for item in ads
            if isinstance(item, dict)
        )
        worker = CatalogImageWorker(self.store, urls)
        if not worker.urls:
            worker.deleteLater()
            return
        for previous in tuple(self._imageJobs):
            previous.cancel()
        thread = threading.Thread(target=worker.run, daemon=True)
        self._imageJobs[worker] = thread
        worker.imageLoaded.connect(self._onCatalogImageLoaded)
        worker.completed.connect(self._onCatalogImagesCompleted)
        thread.start()

    def _onCatalogImagesCompleted(self):
        worker = self.sender()
        self._imageJobs.pop(worker, None)
        worker.deleteLater()

    def _onCatalogImageLoaded(self, url, path):
        if self._shuttingDown:
            return
        self.imagePaths[url] = path
        for card in self.container.findChildren(ApplicationCard):
            if card.appData.get("icon_url") == url:
                card.setImage(path)

        if self.currentApp and self.currentApp.get("icon_url") == url:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.detailIcon.setPixmap(
                    pixmap.scaled(
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

    def _syncPinnedMetadata(self):
        cards = normalize_pinned_cards(cfg.pinnedHomeCards.value)
        if not cards:
            return
        apps = {int(app["id"]): app for app in self._mergedApps()}
        changed = cards != cfg.pinnedHomeCards.value
        for card in cards:
            app = apps.get(card["app_id"])
            if app is None:
                continue
            source = app
            if card["preset_id"] != DIRECT_APPLICATION_PRESET_ID:
                source = next(
                    (
                        preset
                        for preset in app.get("presets", []) or []
                        if str(preset.get("id", "")) == str(card["preset_id"])
                    ),
                    None,
                )
                if source is None:
                    continue
            values = {
                "title": (
                    source.get("name", "")
                    if source is app
                    else source.get("title", "")
                ),
                "description": source.get("description", ""),
                "install_dir": app.get("install_dir", ""),
                "icon_url": app.get("icon_url", ""),
                "icon_path": self.imagePaths.get(
                    app.get("icon_url", ""), card.get("icon_path", "")
                ),
            }
            for key, value in values.items():
                if card.get(key) != value:
                    card[key] = value
                    changed = True
        if changed:
            cfg.set(cfg.pinnedHomeCards, cards)
            self.pinnedCardsChanged.emit(cards)

    @property
    def catalog(self):
        return self._catalog

    @catalog.setter
    def catalog(self, apps):
        self._catalog = list(apps)
        self._mergedCatalog = None

    def _mergedApps(self):
        if self._mergedCatalog is None:
            self._mergedCatalog = self.store.mergeInstalled(self.catalog)
        return self._mergedCatalog

    def _filtered(self, apps):
        if not self.searchText:
            return list(apps)
        return [
            app for app in apps
            if self.searchText in str(app.get("name", "")).lower()
            or self.searchText in str(app.get("description", "")).lower()
            or self.searchText in str(app.get("developer", "")).lower()
        ]

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
        hasOpenAction = isinstance(self._installedOpenAction(app), dict)
        if state:
            actionText = state
            enabled = False
        elif app.get("update_available"):
            actionText = "更新"
            enabled = supported
        elif app.get("installed"):
            actionText = "打开" if hasOpenAction else "未配置打开动作"
            enabled = hasOpenAction
        else:
            actionText = "下载" if supported else "不支持"
            enabled = supported
        directKey = (appId, DIRECT_APPLICATION_PRESET_ID)
        card.setState(
            actionText,
            installedPage,
            enabled,
            hasOpenAction,
            directKey in self._pinnedKeys(),
            removeEnabled=installedPage and not bool(state),
        )

    def _renderGrid(self, layout, apps, installedPage=False):
        cards = []
        gridWidget = layout.parentWidget()
        gridWidget.setUpdatesEnabled(False)
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                cards.append(item.widget())
        columns = self._columnCount()
        try:
            for index, app in enumerate(apps):
                if index < len(cards):
                    card = cards[index]
                else:
                    card = ApplicationCard(self)
                    card.clicked.connect(
                        lambda card=card: self._showDetail(card.appData)
                    )
                    card.actionClicked.connect(
                        lambda card=card: self._onAppAction(card.appData)
                    )
                    card.pinClicked.connect(
                        lambda card=card: self._toggleApplicationPin(card.appData)
                    )
                    card.uninstallClicked.connect(
                        lambda card=card: self._confirmUninstall(card.appData)
                    )
                card.setApplication(
                    app,
                    self.imagePaths.get(app.get("icon_url", ""), ""),
                )
                card.installedPage = installedPage
                self._setCardState(card, app, installedPage)
                row, column = divmod(index, columns)
                layout.addWidget(card, row, column)
                card.show()
            for card in cards[len(apps) :]:
                card.hide()
                card.deleteLater()
            self._setGridColumns(layout, columns)
        finally:
            gridWidget.setUpdatesEnabled(True)
            gridWidget.update()

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
        self._scheduleLayoutUpdate()

    def _scheduleLayoutUpdate(self):
        if hasattr(self, "_layoutTimer"):
            self._layoutTimer.start()

    def _applyLayoutUpdate(self):
        if hasattr(self, "detail") and self.stack.currentWidget() is self.detail:
            self._resizeDetailStack()
        self._reflowGrids()
        self._syncAdImageSize()

    def _resizeDetailStack(self):
        margins = self.rootLayout.contentsMargins()
        available = self.viewport().height() - margins.top() - margins.bottom()
        self.stack.setFixedHeight(max(280, available))

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
        installed = [app for app in self._mergedApps() if app.get("installed")]
        apps = self._filtered(installed)
        self._renderGrid(self.installedGrid, apps, True)
        count = f"{len(apps)} / {len(installed)}" if self.searchText else len(apps)
        self.installedTitle.setText(f"已安装的软件（{count}）")
        if self.searchText and installed and not apps:
            self.installedEmptyTitle.setText("未找到匹配的已安装应用")
            self.installedEmptyDescription.setText(
                "试试其他关键词，或清除搜索查看本机已安装的全部应用。"
            )
            self.installedEmptyButton.setText("清除搜索")
        else:
            self.installedEmptyTitle.setText("还没有已安装的应用")
            self.installedEmptyDescription.setText(
                "去全部应用看看，安装后可以在这里快速打开、更新或固定到主页。"
            )
            self.installedEmptyButton.setText("浏览全部应用")
        self.installedEmpty.setVisible(not apps)

    def _allAppsForPage(self):
        apps = [
            app
            for app in self._filtered(self._mergedApps())
            if app.get("catalog_available", True)
        ]
        if self.categoryPivot.currentRouteKey() == "recommended":
            apps = [app for app in apps if app.get("recommended")]
            apps.sort(
                key=lambda app: (
                    app.get("recommended_order") is None,
                    app.get("recommended_order") or 0,
                )
            )
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
        self.allPage.setGeometry(self.catalogStack.contentsRect())
        self.allPage.layout().activate()
        multipleAds = len(self.ads) > 1
        for button in (self.adPrevious, self.adNext):
            button.setVisible(multipleAds)
            button.setEnabled(multipleAds)
        self._adSyncTimer.start()
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
        viewportGeometry = self.adFlipView.viewport().geometry()
        self.adOverlay.setGeometry(viewportGeometry)
        # The overlay is positioned manually (outside the flip view layout), so
        # keep its content layout in sync with the new viewport size immediately.
        if self.adOverlay.layout() is not None:
            self.adOverlay.layout().setGeometry(self.adOverlay.rect())
        previousY = max(0, (self.adOverlay.height() - self.adPrevious.height()) // 2)
        previousPosition = self.adOverlay.mapTo(
            self.adPrevious.parentWidget(),
            QPoint(8, previousY),
        )
        nextPosition = self.adOverlay.mapTo(
            self.adNext.parentWidget(),
            QPoint(
                self.adOverlay.width() - self.adNext.width() - 8,
                previousY,
            ),
        )
        self.adPrevious.move(previousPosition)
        self.adNext.move(nextPosition)
        self.adOverlay.raise_()
        self.adPrevious.raise_()
        self.adNext.raise_()

    def _onAdChanged(self, index):
        if not self.ads:
            return
        index = max(0, min(index, len(self.ads) - 1))
        ad = self.ads[index]
        title = str(ad.get("title", ""))
        description = str(ad.get("description", ""))
        self.adTitle.setText(title)
        self.adDescription.setText(description)
        self.adDescription.setVisible(bool(description))
        buttonType = ad.get("button_type") or (
            "app" if ad.get("app_id") else "none"
        )
        self.adButton.setText("打开网页" if buttonType == "url" else "查看软件")
        self.adButton.setVisible(buttonType in {"app", "url"})
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
        ad = self.ads[index]
        buttonType = ad.get("button_type") or (
            "app" if ad.get("app_id") else "none"
        )
        if buttonType == "url":
            url = QUrl(str(ad.get("button_url", "")))
            if url.scheme().lower() == "https":
                QDesktopServices.openUrl(url)
            return
        appId = ad.get("app_id")
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
        self._beginViewportUpdate(0)
        self.currentApp = app
        self._pauseAds()
        self.pivot.hide()
        self.refreshButton.hide()
        self.detailName.setText(str(app.get("name", "")))
        self.detailDeveloper.setText(f"开发者：{app.get('developer') or '未填写'}")
        self.detailVersion.setText(f"版本：{app.get('version') or '未填写'}")
        self.detailDescription.setText(str(app.get("description", "")))
        iconPath = self.imagePaths.get(app.get("icon_url", ""), "")
        icon = QPixmap(iconPath) if iconPath and Path(iconPath).exists() else QPixmap()
        self.detailIcon.setPixmap(
            icon.scaled(
                112,
                112,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if not icon.isNull()
            else FIF.APPLICATION.icon().pixmap(QSize(72, 72))
        )
        self._updateDetailAction()
        self._renderPresets(app)
        self.detailLeftScroll.verticalScrollBar().setValue(0)
        self.presetScroll.verticalScrollBar().setValue(0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._resizeDetailStack()
        self.stack.setCurrentWidget(self.detail, isBack=False)
        self.verticalScrollBar().setValue(0)
        QScroller.ungrabGesture(self.viewport())

    def _backToOverview(self):
        self._beginViewportUpdate(self._catalogScrollPosition)
        self.currentApp = None
        self.pivot.show()
        self.refreshButton.show()
        self.stack.setMinimumHeight(0)
        self.stack.setMaximumHeight(QWIDGETSIZE_MAX)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        QScroller.grabGesture(
            self.viewport(),
            QScroller.ScrollerGestureType.TouchGesture,
        )
        target = 0 if self.pivot.currentRouteKey() == "installed" else 1
        self.catalogStack.setCurrentIndex(target)
        if target == 0:
            self._renderInstalled()
        else:
            self._renderAll()
        self.stack.setCurrentIndex(0, isBack=True)
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
        hasOpenAction = isinstance(
            self._installedOpenAction(self.currentApp), dict
        )
        if appId in self._downloadStates:
            self.detailAction.setText(self._downloadStates[appId])
        elif self.currentApp.get("update_available"):
            self.detailAction.setText("更新")
        elif self.currentApp.get("installed"):
            self.detailAction.setText(
                "打开"
                if hasOpenAction
                else "未配置打开动作"
            )
        else:
            self.detailAction.setText("下载")
        # The store validates package hashes before publishing this flag. Keep the
        # detail action in lockstep with cards so malformed catalog entries cannot
        # enable a download that will only fail after the user clicks it.
        supported = bool(self.currentApp.get("architecture_supported"))
        if self.currentApp.get("installed") and not self.currentApp.get(
            "update_available"
        ):
            actionEnabled = hasOpenAction
        else:
            actionEnabled = supported
        self.detailAction.setEnabled(
            appId not in self._downloadJobs
            and appId not in self._installing
            and appId not in self._uninstalling
            and actionEnabled
        )
        busy = (
            appId in self._downloadJobs
            or appId in self._installing
            or appId in self._uninstalling
        )
        for openButton, pinButton, available, pinned in self._presetActionButtons:
            openButton.setEnabled(available and not busy)
            pinButton.setEnabled((available or pinned) and not busy)

    def _onDetailAction(self):
        if self.currentApp:
            self._onAppAction(self.currentApp)

    def _onLaunchFailed(self, message):
        if self._shuttingDown:
            return
        InfoBar.error(
            "应用未打开",
            message,
            duration=5000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self.window(),
        )

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
                self.store.executeAction(local or app)
            except (ApplicationStoreError, OSError, ValueError) as error:
                InfoBar.error("无法打开应用", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        try:
            self.store.downloadSlots.acquire()
        except ApplicationStoreError as error:
            InfoBar.warning("下载任务已满", str(error), duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        worker = None
        try:
            worker = downloadWorker(app, self.store)
            thread = threading.Thread(target=worker.run, daemon=True)
        except Exception as error:
            self.store.downloadSlots.release()
            if worker is not None:
                worker.deleteLater()
            InfoBar.error("无法开始下载", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        beginAppStorePackageOperation()
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
        try:
            thread.start()
        except Exception as error:
            self._downloadJobs.pop(appId, None)
            self._downloadStates.pop(appId, None)
            _releasePackageOperation(self.store.downloadSlots)
            worker.deleteLater()
            InfoBar.error("无法开始下载", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
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
            _releasePackageOperation(self.store.downloadSlots)
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
        thread = None
        try:
            thread = threading.Thread(
                target=self._installInBackground,
                args=(app, Path(path)),
                daemon=True,
            )
            with self._fileOperationLock:
                self._fileOperationThreads.add(thread)
                self._installThreads[appId] = thread
            thread.start()
        except Exception as error:
            if thread is not None:
                with self._fileOperationLock:
                    self._fileOperationThreads.discard(thread)
                    self._installThreads.pop(appId, None)
            self._installing.discard(appId)
            _releasePackageOperation(self.store.downloadSlots)
            self._downloadStates.pop(appId, None)
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
            self._updateVisibleCardState(appId)
            self._updateDetailAction()
            InfoBar.error("无法开始安装", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _installInBackground(self, app, path):
        installed = None
        errorMessage = ""
        try:
            installed = self.store.installZip(
                app,
                path,
                self._installationCancelEvent,
            )
        except Exception as error:
            errorMessage = str(error)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            with self._fileOperationLock:
                self._fileOperationThreads.discard(threading.current_thread())
        if not self._shuttingDown:
            self._installFinished.emit(
                int(app["id"]),
                installed,
                errorMessage,
            )

    _installFinished = Signal(int, object, str)

    def _onInstallFinished(self, appId, installed, error):
        if self._shuttingDown:
            return
        if appId not in self._installing:
            return
        self._installing.discard(appId)
        with self._fileOperationLock:
            self._installThreads.pop(appId, None)
        _releasePackageOperation(self.store.downloadSlots)
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
        try:
            accepted = box.exec()
        finally:
            box.deleteLater()
        if not accepted:
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
        self._mergedCatalog = None
        self._syncPinnedMetadata()
        self._renderInstalled()
        self._renderAll()
        if self.currentApp:
            current = next(
                (
                    app
                    for app in self._mergedApps()
                    if app["id"] == self.currentApp["id"]
                ),
                None,
            )
            if current:
                self.currentApp = current
                self._updateDetailAction()
                self._renderPresets(current)
            else:
                self._backToOverview()

    def _renderPresets(self, app):
        self._presetActionButtons = []
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
            self.presetCards.addWidget(
                BodyLabel("该应用暂不支持预设卡片", self.presetGroup)
            )
            return
        pinned = self._pinnedKeys()
        installedPresetIds = {
            str(preset.get("id", ""))
            for preset in app.get("installed_presets", []) or []
        }
        for index, preset in enumerate(presets):
            if index:
                divider = QFrame(self.presetGroup)
                divider.setFrameShape(QFrame.Shape.HLine)
                divider.setStyleSheet(
                    "border: none; border-top: 1px solid rgba(128, 128, 128, 0.2);"
                )
                self.presetCards.addWidget(divider)
            item = QWidget(self.presetGroup)
            row = QHBoxLayout(item)
            row.setContentsMargins(0, 10, 0, 10)
            row.setSpacing(12)
            copy = QVBoxLayout()
            copy.setSpacing(4)
            copy.addWidget(
                StrongBodyLabel(str(preset.get("title", "")), item)
            )
            description = BodyLabel(str(preset.get("description", "")), item)
            description.setWordWrap(True)
            copy.addWidget(description)
            row.addLayout(copy, 1)
            key = (int(app["id"]), int(preset["id"]))
            available = str(preset.get("id", "")) in installedPresetIds
            busy = (
                key[0] in self._downloadJobs
                or key[0] in self._installing
                or key[0] in self._uninstalling
            )
            openButton = PushButton(FIF.PLAY, "打开", item)
            openButton.setFixedHeight(40)
            openButton.setAccessibleName("打开预设")
            openButton.setEnabled(available and not busy)
            openButton.clicked.connect(
                lambda _checked=False, appData=app, presetData=preset: self._openPreset(
                    appData, presetData
                )
            )
            row.addWidget(openButton)
            pin = ToggleToolButton(FIF.PIN, item)
            pin.setFixedSize(40, 40)
            isPinned = key in pinned
            pin.setChecked(isPinned)
            pin.setEnabled((available or isPinned) and not busy)
            if isPinned:
                tooltip = "取消固定"
            elif available:
                tooltip = "固定到主页"
            else:
                tooltip = "请先更新应用"
            pin.setAccessibleName(tooltip)
            setFluentToolTip(pin, tooltip)
            pin.clicked.connect(lambda _checked=False, appData=app, presetData=preset: self._togglePin(appData, presetData))
            self._presetActionButtons.append(
                (openButton, pin, available, isPinned)
            )
            row.addWidget(pin)
            self.presetCards.addWidget(item)

    def _openPreset(self, app, preset):
        appId = int(app["id"])
        if (
            appId in self._downloadJobs
            or appId in self._installing
            or appId in self._uninstalling
        ):
            return
        installed = self.store.installed().get(appId)
        if installed is None:
            InfoBar.warning(
                "应用尚未安装",
                "请先安装应用后再打开预设。",
                duration=3000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self.window(),
            )
            return
        installedPreset = next(
            (
                item
                for item in installed.metadata.get("presets", [])
                if str(item.get("id", "")) == str(preset.get("id", ""))
            ),
            None,
        )
        action = installedPreset.get("action") if installedPreset else None
        if not isinstance(action, dict):
            InfoBar.warning(
                "预设不可用",
                "请先更新应用，再打开这个预设。",
                duration=3000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self.window(),
            )
            return
        try:
            self.store.executeAction(installed, action)
        except (ApplicationStoreError, OSError, ValueError) as error:
            InfoBar.error(
                "无法打开预设",
                str(error),
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self.window(),
            )

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
        action = self._installedOpenAction(app)
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
        noticeParent = self.window()
        cards = normalize_pinned_cards([item])
        if not cards:
            InfoBar.warning("预设卡片无效", "请重新固定这张主页卡片。", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=noticeParent)
            return
        item = cards[0]
        appId = item["app_id"]
        installed = self.store.installed().get(appId)
        if not installed:
            InfoBar.warning("应用尚未安装", "请先安装对应应用后再使用主页预设卡片。", duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=noticeParent)
            return
        try:
            if item["preset_id"] == DIRECT_APPLICATION_PRESET_ID:
                self.store.executeAction(installed)
            else:
                preset = next(
                    (
                        preset
                        for preset in installed.metadata.get("presets", [])
                        if str(preset.get("id", ""))
                        == str(item["preset_id"])
                    ),
                    None,
                )
                action = preset.get("action") if preset else None
                if not isinstance(action, dict):
                    InfoBar.warning(
                        "主页卡片已失效",
                        "请在应用详情中重新固定这张预设卡片。",
                        duration=3000,
                        position=InfoBarPosition.BOTTOM_RIGHT,
                        parent=noticeParent,
                    )
                    return
                self.store.executeAction(installed, action)
        except (ApplicationStoreError, OSError, ValueError) as error:
            InfoBar.error("执行预设失败", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=noticeParent)

    def refreshPinnedCards(self):
        cards = normalize_pinned_cards(cfg.pinnedHomeCards.value)
        self._refreshPinStates(cards)
        self.pinnedCardsChanged.emit(cards)

    def clearCachedImages(self):
        self.imagePaths.clear()

    @staticmethod
    def _installedOpenAction(app):
        if "installed_open_action" in app:
            return app.get("installed_open_action")
        return app.get("open_action")
