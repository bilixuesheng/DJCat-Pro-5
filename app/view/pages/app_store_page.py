import threading
import time
from queue import Empty, Queue
from pathlib import Path

from loguru import logger
from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    Property,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScroller,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CaptionLabel,
    DrillInTransitionStackedWidget,
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
    qconfig,
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
ALL_APPS_PAGE_SIZE = 6
APPLICATION_CARD_HEIGHT = 168
CONTENT_MARGINS = (12, 8, 20, 24)
_LIVE_CATALOG_URI_SCHEMES = frozenset({"classisland"})
def _releaseSlotAfterExit(thread, downloadSlots):
    def releaseAfterExit():
        thread.join()
        downloadSlots.release()

    threading.Thread(
        target=releaseAfterExit,
        daemon=True,
        name="app-store-package-reaper",
    ).start()


# 选项卡、分类和分页是同级之间的横移；进入详情是往下一级走，用 DrillIn 区分开。
SLIDE_DURATION_MS = 180
SLIDE_NEXT_START_OPACITY = 0.35


def _slideOffset(width):
    return max(48, min(120, width // 8))


class _ReversibleSnapshotTransition:
    def setCurrentIndex(self, index, duration=None, isBack=False):
        if index < 0 or index >= self.count():
            return
        # 过渡期间 currentIndex 仍是旧页：不先收尾，反向切回旧页会被当成原地不动。
        if self._aniGroup.state() == QAbstractAnimation.State.Running:
            if index == self._nextIndex:
                return
            self._stopAnimation()
        super().setCurrentIndex(index, duration, isBack)

    def _onAniFinished(self):
        super()._onAniFinished()
        self._currentSnapshot.clear()
        self._nextSnapshot.clear()


class HorizontalTransitionStackedWidget(
    _ReversibleSnapshotTransition, TransitionStackedWidget
):
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
        offset = _slideOffset(self.width())
        animationDuration = duration or SLIDE_DURATION_MS
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
        self._nextFade.setStartValue(SLIDE_NEXT_START_OPACITY)
        self._nextFade.setEndValue(1.0)

    def resizeEvent(self, event):
        self._stopAnimation()
        super().resizeEvent(event)


class DetailTransitionStackedWidget(
    _ReversibleSnapshotTransition, DrillInTransitionStackedWidget
):
    pass


class GridSlideTransition(QObject):
    """Slide a grid's previous and new contents past each other.

    The grid changes at once and stays hidden, keeping its layout space, under
    two snapshots; paging and category switches then move like the catalog
    tabs without a second set of cards or any relayout per animation tick.
    """

    def __init__(self, target: QWidget):
        super().__init__(target)
        self._target = target
        policy = target.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        target.setSizePolicy(policy)
        self._group = QParallelAnimationGroup(self)
        self._group.finished.connect(self._settle)
        self._labels = []
        self._slides = []
        self._fades = []
        curve = QEasingCurve(QEasingCurve.Type.OutCubic)
        for _ in range(2):
            label = QLabel(target.parentWidget())
            label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            effect = QGraphicsOpacityEffect(label)
            label.setGraphicsEffect(effect)
            label.hide()
            slide = QPropertyAnimation(label, b"pos", self)
            fade = QPropertyAnimation(effect, b"opacity", self)
            for animation in (slide, fade):
                animation.setDuration(SLIDE_DURATION_MS)
                animation.setEasingCurve(curve)
                self._group.addAnimation(animation)
            self._labels.append(label)
            self._slides.append(slide)
            self._fades.append(fade)

    def isRunning(self):
        return self._group.state() == QAbstractAnimation.State.Running

    def run(self, change, forward=True):
        self.stop()
        target = self._target
        if not target.isVisible() or target.width() <= 0:
            change()
            return
        before = target.grab()
        change()
        target.parentWidget().layout().activate()
        target.layout().activate()
        after = target.grab()

        origin = target.pos()
        offset = _slideOffset(target.width()) * (1 if forward else -1)
        current, upcoming = self._labels
        for label, pixmap in ((current, before), (upcoming, after)):
            label.setPixmap(pixmap)
            label.resize(pixmap.deviceIndependentSize().toSize())
            label.show()
            label.raise_()
        currentSlide, nextSlide = self._slides
        currentFade, nextFade = self._fades
        currentSlide.setStartValue(origin)
        currentSlide.setEndValue(origin - QPoint(offset, 0))
        nextSlide.setStartValue(origin + QPoint(offset, 0))
        nextSlide.setEndValue(origin)
        currentFade.setStartValue(1.0)
        currentFade.setEndValue(0.0)
        nextFade.setStartValue(SLIDE_NEXT_START_OPACITY)
        nextFade.setEndValue(1.0)
        current.move(origin)
        upcoming.move(origin + QPoint(offset, 0))
        target.hide()
        self._group.start()

    def stop(self):
        if self.isRunning():
            self._group.stop()
            self._settle()

    def _settle(self):
        for label in self._labels:
            label.hide()
            label.clear()
        self._target.show()


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
            try:
                self.store.syncInstalledMetadata(payload.get("apps"))
            except Exception:
                logger.exception("同步已安装应用的目录信息失败")
            self.finished.emit(payload, {}, "")
        except Exception as error:
            if not self._cancelEvent.is_set():
                self.finished.emit({}, {}, str(error))
        finally:
            self.completed.emit()


class CatalogImageWorker(QObject):
    imageLoaded = Signal(str, str)
    completed = Signal()
    # 新一批图片开始前旧的一批总会先被取消，排在前面的旧任务出队即跳过，
    # 所以普通先进先出队列就够了；线程是 daemon，退出程序不等图片下载。
    _jobs = Queue()
    _poolLock = threading.Lock()
    _poolThreads = set()
    _threadSequence = 0
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
                store, url, cancelEvent, results = cls._jobs.get(
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
                    except Exception as error:
                        logger.warning(
                            "应用市场图片加载失败（{}）：{}",
                            QUrl(url).fileName(),
                            error,
                        )
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
                self._jobs.put((self.store, url, self._cancelEvent, results))
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


class ActionProgressButton(PrimaryPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._progress = None
        self._displayProgress = 0.0
        self._indeterminate = False
        self._progressOffset = 0.0
        self._progressAnimation = QPropertyAnimation(
            self, b"displayProgress", self
        )
        self._progressAnimation.setDuration(150)
        self._progressTimer = QTimer(self)
        self._progressTimer.setInterval(30)
        self._progressTimer.timeout.connect(self._advanceProgress)

    def setProgress(self, progress=None, indeterminate=False):
        self._indeterminate = bool(indeterminate)
        if self._indeterminate:
            self._progressAnimation.stop()
            self._progress = None
            self._displayProgress = 0.0
            self._progressTimer.start()
        else:
            self._progressTimer.stop()
            self._progressOffset = 0.0
            if progress is None:
                self._progressAnimation.stop()
                self._progress = None
                self._displayProgress = 0.0
            else:
                target = max(0, min(100, int(progress)))
                if (
                    self._progress == target
                    and self._progressAnimation.state()
                    == QAbstractAnimation.State.Running
                ):
                    return
                self._progress = target
                self._progressAnimation.stop()
                if self._displayProgress == target:
                    self.update()
                    return
                self._progressAnimation.setStartValue(self._displayProgress)
                self._progressAnimation.setEndValue(float(target))
                self._progressAnimation.start()
        self.update()

    def _getDisplayProgress(self):
        return self._displayProgress

    def _setDisplayProgress(self, progress):
        self._displayProgress = float(progress)
        self.update()

    def _advanceProgress(self):
        self._progressOffset = (self._progressOffset + 0.025) % 1.0
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._progress is None and not self._indeterminate:
            return
        inset = 5.0
        width = max(0.0, self.width() - inset * 2.0)
        if width <= 0:
            return
        track = QRectF(inset, self.height() - 2.0, width, 2.0)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        color = QColor(qconfig.themeColor.value)
        trackColor = QColor(color)
        trackColor.setAlpha(75)
        painter.setBrush(trackColor)
        painter.drawRoundedRect(track, 1.0, 1.0)
        painter.setClipRect(track)
        if self._indeterminate:
            segment = max(24.0, width * 0.28)
            x = track.left() - segment + (width + segment) * self._progressOffset
            fill = QRectF(x, track.top(), segment, track.height())
        else:
            fill = QRectF(
                track.left(),
                track.top(),
                width * self._displayProgress / 100.0,
                track.height(),
            )
        painter.setBrush(color)
        painter.drawRoundedRect(fill, 1.0, 1.0)

    displayProgress = Property(float, _getDisplayProgress, _setDisplayProgress)


class ApplicationCard(CardWidget):
    actionClicked = Signal()
    pinClicked = Signal()
    uninstallClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setClickEnabled(True)
        self.setFixedHeight(APPLICATION_CARD_HEIGHT)
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
        self.downloadCountLabel = CaptionLabel(self)
        self.pinButton = ToggleToolButton(FIF.PIN, self)
        self.pinButton.setAccessibleName("固定到主页")
        setFluentToolTip(self.pinButton, "固定到主页")
        self.pinButton.hide()
        self.actionButton = ActionProgressButton(self)
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
        titleLayout = QVBoxLayout()
        titleLayout.setContentsMargins(0, 0, 0, 0)
        titleLayout.setSpacing(2)
        titleLayout.addStretch(1)
        titleLayout.addWidget(self.titleLabel)
        titleLayout.addWidget(self.downloadCountLabel)
        titleLayout.addStretch(1)
        top.addLayout(titleLayout, 1)
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
        try:
            count = max(0, int(app.get("download_count", 0) or 0))
        except (TypeError, ValueError):
            count = 0
        self.downloadCountLabel.setText(f"已下载 {count:,} 次")
        self.setImage(imagePath)

    def setDownloadCountVisible(self, visible: bool) -> None:
        self.downloadCountLabel.setVisible(bool(visible))

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

    def setProgress(self, progress=None, indeterminate=False) -> None:
        self.actionButton.setProgress(progress, indeterminate)

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


class EmptyStateCard(CardWidget):
    actionRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(220)
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(64, 64)
        self.iconLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.iconLabel.setPixmap(FIF.APPLICATION.icon().pixmap(QSize(48, 48)))
        self.titleLabel = SubtitleLabel(self)
        self.descriptionLabel = BodyLabel(self)
        self.descriptionLabel.setWordWrap(True)
        self.descriptionLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.actionButton = PrimaryPushButton(self)
        self.actionButton.clicked.connect(self.actionRequested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 28, 24, 28)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.iconLabel, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.titleLabel, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.descriptionLabel)
        layout.addWidget(self.actionButton, 0, Qt.AlignmentFlag.AlignHCenter)

    def setContent(self, title: str, description: str, actionText: str = "") -> None:
        self.titleLabel.setText(title)
        self.descriptionLabel.setText(description)
        self.actionButton.setText(actionText)
        self.actionButton.setVisible(bool(actionText))


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


AD_SCRIM_START = 0.38
AD_SCRIM_LEAD_PX = 24


def _adOverlayStyle(start: float) -> str:
    """暗色渐变的起点跟着标题提前：字体行高和描述行数都会改变文字块的高度，
    固定在 38% 时，Windows 字体下的两行描述会让白色标题落在还没变暗的图上。"""
    stops = (
        (start, "transparent"),
        (start + 0.10, "rgba(0,0,0,45)"),
        (start + 0.20, "rgba(0,0,0,95)"),
        (start + 0.36, "rgba(0,0,0,175)"),
    )
    gradient = ", ".join(f"stop: {min(position, 0.99):.2f} {color}" for position, color in stops)
    return (
        "QWidget#AdvertisementOverlay {"
        f"background: qlineargradient(y1: 0, y2: 1, {gradient}, stop: 1 rgba(0,0,0,245));"
        "border-radius: 12px;"
        "}"
    )


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


class _PinnedCardNotice(Exception):
    def __init__(self, level, title, message):
        super().__init__(message)
        self.level = level
        self.title = title


class AppStorePage(QWidget):
    pinnedCardsChanged = Signal(object)
    pinnedCardFailed = Signal()
    _pinnedCardFinished = Signal(int, bool, str, str, str)
    _launchFinished = Signal(int, str, str)
    _downloadProgressSignal = Signal(int, int, int)
    _downloadRetrySignal = Signal(str, str)
    _downloadFinishedSignal = Signal(object, str, str, bool)
    _uninstallFinished = Signal(int, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = ApplicationStore()
        self._catalog = []
        self._mergedCatalog = None
        self.ads = []
        self.imagePaths = {}
        self.currentApp = None
        self.searchText = ""
        self._catalogLoading = False
        self._catalogLoaded = False
        self._catalogError = ""
        self._catalogThread = None
        self._catalogWorker = None
        self._imageJobs = {}
        self._shuttingDown = False
        self._globalAdFilterInstalled = False
        self._downloadJobs = {}
        self._downloadStates = {}
        self._downloadProgress = {}
        self._checkingUpdates = False
        self._launching = set()
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
        self._currentPage = 0
        self._categoryIndex = 0
        self._renderingAll = False
        self._allEmptyAction = None
        self._downloadProgressSignal.connect(self._queueDownloadProgress)
        self._downloadRetrySignal.connect(self._showDownloadRetry)
        self._downloadFinishedSignal.connect(self._onDownloadFinished)
        self._launchFinished.connect(self._onLaunchFinished)
        self._pinnedCardFinished.connect(self._onPinnedCardFinished)
        self._installFinished.connect(self._onInstallFinished)
        self._uninstallFinished.connect(self._onUninstallFinished)
        self.setObjectName("AppStorePage")
        self._buildUi()
        cfg.pinnedHomeCards.valueChanged.connect(self._refreshPinStates)

    def _buildUi(self):
        # 选项卡栏固定在顶部，两个选项卡各自滚动、各自记住位置：切换和进出详情时
        # 页面高度不变，快照截到的就是屏幕上正在看的那一段。
        self.rootLayout = QVBoxLayout(self)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.stack = DetailTransitionStackedWidget(self)
        self.catalogPage = QWidget(self.stack)
        catalogLayout = QVBoxLayout(self.catalogPage)
        catalogLayout.setContentsMargins(0, 0, 0, 0)
        catalogLayout.setSpacing(8)

        self.pivot = Pivot(self.catalogPage)
        self.pivot.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.pivot.addItem("installed", "已安装", lambda: self._switchCatalogTab(0))
        self.pivot.addItem("all", "全部应用", lambda: self._switchCatalogTab(1))
        self.pivot.setCurrentItem("installed")

        header = QHBoxLayout()
        header.setContentsMargins(
            CONTENT_MARGINS[0], CONTENT_MARGINS[1], CONTENT_MARGINS[2], 0
        )
        header.addWidget(self.pivot)
        header.addStretch(1)
        self.checkUpdatesButton = PushButton(
            FIF.SYNC, "检查更新", self.catalogPage
        )
        self.checkUpdatesButton.clicked.connect(self._checkInstalledUpdates)
        header.addWidget(self.checkUpdatesButton)
        self.refreshButton = ToolButton(FIF.SYNC, self.catalogPage)
        setFluentToolTip(self.refreshButton, "刷新应用目录")
        self.refreshButton.clicked.connect(self._loadCatalog)
        header.addWidget(self.refreshButton)
        catalogLayout.addLayout(header)

        self.catalogStack = HorizontalTransitionStackedWidget(self.catalogPage)
        catalogLayout.addWidget(self.catalogStack, 1)

        self.overview = QWidget()
        overviewLayout = self._createTabLayout(self.overview)
        self.installedTitle = BodyLabel("已安装的软件", self.overview)
        overviewLayout.addWidget(self.installedTitle)
        self.installedEmpty = EmptyStateCard(self.overview)
        self.installedEmpty.actionRequested.connect(self._handleInstalledEmptyAction)
        self.installedEmptyIcon = self.installedEmpty.iconLabel
        self.installedEmptyTitle = self.installedEmpty.titleLabel
        self.installedEmptyDescription = self.installedEmpty.descriptionLabel
        self.installedEmptyButton = self.installedEmpty.actionButton
        overviewLayout.addWidget(self.installedEmpty)
        self.installedGridWidget, self.installedGrid = self._createGrid(self.overview)
        overviewLayout.addWidget(self.installedGridWidget)
        self.installedScroll = self._createTabScroll(self.overview, grabTouch=True)

        self.allPage = QWidget()
        allLayout = self._createTabLayout(self.allPage)
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
        adLayout.addWidget(self.adFlipView)
        self.adOverlay = AdvertisementOverlay(self.adFlipView)
        self.allScroll = self._createTabScroll(self.allPage, grabTouch=False)
        for touchTarget in (
            self.allScroll.viewport(),
            self.adFlipView,
            self.adFlipView.viewport(),
        ):
            touchTarget.installEventFilter(self.adOverlay)
        self.adOverlay.setObjectName("AdvertisementOverlay")
        self.adOverlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._adScrimStart = AD_SCRIM_START
        self.adOverlay.setStyleSheet(_adOverlayStyle(self._adScrimStart))
        overlayLayout = QVBoxLayout(self.adOverlay)
        overlayLayout.setContentsMargins(20, 0, 20, 10)
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
        overlayLayout.addSpacing(6)
        self.adButton = PrimaryPushButton("查看软件", self.adOverlay)
        self.adButton.setMaximumHeight(30)
        self.adButton.clicked.connect(self._openAdApp)
        overlayLayout.addWidget(self.adButton, 0, Qt.AlignmentFlag.AlignLeft)
        self.adPrevious = self.adFlipView.preButton
        self.adNext = self.adFlipView.nextButton
        self.adOverlay.setTouchButtons((self.adPrevious, self.adNext))
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
        self.allEmpty = EmptyStateCard(self.allPage)
        self.allEmpty.actionRequested.connect(self._handleAllEmptyAction)
        self.allEmpty.hide()
        allLayout.addWidget(self.allEmpty)
        self.allGridWidget, self.allGrid = self._createGrid(self.allPage)
        allLayout.addWidget(self.allGridWidget)
        self.allGridSlide = GridSlideTransition(self.allGridWidget)
        self.pagerBar = QWidget(self.allPage)
        pagerLayout = QHBoxLayout(self.pagerBar)
        pagerLayout.setContentsMargins(0, 0, 0, 0)
        pagerLayout.setSpacing(8)
        self.pagerPrevious = ToolButton(FIF.LEFT_ARROW, self.pagerBar)
        self.pagerPrevious.clicked.connect(lambda: self._changePage(-1))
        pagerLayout.addWidget(self.pagerPrevious)
        self.pager = PipsPager(self.pagerBar)
        self.pager.currentIndexChanged.connect(self._onPageChanged)
        pagerLayout.addWidget(self.pager)
        self.pagerNext = ToolButton(FIF.RIGHT_ARROW, self.pagerBar)
        self.pagerNext.clicked.connect(lambda: self._changePage(1))
        pagerLayout.addWidget(self.pagerNext)
        allLayout.addWidget(self.pagerBar, 0, Qt.AlignmentFlag.AlignHCenter)

        self.catalogStack.addWidget(self.installedScroll)
        self.catalogStack.addWidget(self.allScroll)
        self.catalogStack.aniFinished.connect(self._resumeAds)
        self.stack.addWidget(self.catalogPage)

        self.detail = QWidget(self.stack)
        self._buildDetail()
        self.stack.addWidget(self.detail)
        self.rootLayout.addWidget(self.stack)
        self.adFrame.hide()
        self._renderInstalled()

    @staticmethod
    def _createTabLayout(content):
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            CONTENT_MARGINS[0], 0, CONTENT_MARGINS[2], CONTENT_MARGINS[3]
        )
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        return layout

    def _createTabScroll(self, content, grabTouch):
        scroll = ScrollArea(self.catalogStack, grabTouch=grabTouch)
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.enableTransparentBackground()
        return scroll

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
        layout.setContentsMargins(*CONTENT_MARGINS)
        layout.setSpacing(8)
        self.detailBackButton = PushButton(
            FIF.LEFT_ARROW, "返回应用列表", self.detail
        )
        self.detailBackButton.clicked.connect(self._backToOverview)
        layout.addWidget(
            self.detailBackButton, 0, Qt.AlignmentFlag.AlignLeft
        )
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
        self.detailAction = ActionProgressButton(self.detailLeft)
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

        self.presetGroup = CardWidget(self.presetPanel)
        groupLayout = QVBoxLayout(self.presetGroup)
        groupLayout.setContentsMargins(16, 16, 16, 16)
        groupLayout.setSpacing(10)
        self.presetTitle = SubtitleLabel("主页预设卡片", self.presetGroup)
        groupLayout.addWidget(self.presetTitle)
        self.presetHeaderDivider = QFrame(self.presetGroup)
        self.presetHeaderDivider.setFrameShape(QFrame.Shape.HLine)
        self.presetHeaderDivider.setStyleSheet(
            "border: none; border-top: 1px solid rgba(128, 128, 128, 0.2);"
        )
        groupLayout.addWidget(self.presetHeaderDivider)
        self.announcementLabel = QLabel(self.presetGroup)
        self.announcementLabel.setWordWrap(True)
        self.announcementLabel.setStyleSheet(
            "padding: 10px 12px; border-radius: 8px; background: #fff4e6; color: #8a4b08;"
        )
        groupLayout.addWidget(self.announcementLabel)
        self.presetCards = QVBoxLayout()
        self.presetCards.setContentsMargins(0, 0, 0, 0)
        self.presetCards.setSpacing(10)
        groupLayout.addLayout(self.presetCards)
        presetLayout.addWidget(self.presetGroup)
        presetLayout.addStretch(1)
        self.presetScroll.setWidget(self.presetPanel)
        columns.addWidget(self.presetScroll, 2)
        layout.addLayout(columns, 1)

    def _switchCatalogTab(self, index: int):
        self.checkUpdatesButton.setVisible(index == 0)
        if index == 1:
            self.allScroll.grabTouchGesture()
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
        changed = index != self._categoryIndex
        forward = index > self._categoryIndex
        self._categoryIndex = index

        def change():
            self._currentPage = 0
            self._renderAll()

        if changed:
            self.allGridSlide.run(change, forward)
            self._scrollAllToListStart()
        else:
            change()

    def _scrollAllToListStart(self):
        """Bring the category bar back into view after the list content changed.

        Only scrolls up: when the start of the list is still on screen the new
        page is already readable where it is, and scrolling to the very top
        would put the banner, not the list, in front of the user.
        """
        # 惯性滚动不停下，会把页面拖回原来的位置。没抓过手势就没有惯性，
        # 也别用 QScroller.scroller() 顺手建出一个。
        if self.allScroll.isTouchGestureGrabbed:
            QScroller.scroller(self.allScroll.viewport()).stop()
        target = self.categoryPivot.y()
        if self.allScroll.verticalScrollBar().value() <= target:
            return
        smoothBar = getattr(getattr(self.allScroll, "delegate", None), "vScrollBar", None)
        if smoothBar is not None:
            smoothBar.scrollTo(target)
        else:
            self.allScroll.verticalScrollBar().setValue(target)

    def _showAllApplications(self):
        searchEdit = getattr(self.window(), "searchEdit", None)
        if searchEdit is not None:
            searchEdit.clear()
        else:
            self.setSearchText("")
        self.pivot.setCurrentItem("all")
        self._switchCatalogTab(1)

    def _clearSearch(self):
        searchEdit = getattr(self.window(), "searchEdit", None)
        if searchEdit is not None:
            searchEdit.clear()
        else:
            self.setSearchText("")

    def _handleInstalledEmptyAction(self):
        if self.searchText:
            self._clearSearch()
            return
        self._showAllApplications()

    def _handleAllEmptyAction(self):
        if self._allEmptyAction is not None:
            self._allEmptyAction()

    def _showAllCategory(self):
        self.categoryPivot.setCurrentItem("all")
        self._switchCategory(1)

    def setSearchText(self, text: str):
        self.searchText = text.strip().lower()
        if self.currentApp is not None:
            return
        # 横移期间 catalogStack 仍停在旧页，以选项卡栏为准才不会渲染错页。
        if self.pivot.currentRouteKey() == "installed":
            self._renderInstalled()
        else:
            self._renderAll()

    def showEvent(self, event):
        self._layoutTimer.stop()
        self._applyLayoutUpdate()
        super().showEvent(event)
        if not self._globalAdFilterInstalled:
            QApplication.instance().installEventFilter(self.adOverlay)
            self._globalAdFilterInstalled = True
        if not self._catalogLoaded:
            self._loadCatalog()

    def hideEvent(self, event):
        if self._globalAdFilterInstalled:
            QApplication.instance().removeEventFilter(self.adOverlay)
            self._globalAdFilterInstalled = False
        self._pauseAds()
        super().hideEvent(event)

    def shutdown(self):
        if self._shuttingDown:
            return
        self._shuttingDown = True
        self._pauseAds()
        if self._globalAdFilterInstalled:
            QApplication.instance().removeEventFilter(self.adOverlay)
            self._globalAdFilterInstalled = False
        self.store.shutdown()
        self._layoutTimer.stop()
        self._adSyncTimer.stop()
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
                    _releaseSlotAfterExit(
                        thread,
                        self.store.downloadSlots,
                    )
                else:
                    self.store.downloadSlots.release()
            self._downloadStates.pop(appId, None)
            self._downloadProgress.pop(appId, None)
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
                _releaseSlotAfterExit(
                    thread,
                    self.store.downloadSlots,
                )
            else:
                self.store.downloadSlots.release()
        self._installing.clear()
        with self._fileOperationLock:
            self._installThreads.clear()
        for appId in self._uninstalling:
            self._downloadStates.pop(appId, None)
            self._downloadProgress.pop(appId, None)
        self._uninstalling.clear()
        for appId in self._launching:
            self._downloadStates.pop(appId, None)
        self._launching.clear()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def _loadCatalog(self):
        if self._shuttingDown or self._catalogLoading:
            return
        self._catalogLoading = True
        self._catalogError = ""
        self.refreshButton.setEnabled(False)
        self.checkUpdatesButton.setEnabled(False)
        if not self.catalog:
            self._renderAll()
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
            self._catalogError = error
            self._mergedCatalog = None
            self._renderInstalled()
            self._renderAll()
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
        if getattr(self, "_checkingUpdates", False):
            updates = sum(
                bool(app.get("installed") and app.get("update_available"))
                for app in self._mergedApps()
            )
            if updates:
                InfoBar.success(
                    "检查完成",
                    f"发现 {updates} 个可用更新。",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self,
                )
            else:
                InfoBar.info(
                    "检查完成",
                    "已安装的软件均为最新版本。",
                    duration=3000,
                    position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self,
                )
        if self.currentApp:
            current = next((app for app in self._mergedApps() if app["id"] == self.currentApp["id"]), None)
            if current:
                # 正在看的详情就地换成新目录的数据，不把两栏滚回顶部。
                self._populateDetail(current)
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
        for card in self.findChildren(ApplicationCard):
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
            self.checkUpdatesButton.setEnabled(True)
        self._checkingUpdates = False

    def _checkInstalledUpdates(self):
        if self._catalogLoading:
            return
        self._checkingUpdates = True
        self._loadCatalog()

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
            if card["preset_id"] != DIRECT_APPLICATION_PRESET_ID:
                currentAction = self._currentCatalogPresetAction(
                    card["app_id"], card["preset_id"]
                )
                if currentAction is not None:
                    values["action"] = currentAction
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
        # 选项卡的滚动条浮在内容上方，不占宽度，所以按页面宽度算，隐藏时也算得准。
        width = self.width() - CONTENT_MARGINS[0] - CONTENT_MARGINS[2]
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
        actionText, enabled = self._actionState(app, showUpdate=installedPage)
        hasOpenAction = isinstance(self._installedOpenAction(app), dict)
        directKey = (appId, DIRECT_APPLICATION_PRESET_ID)
        card.setState(
            actionText,
            installedPage,
            enabled,
            hasOpenAction,
            directKey in self._pinnedKeys(),
            removeEnabled=installedPage and appId not in self._downloadStates,
        )
        self._applyProgress(card, appId)

    def _actionState(self, app, showUpdate):
        """Text and enabled state of an app's main button, shared by card and detail."""
        state = self._downloadStates.get(int(app["id"]))
        if state:
            return state, False
        supported = bool(app.get("architecture_supported"))
        if showUpdate and app.get("update_available"):
            return "更新", supported
        if app.get("installed"):
            hasOpenAction = isinstance(self._installedOpenAction(app), dict)
            return ("打开" if hasOpenAction else "未配置打开动作"), hasOpenAction
        return ("下载" if supported else "不支持"), supported

    def _applyProgress(self, button, appId):
        if (
            appId in self._launching
            or appId in self._installing
            or appId in self._uninstalling
        ):
            button.setProgress(indeterminate=True)
        elif appId in self._downloadJobs:
            progress = self._downloadProgress.get(appId, 0)
            button.setProgress(progress, indeterminate=not progress)
        else:
            button.setProgress()

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
                        lambda card=card: self._onAppAction(
                            card.appData, allowUpdate=card.installedPage
                        )
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
                card.setDownloadCountVisible(not installedPage)
                self._setCardState(card, app, installedPage)
                row, column = divmod(index, columns)
                layout.addWidget(card, row, column)
                card.show()
            for card in cards[len(apps) :]:
                card.hide()
                card.setParent(None)
                card.deleteLater()
            self._setGridColumns(layout, columns)
            layout.setProperty("djcatColumns", columns)
        finally:
            gridWidget.setUpdatesEnabled(True)
            gridWidget.update()

    def _reflowGrid(self, layout):
        columns = self._columnCount()
        if layout.property("djcatColumns") == columns:
            return
        widgets = []
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                widgets.append(item.widget())
        for index, widget in enumerate(widgets):
            row, column = divmod(index, columns)
            layout.addWidget(widget, row, column)
        self._setGridColumns(layout, columns)
        layout.setProperty("djcatColumns", columns)

    def _reflowGrids(self):
        if not hasattr(self, "installedGrid") or not hasattr(self, "allGrid"):
            return
        self._reflowGrid(self.installedGrid)
        self._reflowGrid(self.allGrid)
        self._reserveAllGridHeight()

    def _reserveAllGridHeight(self):
        # 最后一页卡片少时网格变矮，分页按钮会往上跳，翻页的横移会把这一跳放大。
        # 只有一页时不预留，免得凭空多出一片空白。
        height = 0
        if (
            self.categoryPivot.currentRouteKey() == "all"
            and self.pager.count() > 1
        ):
            rows = -(-ALL_APPS_PAGE_SIZE // self._columnCount())
            margins = self.allGrid.contentsMargins()
            height = (
                rows * APPLICATION_CARD_HEIGHT
                + (rows - 1) * self.allGrid.verticalSpacing()
                + margins.top()
                + margins.bottom()
            )
        self.allGridWidget.setMinimumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.isVisible():
            self._scheduleLayoutUpdate()
            return
        # 主窗口切页时先把尚未显示的页面缩放到位再截快照，这一刻就得按最终列数排好；
        # 等到 showEvent 再排，过渡动画里就会先看到一张卡片占满一整行。
        self._layoutTimer.stop()
        self._applyLayoutUpdate()

    def _scheduleLayoutUpdate(self):
        if hasattr(self, "_layoutTimer"):
            self._layoutTimer.start()

    def _applyLayoutUpdate(self):
        self._reflowGrids()
        self._syncAdImageSize()

    def _updateVisibleCardState(self, appId):
        for card in self.findChildren(ApplicationCard):
            if card.appId == appId:
                self._setCardState(card, card.appData, card.installedPage)

    def _refreshPinStates(self, _cards=None):
        if self._shuttingDown:
            return
        for card in self.findChildren(ApplicationCard):
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
            pageCount = (
                max(1, (len(apps) + ALL_APPS_PAGE_SIZE - 1) // ALL_APPS_PAGE_SIZE)
                if paginated
                else 1
            )
            if self.pager.count() != pageCount:
                self.pager.setPageNumber(pageCount)
            self._currentPage = min(self._currentPage, pageCount - 1)
            if self.pager.currentIndex() != self._currentPage:
                self.pager.setCurrentIndex(self._currentPage)
            self.pager.setVisible(paginated)
            self.pagerBar.setVisible(paginated and bool(apps))
            self._updatePagerButtons()
            self._renderAllPage(apps)
            self._reserveAllGridHeight()
            self._updateAllEmptyState(apps)
        finally:
            self.pager.blockSignals(False)
            self._renderingAll = False

    def _renderAllPage(self, apps=None):
        apps = self._allAppsForPage() if apps is None else apps
        if self.categoryPivot.currentRouteKey() == "all":
            start = self._currentPage * ALL_APPS_PAGE_SIZE
            apps = apps[start : start + ALL_APPS_PAGE_SIZE]
        self._renderGrid(self.allGrid, apps)

    def _updateAllEmptyState(self, apps):
        self.allEmpty.setVisible(not apps)
        if apps:
            self._allEmptyAction = None
            return
        if self.searchText:
            content = (
                "未找到匹配的应用",
                "试试其他关键词，或清除搜索查看全部应用。",
                "清除搜索",
            )
            action = self._clearSearch
        elif not self.catalog and self._catalogError:
            content = ("应用目录加载失败", self._catalogError, "重试")
            action = self._loadCatalog
        elif not self._catalogLoaded and self._catalogLoading:
            content = ("正在加载应用目录", "请稍候，加载完成后会显示在这里。", "")
            action = None
        elif self.categoryPivot.currentRouteKey() == "recommended" and any(
            app.get("catalog_available", True) for app in self._mergedApps()
        ):
            content = (
                "暂无推荐应用",
                "切换到“全部”查看所有可用的应用。",
                "查看全部",
            )
            action = self._showAllCategory
        else:
            content = ("暂无可用应用", "应用目录还是空的，稍后再来看看。", "")
            action = None
        self.allEmpty.setContent(*content)
        self._allEmptyAction = action

    def _onPageChanged(self, index):
        if self._renderingAll or index == self._currentPage:
            return
        forward = index > self._currentPage

        def change():
            self._currentPage = index
            self._updatePagerButtons()
            self._renderAllPage()

        self.allGridSlide.run(change, forward)
        self._scrollAllToListStart()

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

    def _fitAdText(self):
        # 描述按实际行数占高度：固定预留两行时，一行描述会在按钮上方空出一整行，
        # 还把整组文字往上顶。行数取决于布局后的宽度，所以改完高度要再排一次。
        lines = len(self._adDescriptionElide.displayLines(self.adDescription))
        height = self.adDescription.fontMetrics().lineSpacing() * max(1, min(2, lines))
        if self.adDescription.height() != height:
            self.adDescription.setFixedHeight(height)
            self.adOverlay.layout().setGeometry(self.adOverlay.rect())
        overlayHeight = self.adOverlay.height()
        if overlayHeight <= 0:
            return
        # 只提前、不推后：文字块矮时仍从 AD_SCRIM_START 起压暗。
        start = round(
            max(0.0, min(AD_SCRIM_START, (self.adTitle.y() - AD_SCRIM_LEAD_PX) / overlayHeight)),
            2,
        )
        if start != self._adScrimStart:
            self._adScrimStart = start
            self.adOverlay.setStyleSheet(_adOverlayStyle(start))

    def _positionAdOverlay(self):
        viewportGeometry = self.adFlipView.viewport().geometry()
        self.adOverlay.setGeometry(viewportGeometry)
        # The overlay is positioned manually (outside the flip view layout), so
        # keep its content layout in sync with the new viewport size immediately.
        if self.adOverlay.layout() is not None:
            self.adOverlay.layout().setGeometry(self.adOverlay.rect())
            self._fitAdText()
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
        self._populateDetail(app)
        self.detailLeftScroll.verticalScrollBar().setValue(0)
        self.presetScroll.verticalScrollBar().setValue(0)
        self.stack.setCurrentWidget(self.detail)

    def _populateDetail(self, app):
        self.currentApp = app
        self._pauseAds()
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

    def _backToOverview(self):
        self.currentApp = None
        target = 0 if self.pivot.currentRouteKey() == "installed" else 1
        if target == 0:
            self._renderInstalled()
        else:
            self._renderAll()
        if self.catalogStack.currentIndex() != target:
            # 列表页此刻被详情挡着，直接换好选项卡，不在看不见的地方播横移。
            self.catalogStack._stopAnimation()
            QStackedWidget.setCurrentIndex(self.catalogStack, target)
        self.stack.setCurrentIndex(0, isBack=True)
        self._resumeAds()

    def _updateDetailAction(self):
        if not self.currentApp:
            return
        appId = int(self.currentApp["id"])
        busy = self._isBusy(appId)
        actionText, enabled = self._actionState(self.currentApp, showUpdate=True)
        self.detailAction.setText(actionText)
        self.detailAction.setEnabled(enabled and not busy)
        self._applyProgress(self.detailAction, appId)
        for openButton, pinButton, available, pinned in self._presetActionButtons:
            openButton.setEnabled(available and not busy)
            pinButton.setEnabled((available or pinned) and not busy)

    def _onDetailAction(self):
        if self.currentApp:
            self._onAppAction(self.currentApp)

    def _onAppAction(self, app, allowUpdate=True):
        appId = int(app["id"])
        if self._isBusy(appId):
            return
        if app.get("installed") and (
            not app.get("update_available") or not allowUpdate
        ):
            self._startLaunch(app)
            return
        try:
            self.store.downloadSlots.acquire()
        except ApplicationStoreError as error:
            InfoBar.warning("下载任务已满", str(error), duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        worker = None
        try:
            worker = downloadWorker(app, self.store)
            thread = threading.Thread(
                target=self._downloadInBackground,
                args=(app, worker),
                daemon=True,
            )
        except Exception as error:
            self.store.downloadSlots.release()
            if worker is not None:
                worker.deleteLater()
            InfoBar.error("无法开始下载", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._downloadJobs[appId] = (thread, worker)
        self._downloadStates[appId] = "下载中 0%"
        self._downloadProgress[appId] = 0
        worker.progressChanged.connect(
            lambda done, total, _speed, _workers, appId=appId: self._downloadProgressSignal.emit(
                appId, done, total
            )
        )
        worker.retrying.connect(
            lambda _try, _total, message, name=str(app.get("name", "")): self._downloadRetrySignal.emit(
                name, message
            )
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
            self._downloadProgress.pop(appId, None)
            self.store.downloadSlots.release()
            worker.deleteLater()
            InfoBar.error("无法开始下载", str(error), duration=4000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._updateVisibleCardState(appId)
        self._updateDetailAction()

    def _isBusy(self, appId):
        return (
            appId in self._downloadJobs
            or appId in self._launching
            or appId in self._installing
            or appId in self._uninstalling
        )

    def _startLaunch(self, app, preset=None):
        # 打开应用和打开预设共用"打开中"：卡片、详情按钮和预设按钮一起禁用，
        # 同一应用不会并发出第二次启动。
        appId = int(app["id"])
        self._launching.add(appId)
        self._downloadStates[appId] = "打开中"
        self._updateVisibleCardState(appId)
        self._updateDetailAction()
        errorTitle = "无法打开应用" if preset is None else "无法打开预设"
        try:
            thread = threading.Thread(
                target=self._launchInBackground,
                args=(app, preset, errorTitle),
                daemon=True,
            )
            with self._fileOperationLock:
                self._fileOperationThreads.add(thread)
            try:
                thread.start()
            except Exception:
                with self._fileOperationLock:
                    self._fileOperationThreads.discard(thread)
                raise
        except Exception as error:
            self._onLaunchFinished(appId, str(error), errorTitle)

    def _launchInBackground(self, app, preset=None, errorTitle="无法打开应用"):
        appId = int(app["id"])
        errorMessage = ""
        try:
            local = self.store.installed().get(appId)
            if preset is None:
                self.store.executeAction(local or app)
            else:
                self.store.executeAction(local, self._presetAction(local, preset))
        except Exception as error:
            errorMessage = str(error)
        finally:
            with self._fileOperationLock:
                self._fileOperationThreads.discard(threading.current_thread())
        if not self._shuttingDown:
            self._launchFinished.emit(appId, errorMessage, errorTitle)

    def _presetAction(self, installed, preset):
        if installed is None:
            raise ApplicationStoreError("请先安装应用后再打开预设。")
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
            action = self._catalogExternalAction(preset)
        if not isinstance(action, dict):
            raise ApplicationStoreError("请先更新应用，再打开这个预设。")
        return action

    def _onLaunchFinished(self, appId, error, errorTitle="无法打开应用"):
        if self._shuttingDown or appId not in self._launching:
            return
        self._launching.discard(appId)
        self._downloadStates.pop(appId, None)
        self._updateVisibleCardState(appId)
        self._updateDetailAction()
        if error:
            InfoBar.error(
                errorTitle,
                error,
                duration=4000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self,
            )

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
        self._downloadProgress[appId] = percent
        self._updateVisibleCardState(appId)
        if self.currentApp and int(self.currentApp["id"]) == appId:
            self._updateDetailAction()

    def _downloadInBackground(self, app, worker):
        # 程序是否在运行原本要等下载、解压完、替换目录时才查；那时才失败，
        # 下载好的包也跟着删掉，关掉程序后还得整包重下。
        if app.get("installed"):
            try:
                running = self.store.applicationRunning(app)
            except Exception:
                running = False
            if running:
                worker.finished.emit("", "软件仍在运行，请完全退出后再更新", False)
                return
        worker.run()

    def _showDownloadRetry(self, name, message):
        title = f"{name} 下载重试" if name else "下载重试"
        InfoBar.warning(title, message, duration=2000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

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
            self._downloadProgress.pop(appId, None)
            self._updateVisibleCardState(appId)
            self._updateDetailAction()
            if error:
                title = "更新失败" if app.get("installed") else "下载失败"
                InfoBar.error(title, error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._installing.add(appId)
        self._downloadStates[appId] = "安装中"
        self._downloadProgress.pop(appId, None)
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
            self.store.downloadSlots.release()
            self._downloadStates.pop(appId, None)
            self._downloadProgress.pop(appId, None)
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
        self.store.downloadSlots.release()
        self._downloadStates.pop(appId, None)
        self._downloadProgress.pop(appId, None)
        if error:
            InfoBar.error("安装失败", error, duration=5000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            self._updateVisibleCardState(appId)
            self._updateDetailAction()
            return
        self._reloadState()
        InfoBar.success("安装完成", f"{installed.name} 已安装到 Program/{installed.installDir}。", duration=3500, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _confirmUninstall(self, app):
        appId = int(app["id"])
        if self._isBusy(appId):
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
        self._downloadProgress.pop(appId, None)
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
                widget = item.widget()
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
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
        for preset in presets:
            item = CardWidget(self.presetGroup)
            row = QHBoxLayout(item)
            row.setContentsMargins(14, 10, 14, 10)
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
            available = bool(app.get("installed")) and (
                str(preset.get("id", "")) in installedPresetIds
                or self._catalogExternalAction(preset) is not None
            )
            busy = self._isBusy(key[0])
            openButton = PushButton(FIF.PLAY, "打开", item)
            openButton.setAccessibleName("打开预设")
            openButton.setEnabled(available and not busy)
            openButton.clicked.connect(
                lambda _checked=False, appData=app, presetData=preset: self._openPreset(
                    appData, presetData
                )
            )
            row.addWidget(openButton)
            pin = ToggleToolButton(FIF.PIN, item)
            isPinned = key in pinned
            pin.setChecked(isPinned)
            pin.setEnabled((available or isPinned) and not busy)
            if isPinned:
                tooltip = "取消固定"
            elif available:
                tooltip = "固定到主页"
            elif not app.get("installed"):
                tooltip = "请先安装应用"
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
            # 固定、取消固定和目录刷新都会整组重建预设卡片。新卡片要等排队的
            # 显示事件才算可见，在那之前布局把整栏当成空的，滚动位置被夹回顶部。
            item.show()

    @staticmethod
    def _catalogExternalAction(preset):
        action = preset.get("action") if isinstance(preset, dict) else None
        if not isinstance(action, dict):
            return None
        actionType = str(action.get("type", "")).lower()
        target = str(action.get("target", "")).strip()
        if any(char in target for char in "\r\n\x00"):
            return None
        url = QUrl(target)
        if not url.isValid():
            return None
        if actionType == "url":
            if (
                url.scheme().lower() != "https"
                or not url.host()
                or url.userName()
                or url.password()
            ):
                return None
        elif (
            actionType != "uri"
            or url.scheme().lower() not in _LIVE_CATALOG_URI_SCHEMES
        ):
            return None
        return action

    def _currentCatalogPreset(self, appId, presetId):
        app = next(
            (
                item
                for item in self.catalog
                if isinstance(item, dict)
                and str(item.get("id", "")) == str(appId)
            ),
            None,
        )
        if app is None:
            return None
        presets = app.get("presets")
        if not isinstance(presets, list):
            return None
        return next(
            (
                item
                for item in presets
                if isinstance(item, dict)
                and str(item.get("id", "")) == str(presetId)
            ),
            None,
        )

    def _currentCatalogPresetAction(self, appId, presetId):
        preset = self._currentCatalogPreset(appId, presetId)
        return self._catalogExternalAction(preset)

    def _openPreset(self, app, preset):
        if not self._isBusy(int(app["id"])):
            self._startLaunch(app, preset)

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
        """Run an Application Home Card without blocking the GUI thread.

        Reading the installed manifests waits on the store lock, which an
        update or uninstall holds while it enumerates processes, and creating
        the process can stall on antivirus scans; the result arrives through
        `pinnedCardFailed` instead of a return value.
        """
        cards = normalize_pinned_cards([item])
        if not cards:
            self._showPinnedCardNotice(
                "warning", "预设卡片无效", "请重新固定这张主页卡片。"
            )
            self.pinnedCardFailed.emit()
            return
        item = cards[0]
        appId = item["app_id"]
        if appId in self._launching:
            return
        if self._isBusy(appId):
            self._showPinnedCardNotice(
                "warning",
                "应用暂时无法打开",
                "应用正在下载、安装或卸载，请完成后再试。",
            )
            self.pinnedCardFailed.emit()
            return
        # 目录只在界面线程里读写，先在这里取出，后台线程不碰它。
        catalogLoaded = self._catalogLoaded
        catalogPreset = None
        if item["preset_id"] != DIRECT_APPLICATION_PRESET_ID and catalogLoaded:
            catalogPreset = self._currentCatalogPreset(appId, item["preset_id"])
        self._launching.add(appId)
        self._downloadStates[appId] = "打开中"
        self._updateVisibleCardState(appId)
        self._updateDetailAction()
        try:
            thread = threading.Thread(
                target=self._executePinnedCardInBackground,
                args=(item, catalogLoaded, catalogPreset),
                daemon=True,
            )
            with self._fileOperationLock:
                self._fileOperationThreads.add(thread)
            try:
                thread.start()
            except Exception:
                with self._fileOperationLock:
                    self._fileOperationThreads.discard(thread)
                raise
        except Exception as error:
            self._onPinnedCardFinished(
                appId, False, "error", "执行预设失败", str(error)
            )

    def _executePinnedCardInBackground(self, item, catalogLoaded, catalogPreset):
        appId = item["app_id"]
        succeeded = False
        level = title = message = ""
        try:
            installed = self.store.installed().get(appId)
            if not installed:
                raise _PinnedCardNotice(
                    "warning",
                    "应用尚未安装",
                    "请先安装对应应用后再使用主页预设卡片。",
                )
            if item["preset_id"] == DIRECT_APPLICATION_PRESET_ID:
                result = self.store.executeAction(installed)
            else:
                action = self._pinnedPresetAction(
                    item, installed, catalogLoaded, catalogPreset
                )
                result = self.store.executeAction(installed, action)
            succeeded = bool(result)
        except _PinnedCardNotice as notice:
            level, title, message = notice.level, notice.title, str(notice)
        except (ApplicationStoreError, OSError, ValueError) as error:
            level, title, message = "error", "执行预设失败", str(error)
        except Exception as error:
            logger.exception("主页应用卡片执行失败")
            level, title, message = "error", "执行预设失败", str(error)
        finally:
            with self._fileOperationLock:
                self._fileOperationThreads.discard(threading.current_thread())
        if not self._shuttingDown:
            self._pinnedCardFinished.emit(appId, succeeded, level, title, message)

    def _pinnedPresetAction(self, item, installed, catalogLoaded, catalogPreset):
        localPreset = next(
            (
                preset
                for preset in installed.metadata.get("presets", [])
                if isinstance(preset, dict)
                and str(preset.get("id", "")) == str(item["preset_id"])
            ),
            None,
        )
        action = None
        if catalogLoaded:
            if catalogPreset is not None:
                catalogAction = self._catalogExternalAction(catalogPreset)
                if catalogAction is not None:
                    action = catalogAction
                elif (
                    isinstance(catalogPreset.get("action"), dict)
                    and catalogPreset["action"].get("type") == "program"
                    and isinstance(localPreset, dict)
                ):
                    action = localPreset.get("action")
        elif isinstance(localPreset, dict):
            action = localPreset.get("action")
        if not isinstance(action, dict) and not catalogLoaded:
            action = self._catalogExternalAction(item)
        if not isinstance(action, dict):
            raise _PinnedCardNotice(
                "warning",
                "主页卡片已失效",
                "请在应用详情中重新固定这张预设卡片。",
            )
        return action

    def _onPinnedCardFinished(self, appId, succeeded, level, title, message):
        if self._shuttingDown or appId not in self._launching:
            return
        self._launching.discard(appId)
        self._downloadStates.pop(appId, None)
        self._updateVisibleCardState(appId)
        self._updateDetailAction()
        if message:
            self._showPinnedCardNotice(level, title, message)
        if not succeeded:
            self.pinnedCardFailed.emit()

    def _showPinnedCardNotice(self, level, title, message):
        show = InfoBar.warning if level == "warning" else InfoBar.error
        show(
            title,
            message,
            duration=3000 if level == "warning" else 4000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self.window(),
        )

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
