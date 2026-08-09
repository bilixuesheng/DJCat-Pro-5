import threading
from math import ceil
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FlipView,
    FlowLayout,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PipsPager,
    Pivot,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.app_store import (
    APP_STORE_TEMP_DIR,
    downloadPackage,
    executeAction,
    fetchCachedImage,
    fetchCatalog,
    installedApplications,
)
from app.config.cfg import cfg
from app.platform.app_maintenance import performMaintenance
from app.signal_bus import signalBus
from app.view.components.scroll_area import ScrollArea


PAGE_SIZE = 15


class CachedImageLabel(QLabel):
    imageReady = Signal(str, str)

    def __init__(self, size: QSize, parent=None):
        super().__init__(parent)
        self._url = ""
        self.setFixedSize(size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: rgba(128, 128, 128, 0.12); border-radius: 10px;")
        self.imageReady.connect(self._onImageReady)

    def setUrl(self, url: str) -> None:
        self._url = url
        threading.Thread(target=self._load, args=(url,), daemon=True).start()

    def _load(self, url: str) -> None:
        path = fetchCachedImage(url)
        try:
            self.imageReady.emit(url, str(path) if path else "")
        except RuntimeError:
            pass

    def _onImageReady(self, url: str, path: str) -> None:
        if url != self._url or not path:
            return
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.setPixmap(
                pixmap.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class StoreAppCard(CardWidget):
    detailRequested = Signal(dict)
    actionRequested = Signal(dict, str)

    def __init__(self, application, actionText, actionName, installedPage, parent=None):
        super().__init__(parent)
        self.application = application
        self.setFixedSize(300, 142)
        self.setClickEnabled(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 14, 14)
        icon = CachedImageLabel(QSize(52, 52), self)
        icon.setUrl(application.get("icon_url", ""))
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        contentLayout = QVBoxLayout()
        contentLayout.setSpacing(4)
        title = SubtitleLabel(application.get("name", "未知应用"), self)
        description = BodyLabel(application.get("description", ""), self)
        description.setWordWrap(True)
        description.setMaximumHeight(42)
        contentLayout.addWidget(title)
        contentLayout.addWidget(description)
        contentLayout.addStretch(1)
        buttonLayout = QHBoxLayout()
        buttonLayout.setContentsMargins(0, 2, 0, 0)
        self.primaryButton = PrimaryPushButton(self)
        self.primaryButton.setText(actionText)
        self.primaryButton.setIcon(
            FIF.UPDATE
            if actionName == "update"
            else FIF.PLAY
            if actionName == "open"
            else FIF.DOWNLOAD
        )
        self.primaryButton.clicked.connect(
            lambda: self.actionRequested.emit(self.application, actionName)
        )
        buttonLayout.addWidget(self.primaryButton)
        if installedPage:
            self.uninstallButton = ToolButton(FIF.DELETE, self)
            self.uninstallButton.setToolTip("卸载")
            self.uninstallButton.setAccessibleName(f"卸载{application.get('name', '')}")
            self.uninstallButton.setStyleSheet(
                "ToolButton { color: white; background: #d13438; border-radius: 6px; }"
            )
            self.uninstallButton.clicked.connect(
                lambda: self.actionRequested.emit(self.application, "uninstall")
            )
            buttonLayout.addWidget(self.uninstallButton)
        buttonLayout.addStretch(1)
        contentLayout.addLayout(buttonLayout)
        layout.addLayout(contentLayout, 1)
        self.clicked.connect(lambda: self.detailRequested.emit(self.application))


class AdOverlay(QWidget):
    appRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._appId = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.addStretch(1)
        self.titleLabel = TitleLabel("", self)
        self.descriptionLabel = BodyLabel("", self)
        self.titleLabel.setStyleSheet("color: white; background: transparent;")
        self.descriptionLabel.setStyleSheet("color: white; background: transparent;")
        self.descriptionLabel.setWordWrap(True)
        layout.addWidget(self.titleLabel)
        layout.addWidget(self.descriptionLabel)
        buttonLayout = QHBoxLayout()
        self.button = PrimaryPushButton(FIF.APPLICATION, "查看应用", self)
        self.button.clicked.connect(lambda: self.appRequested.emit(self._appId))
        buttonLayout.addWidget(self.button)
        buttonLayout.addStretch(1)
        layout.addLayout(buttonLayout)

    def setAdvertisement(self, advertisement: dict) -> None:
        self._appId = int(advertisement.get("app_id", 0))
        self.titleLabel.setText(advertisement.get("title", ""))
        self.descriptionLabel.setText(advertisement.get("description", ""))

    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.35, QColor(0, 0, 0, 115))
        gradient.setColorAt(1, QColor(0, 0, 0, 225))
        painter.fillRect(self.rect(), gradient)
        super().paintEvent(event)


class AdvertisementCarousel(QWidget):
    appRequested = Signal(int)
    imageReady = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(280)
        self._advertisements = []
        self.flipView = FlipView(self)
        self.flipView.setBorderRadius(12)
        self.overlay = AdOverlay(self)
        self.overlay.appRequested.connect(self.appRequested)
        self.pager = PipsPager(self)
        self.timer = QTimer(self)
        self.timer.setInterval(5000)
        self.timer.timeout.connect(self._next)
        self.flipView.currentIndexChanged.connect(self._onIndexChanged)
        self.pager.currentIndexChanged.connect(self.flipView.setCurrentIndex)
        self.imageReady.connect(self._setImage)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.flipView)

    def setAdvertisements(self, advertisements: list[dict]) -> None:
        self._advertisements = advertisements
        self.flipView.clear()
        self.timer.stop()
        if not advertisements:
            self.hide()
            return
        self.show()
        placeholder = QPixmap(900, 250)
        placeholder.fill(QColor(55, 55, 55))
        for index, advertisement in enumerate(advertisements):
            self.flipView.addImage(placeholder)
            threading.Thread(
                target=self._loadImage,
                args=(index, advertisement.get("image_url", "")),
                daemon=True,
            ).start()
        self.pager.setPageNumber(len(advertisements))
        self.flipView.setCurrentIndex(0)
        self._onIndexChanged(0)
        if len(advertisements) > 1:
            self.timer.start()

    def _loadImage(self, index: int, url: str) -> None:
        path = fetchCachedImage(url)
        try:
            self.imageReady.emit(index, str(path) if path else "")
        except RuntimeError:
            pass

    def _setImage(self, index: int, path: str) -> None:
        if path and index < self.flipView.count():
            self.flipView.setItemImage(index, path)

    def _onIndexChanged(self, index: int) -> None:
        if not 0 <= index < len(self._advertisements):
            return
        self.overlay.setAdvertisement(self._advertisements[index])
        if self.pager.currentIndex() != index:
            self.pager.setCurrentIndex(index)

    def _next(self) -> None:
        if self._advertisements:
            self.flipView.setCurrentIndex(
                (self.flipView.currentIndex() + 1) % len(self._advertisements)
            )

    def enterEvent(self, event):
        self.timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if len(self._advertisements) > 1:
            self.timer.start()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = QSize(max(480, self.width()), self.height())
        self.flipView.setItemSize(size)
        self.overlay.setGeometry(0, self.height() // 2, self.width(), self.height() // 2)
        self.pager.move(
            self.width() - self.pager.width() - 18,
            self.height() - self.pager.height() - 14,
        )
        self.overlay.raise_()
        self.pager.raise_()


class AppOperationWorker(QObject):
    progressChanged = Signal(int, int)
    finished = Signal(str, dict, str)

    def __init__(self, operation: str, application: dict):
        super().__init__()
        self.operation = operation
        self.application = application

    def run(self) -> None:
        archive = None
        try:
            if self.operation in {"install", "update"}:
                archive = downloadPackage(
                    self.application["download_url"],
                    progress=self.progressChanged.emit,
                )
                performMaintenance("install", self.application, archive)
            elif self.operation == "uninstall":
                performMaintenance("uninstall", self.application)
            else:
                raise ValueError("不支持的应用操作")
            error = ""
        except Exception as exception:
            error = str(exception)
        finally:
            if archive is not None:
                Path(archive).unlink(missing_ok=True)
        try:
            self.finished.emit(self.operation, self.application, error)
        except RuntimeError:
            pass


class AppStorePage(QWidget):
    catalogReceived = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AppStorePage")
        self._loaded = False
        self._catalogLoaded = False
        self._catalogLoading = False
        self._searchText = ""
        self._catalog = {"apps": [], "ads": []}
        self._installed = []
        self._page = 1
        self._operationWorker = None
        self._operationThread = None
        self.catalogReceived.connect(self._onCatalogReceived)
        signalBus.appStoreCacheCleared.connect(self._onCacheCleared)

    @property
    def isLoaded(self):
        return self._loaded

    def showEvent(self, event):
        self.ensureLoaded()
        super().showEvent(event)

    def ensureLoaded(self) -> None:
        if not self._loaded:
            self._loaded = True
            rootLayout = QVBoxLayout(self)
            rootLayout.setContentsMargins(0, 0, 0, 0)
            self.stack = QStackedWidget(self)
            rootLayout.addWidget(self.stack)
            self._buildOverview()
            self.detailPage = None
            self._refreshInstalled()
        self._startCatalogFetch()

    def _startCatalogFetch(self) -> None:
        if self._catalogLoaded or self._catalogLoading:
            return
        self._catalogLoading = True
        threading.Thread(target=self._fetchCatalog, daemon=True).start()

    def _buildOverview(self) -> None:
        self.overview = ScrollArea(self)
        self.overviewContainer = QWidget()
        self.overviewLayout = QVBoxLayout(self.overviewContainer)
        self.overviewLayout.setContentsMargins(30, 20, 30, 36)
        self.overviewLayout.setSpacing(14)
        self.overviewLayout.addWidget(TitleLabel("应用市场", self.overviewContainer))
        self.topPivot = Pivot(self.overviewContainer)
        self.topPivot.addItem("installed", "已安装")
        self.topPivot.addItem("all", "全部应用")
        self.topPivot.currentItemChanged.connect(self._switchTopSection)
        self.overviewLayout.addWidget(self.topPivot)
        self.sectionStack = QStackedWidget(self.overviewContainer)
        self.installedSection = QWidget(self.sectionStack)
        self.installedLayout = QVBoxLayout(self.installedSection)
        self.installedLayout.setContentsMargins(0, 8, 0, 0)
        self.allSection = QWidget(self.sectionStack)
        self.allLayout = QVBoxLayout(self.allSection)
        self.allLayout.setContentsMargins(0, 8, 0, 0)
        self.allLayout.setSpacing(14)
        self.carousel = AdvertisementCarousel(self.allSection)
        self.carousel.appRequested.connect(self._showAppById)
        self.allLayout.addWidget(self.carousel)
        self.categoryPivot = Pivot(self.allSection)
        self.categoryPivot.addItem("recommended", "推荐")
        self.categoryPivot.addItem("all", "全部")
        self.categoryPivot.currentItemChanged.connect(self._switchCategory)
        self.allLayout.addWidget(self.categoryPivot)
        self.catalogCardsSlot = QVBoxLayout()
        self.allLayout.addLayout(self.catalogCardsSlot)
        self.pagerLayout = QHBoxLayout()
        self.pagerLayout.addStretch(1)
        self.allLayout.addLayout(self.pagerLayout)
        self.allLayout.addStretch(1)
        self.sectionStack.addWidget(self.installedSection)
        self.sectionStack.addWidget(self.allSection)
        self.overviewLayout.addWidget(self.sectionStack, 1)
        self.overview.setWidget(self.overviewContainer)
        self.overview.setWidgetResizable(True)
        self.overview.enableTransparentBackground()
        self.stack.addWidget(self.overview)
        self.topPivot.setCurrentItem("installed")
        self.categoryPivot.setCurrentItem("recommended")

    def _fetchCatalog(self) -> None:
        catalog = fetchCatalog()
        try:
            self.catalogReceived.emit(catalog)
        except RuntimeError:
            pass

    def _onCatalogReceived(self, catalog) -> None:
        self._catalogLoading = False
        if catalog is None:
            self._showInfo("无法获取应用目录", "请检查网络后重新进入应用市场。", error=True)
            return
        self._catalogLoaded = True
        self._catalog = catalog
        self.carousel.setAdvertisements(catalog.get("ads", []))
        self._renderCurrentSection()

    def _onCacheCleared(self) -> None:
        if not self._loaded:
            return
        self.carousel.setAdvertisements(self._catalog.get("ads", []))
        self._renderCurrentSection()

    def _refreshInstalled(self) -> None:
        self._installed = installedApplications()
        if self._loaded:
            self._renderInstalled()

    def _catalogById(self):
        return {int(app["id"]): app for app in self._catalog.get("apps", [])}

    def _installedById(self):
        return {int(app["id"]): app for app in self._installed}

    def _mergedInstalled(self):
        catalog = self._catalogById()
        merged = []
        for local in self._installed:
            current = catalog.get(int(local["id"]), {})
            item = {**local, **current}
            for key in ("open_action", "components"):
                if key in local:
                    item[key] = local[key]
            item["installed_version"] = local.get("version", "")
            item["update_available"] = bool(
                current and current.get("version") != local.get("version")
            )
            merged.append(item)
        return merged

    def _matchesSearch(self, application: dict) -> bool:
        if not self._searchText:
            return True
        target = " ".join(
            str(application.get(key, ""))
            for key in ("name", "developer", "description")
        ).casefold()
        return self._searchText in target

    def _replaceCards(self, layout, cards, emptyText):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        widget = QWidget()
        flow = FlowLayout(widget, needAni=True)
        flow.setContentsMargins(0, 6, 0, 12)
        for card in cards:
            flow.addWidget(card)
        if not cards:
            label = BodyLabel(emptyText, widget)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(120)
            flow.addWidget(label)
        layout.addWidget(widget)

    def _appCard(self, application, installedPage=False):
        installed = int(application["id"]) in self._installedById()
        if installedPage and application.get("update_available"):
            text, action = "更新", "update"
        elif installed:
            text, action = "打开", "open"
        else:
            text, action = "下载", "install"
        card = StoreAppCard(application, text, action, installedPage, self)
        card.detailRequested.connect(self.showDetails)
        card.actionRequested.connect(self._handleAction)
        return card

    def _renderInstalled(self) -> None:
        applications = [
            app for app in self._mergedInstalled() if self._matchesSearch(app)
        ]
        cards = [self._appCard(app, True) for app in applications]
        self._replaceCards(self.installedLayout, cards, "尚未安装应用")
        self.installedLayout.addStretch(1)

    def _renderCatalog(self) -> None:
        category = self.categoryPivot.currentRouteKey() or "recommended"
        applications = [
            app
            for app in self._catalog.get("apps", [])
            if self._matchesSearch(app)
            and (category == "all" or app.get("recommended"))
        ]
        if category == "all":
            pageCount = max(1, ceil(len(applications) / PAGE_SIZE))
            self._page = min(self._page, pageCount)
            start = (self._page - 1) * PAGE_SIZE
            applications = applications[start : start + PAGE_SIZE]
        else:
            pageCount = 1
            self._page = 1
        cards = [self._appCard(app) for app in applications]
        self._replaceCards(self.catalogCardsSlot, cards, "暂无符合条件的应用")
        self._renderPager(pageCount if category == "all" else 0)

    def _renderPager(self, pageCount: int) -> None:
        while self.pagerLayout.count() > 1:
            item = self.pagerLayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for page in range(1, pageCount + 1):
            button = PrimaryPushButton(str(page), self.allSection) if page == self._page else PushButton(str(page), self.allSection)
            button.setFixedWidth(36)
            button.clicked.connect(lambda checked=False, value=page: self._setPage(value))
            self.pagerLayout.insertWidget(self.pagerLayout.count() - 1, button)

    def _setPage(self, page: int) -> None:
        self._page = page
        self._renderCatalog()

    def _switchTopSection(self, routeKey: str) -> None:
        self.sectionStack.setCurrentWidget(
            self.installedSection if routeKey == "installed" else self.allSection
        )
        self._renderCurrentSection()

    def _switchCategory(self, _routeKey: str) -> None:
        self._page = 1
        self._renderCatalog()

    def _renderCurrentSection(self) -> None:
        if not self._loaded:
            return
        if self.topPivot.currentRouteKey() == "all":
            self._renderCatalog()
        else:
            self._renderInstalled()

    def setSearchText(self, text: str) -> None:
        self._searchText = text.strip().casefold()
        self._page = 1
        if self._loaded:
            self.stack.setCurrentWidget(self.overview)
            self._renderCurrentSection()

    def _showAppById(self, appId: int) -> None:
        application = self._catalogById().get(appId)
        if application:
            self.showDetails(application)

    def showDetails(self, application: dict) -> None:
        if self.detailPage is not None:
            self.stack.removeWidget(self.detailPage)
            self.detailPage.deleteLater()
        installed = int(application["id"]) in self._installedById()
        self.detailPage = ScrollArea(self)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 20, 30, 36)
        backButton = PushButton(FIF.RETURN, "返回应用市场", container)
        backButton.clicked.connect(lambda: self.stack.setCurrentWidget(self.overview))
        layout.addWidget(backButton, 0, Qt.AlignmentFlag.AlignLeft)
        columns = QHBoxLayout()
        columns.setSpacing(28)
        left = QVBoxLayout()
        icon = CachedImageLabel(QSize(104, 104), container)
        icon.setUrl(application.get("icon_url", ""))
        left.addWidget(icon)
        left.addWidget(TitleLabel(application.get("name", ""), container))
        left.addWidget(BodyLabel(f"开发者：{application.get('developer', '')}", container))
        left.addWidget(BodyLabel(f"版本：{application.get('version', '')}", container))
        actionButton = PrimaryPushButton(
            FIF.PLAY if installed else FIF.DOWNLOAD,
            "打开" if installed else "下载",
            container,
        )
        actionButton.clicked.connect(
            lambda: self._handleAction(application, "open" if installed else "install")
        )
        left.addWidget(actionButton)
        left.addStretch(1)
        columns.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(SubtitleLabel("预设卡片", container))
        components = application.get("components", [])
        if not components:
            right.addWidget(BodyLabel("该应用暂不支持预设卡片", container))
        for component in components:
            card = CardWidget(container)
            cardLayout = QHBoxLayout(card)
            componentIcon = CachedImageLabel(QSize(48, 48), card)
            componentIcon.setUrl(application.get("icon_url", ""))
            cardLayout.addWidget(componentIcon, 0, Qt.AlignmentFlag.AlignTop)
            componentLayout = QVBoxLayout()
            componentLayout.addWidget(SubtitleLabel(component.get("title", ""), card))
            description = BodyLabel(component.get("description", ""), card)
            description.setWordWrap(True)
            componentLayout.addWidget(description)
            pinned = self._isPinned(application, component)
            button = PushButton(
                FIF.ACCEPT if pinned else FIF.PIN,
                "已固定" if pinned else "固定到主页",
                card,
            )
            button.setEnabled(installed and not pinned)
            button.clicked.connect(
                lambda checked=False, app=application, item=component: self._pinComponent(app, item)
            )
            componentLayout.addWidget(button, 0, Qt.AlignmentFlag.AlignLeft)
            cardLayout.addLayout(componentLayout, 1)
            right.addWidget(card)
        right.addStretch(1)
        columns.addLayout(right, 2)
        layout.addLayout(columns, 1)
        self.detailPage.setWidget(container)
        self.detailPage.setWidgetResizable(True)
        self.detailPage.enableTransparentBackground()
        self.stack.addWidget(self.detailPage)
        self.stack.setCurrentWidget(self.detailPage)

    @staticmethod
    def _cardKey(application, component):
        return f"app:{int(application['id'])}:component:{int(component['id'])}"

    def _isPinned(self, application, component):
        key = self._cardKey(application, component)
        return any(card.get("key") == key for card in cfg.pinnedHomeCards.value)

    def _pinComponent(self, application, component) -> None:
        if self._isPinned(application, component):
            return
        cards = list(cfg.pinnedHomeCards.value)
        cards.append(
            {
                "key": self._cardKey(application, component),
                "app_id": int(application["id"]),
                "install_dir": application["install_dir"],
                "name": application["name"],
                "title": component["title"],
                "description": component["description"],
                "icon_url": application.get("icon_url", ""),
                "action": component["action"],
            }
        )
        cfg.set(cfg.pinnedHomeCards, cards)
        signalBus.homeCardsChanged.emit()
        self.showDetails(application)

    def _handleAction(self, application: dict, action: str) -> None:
        if action == "open":
            try:
                installed = self._installedById().get(int(application["id"]), {})
                runtimeApplication = {**application, **installed}
                executeAction(runtimeApplication, runtimeApplication["open_action"])
            except (OSError, ValueError, KeyError) as error:
                self._showInfo("无法打开应用", str(error), error=True)
            return
        if action == "uninstall":
            dialog = MessageBox(
                "确认卸载",
                f"将删除 Program/{application['install_dir']} 及其中全部文件。",
                self.window(),
            )
            dialog.yesButton.setText("卸载")
            dialog.cancelButton.setText("取消")
            if not dialog.exec():
                return
        self._startOperation(action, application)

    def _startOperation(self, operation: str, application: dict) -> None:
        if self._operationWorker is not None:
            self._showInfo("正在处理其他应用", "请等待当前操作完成。")
            return
        self._operationWorker = AppOperationWorker(operation, application)
        self._operationWorker.progressChanged.connect(self._onProgress)
        self._operationWorker.finished.connect(self._onOperationFinished)
        self._operationThread = threading.Thread(
            target=self._operationWorker.run
        )
        self._operationThread.start()
        self._showInfo("应用处理中", f"正在{self._operationName(operation)}…")

    def _onProgress(self, downloaded: int, total: int) -> None:
        if not total:
            return
        percent = min(100, downloaded * 100 // total)
        self.setToolTip(f"应用下载进度：{percent}%")

    def _onOperationFinished(self, operation: str, application: dict, error: str) -> None:
        worker = self._operationWorker
        self._operationWorker = None
        self._operationThread = None
        if worker is not None:
            worker.deleteLater()
        self.setToolTip("")
        if error:
            self._showInfo(f"{self._operationName(operation)}失败", error, error=True)
            return
        if operation == "uninstall":
            appId = int(application["id"])
            cards = [
                card for card in cfg.pinnedHomeCards.value if int(card.get("app_id", 0)) != appId
            ]
            cfg.set(cfg.pinnedHomeCards, cards)
            signalBus.homeCardsChanged.emit()
        self._refreshInstalled()
        self.stack.setCurrentWidget(self.overview)
        self._renderCurrentSection()
        self._showInfo(f"{self._operationName(operation)}完成", application.get("name", ""))

    @staticmethod
    def _operationName(operation: str):
        return {"install": "安装", "update": "更新", "uninstall": "卸载"}.get(operation, "操作")

    def _showInfo(self, title: str, content: str, error=False) -> None:
        factory = InfoBar.error if error else InfoBar.success
        factory(
            title,
            content,
            duration=4000,
            position=InfoBarPosition.TOP_RIGHT,
            parent=self.window(),
        )
