import os
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QInputDevice
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QScroller, QWidget
from qfluentwidgets import (
    CardWidget,
    InfoBar,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ToggleToolButton,
    qconfig,
)

from app.config.cfg import cfg
from app.view.components.scroll_area import ScrollArea
from app.view.pages.app_store_page import (
    ActionProgressButton,
    ApplicationCard,
    AppStorePage,
    CatalogImageWorker,
    CatalogWorker,
    HorizontalTransitionStackedWidget,
)


class _Store:
    architecture = "x86_64"

    def mergeInstalled(self, apps):
        return list(apps)

    def shutdown(self):
        pass


class _CancelableWorker(QObject):
    finished = Signal()

    def __init__(self):
        super().__init__()
        self.cancelEvent = threading.Event()

    def run(self):
        self.cancelEvent.wait()
        self.finished.emit()

    def cancel(self):
        self.cancelEvent.set()


class _IgnoringCancelWorker:
    def __init__(self):
        self.canceled = threading.Event()
        self.release = threading.Event()

    def run(self):
        self.release.wait()

    def cancel(self):
        self.canceled.set()


class _BlockingCatalogStore:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def fetchCatalog(self):
        self.started.set()
        self.release.wait()
        return {"apps": [], "ads": []}


class _SlowImageStore:
    def __init__(self):
        self.imageStarted = threading.Event()
        self.releaseImage = threading.Event()
        self.imageFinished = threading.Event()

    def fetchCatalog(self):
        return {
            "apps": [{"id": 1, "icon_url": "https://example.test/icon.png"}],
            "ads": [],
        }

    def imagePath(self, _url):
        self.imageStarted.set()
        self.releaseImage.wait()
        self.imageFinished.set()
        return "cached.png"


def _apps(count):
    return [
        {
            "id": index,
            "name": f"App {index}",
            "description": "A long application description that should be elided.",
            "architecture_supported": True,
            "packages": {"x86_64": {"enabled": True}},
            "installed": False,
            "update_available": False,
        }
        for index in range(count)
    ]


class AppStorePageTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtApp = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        with patch("app.view.pages.app_store_page.ApplicationStore", return_value=_Store()):
            self.page = AppStorePage()
        self.page._catalogLoaded = True

    def tearDown(self):
        self.page.shutdown()
        self.page.close()
        self.page.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.qtApp.processEvents()

    def _waitForLaunch(self):
        deadline = time.monotonic() + 1
        while self.page._launching and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertFalse(self.page._launching)

    def testPagerClickDoesNotRebuildItems(self):
        apps = _apps(7)
        self.page.categoryPivot.setCurrentItem("all")
        self.page._allAppsForPage = lambda: apps
        self.page._renderAll()
        item = self.page.pager.item(1)

        self.page.pager._setPressedItem(item)

        self.assertEqual(self.page._currentPage, 1)
        self.assertEqual(self.page.pager.count(), 2)
        self.assertIsNotNone(self.page.allGrid.itemAtPosition(0, 0))

    def testAllCategoryAlwaysShowsPager(self):
        self.page.categoryPivot.setCurrentItem("all")
        self.page._allAppsForPage = lambda: _apps(1)
        self.page._renderAll()

        self.assertFalse(self.page.pager.isHidden())
        self.assertFalse(self.page.pagerBar.isHidden())

    def testPaginationButtonsAreTouchFriendlyAndNavigate(self):
        self.page.categoryPivot.setCurrentItem("all")
        self.page._allAppsForPage = lambda: _apps(7)
        self.page._renderAll()

        for button in (self.page.pagerPrevious, self.page.pagerNext):
            self.assertLess(button.width(), 40)
            self.assertLess(button.height(), 40)
            self.assertLess(button.minimumHeight(), button.maximumHeight())
        self.assertFalse(self.page.pagerPrevious.isEnabled())
        self.assertTrue(self.page.pagerNext.isEnabled())

        self.page.pagerNext.click()

        self.assertEqual(self.page._currentPage, 1)
        self.assertFalse(self.page.pagerNext.isEnabled())

    def testAllCategoryShowsAtMostSixApplicationsPerPage(self):
        apps = _apps(7)
        self.page.categoryPivot.setCurrentItem("all")
        self.page._allAppsForPage = lambda: apps

        self.page._renderAll()
        self.assertEqual(self.page.allGrid.count(), 6)

        self.page.pagerNext.click()
        self.assertEqual(self.page.allGrid.count(), 1)

    def testRecommendedCategoryShowsEveryRecommendedAppWithoutPager(self):
        apps = _apps(16)
        for app in apps:
            app["recommended"] = True
        self.page.catalog = apps
        self.page.categoryPivot.setCurrentItem("recommended")

        self.page._renderAll()

        self.assertTrue(self.page.pager.isHidden())
        self.assertEqual(self.page.allGrid.count(), 16)

    def testRecommendedCategoryUsesItsIndependentServerOrder(self):
        apps = _apps(3)
        for app, order in zip(apps, (2, 0, 1)):
            app["recommended"] = True
            app["recommended_order"] = order
        self.page.catalog = apps
        self.page.categoryPivot.setCurrentItem("recommended")

        self.assertEqual(
            [app["id"] for app in self.page._allAppsForPage()],
            [1, 2, 0],
        )

    def testProgressUpdatesExistingCardAndDisablesAction(self):
        apps = _apps(1)
        self.page._allAppsForPage = lambda: apps
        self.page._renderAll()
        card = self.page.allGrid.itemAtPosition(0, 0).widget()
        self.page._downloadJobs[0] = object()

        self.page._onDownloadProgress(0, 50, 100)
        self.page._downloadJobs.pop(0)

        self.assertIs(self.page.allGrid.itemAtPosition(0, 0).widget(), card)
        self.assertEqual(card.actionButton.text(), "下载中 50%")
        self.assertFalse(card.actionButton.isEnabled())
        self.assertFalse(card.removeButton.isEnabled())
        self.assertEqual(card.actionButton._progress, 50)

    def testDisabledProgressAlignsWithButtonCornersAndUsesThemeColor(self):
        button = ActionProgressButton("下载中")
        self.addCleanup(button.deleteLater)
        button.resize(120, 32)
        button.setEnabled(False)
        image = QImage(button.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        button.render(image)
        background = QImage(image)

        button.setProgress(100)
        button.render(image)

        color = qconfig.themeColor.value
        y = button.height() - 1
        self.assertEqual(image.pixelColor(6, y), color)
        self.assertEqual(image.pixelColor(button.width() - 7, y), color)
        for x in (*range(5), *range(button.width() - 5, button.width())):
            self.assertEqual(image.pixelColor(x, y), background.pixelColor(x, y))
        for x in (5, button.width() - 6):
            self.assertNotEqual(image.pixelColor(x, y), color)
            self.assertNotEqual(image.pixelColor(x, y), background.pixelColor(x, y))

    def testPartialProgressEndsWithRoundedCap(self):
        button = ActionProgressButton("下载中 50%")
        self.addCleanup(button.deleteLater)
        button.resize(120, 32)
        button.setEnabled(False)
        button.setProgress(50)
        image = QImage(button.size(), QImage.Format.Format_ARGB32)

        button.render(image)

        y = button.height() - 1
        color = qconfig.themeColor.value
        self.assertEqual(image.pixelColor(button.width() // 2 - 2, y), color)
        self.assertNotEqual(image.pixelColor(button.width() // 2 - 1, y), color)

    def testIndeterminateProgressUsesUpdatedThemeColor(self):
        button = ActionProgressButton("下载中 0%")
        self.addCleanup(button.deleteLater)
        button.resize(120, 32)
        button.setEnabled(False)
        button.setProgress(indeterminate=True)
        button._progressOffset = 0.5
        image = QImage(button.size(), QImage.Format.Format_ARGB32)
        originalColor = QColor(qconfig.themeColor.value)
        updatedColor = QColor("#b74291")

        try:
            qconfig.set(qconfig.themeColor, updatedColor, save=False)
            button.render(image)
            self.assertEqual(
                image.pixelColor(button.width() // 2, button.height() - 1),
                updatedColor,
            )
        finally:
            qconfig.set(qconfig.themeColor, originalColor, save=False)

    def testZeroDownloadProgressIsIndeterminateOnCardsAndDetails(self):
        app = _apps(1)[0]
        appId = app["id"]
        card = ApplicationCard()
        self.addCleanup(card.deleteLater)
        self.page._downloadJobs[appId] = object()
        self.page._downloadStates[appId] = "下载中 0%"
        self.page._downloadProgress[appId] = 0
        self.page.currentApp = app

        self.page._setCardState(card, app)
        self.page._updateDetailAction()

        self.assertTrue(card.actionButton._indeterminate)
        self.assertTrue(self.page.detailAction._indeterminate)

        self.page._onDownloadProgress(appId, 1, 100)
        self.page._setCardState(card, app)
        self.page._downloadJobs.pop(appId)

        self.assertFalse(card.actionButton._indeterminate)
        self.assertEqual(card.actionButton._progress, 1)
        self.assertFalse(self.page.detailAction._indeterminate)
        self.assertEqual(self.page.detailAction._progress, 1)

    def testRerenderReusesVisibleCardsWithoutABlankFrame(self):
        first = _apps(1)
        second = _apps(1)
        second[0]["id"] = 9
        second[0]["name"] = "Updated"
        self.page._renderGrid(self.page.allGrid, first)
        card = self.page.allGrid.itemAtPosition(0, 0).widget()

        self.page._renderGrid(self.page.allGrid, second)

        self.assertIs(self.page.allGrid.itemAtPosition(0, 0).widget(), card)
        self.assertFalse(card.isHidden())
        self.assertEqual(card.appId, 9)
        self.assertEqual(card.titleLabel.text(), "Updated")

    def testRemovedApplicationCardsLeaveTheWidgetTreeImmediately(self):
        self.page._renderGrid(self.page.allGrid, _apps(2))
        removed = self.page.allGrid.itemAt(1).widget()

        self.page._renderGrid(self.page.allGrid, _apps(1))

        self.assertIsNone(removed.parent())
        self.assertNotIn(removed, self.page.container.findChildren(ApplicationCard))

    def testUnchangedGridWidthDoesNotMoveExistingCardsAgain(self):
        self.page._renderGrid(self.page.allGrid, _apps(3))

        with patch.object(self.page.allGrid, "takeAt") as takeAt:
            self.page._reflowGrid(self.page.allGrid)

        takeAt.assert_not_called()

    def testAdvertisementGlobalFilterOnlyRunsWhilePageIsVisible(self):
        self.assertFalse(self.page._globalAdFilterInstalled)

        self.page.show()
        self.assertTrue(self.page._globalAdFilterInstalled)

        self.page.hide()
        self.assertFalse(self.page._globalAdFilterInstalled)

    def testShutdownStopsAllPendingLayoutTimersAndGlobalFilter(self):
        self.page.show()
        self.page._layoutTimer.start()
        self.page._adSyncTimer.start()

        self.page.shutdown()

        self.assertFalse(self.page._globalAdFilterInstalled)
        self.assertFalse(self.page._layoutTimer.isActive())
        self.assertFalse(self.page._adSyncTimer.isActive())

    def testResponsiveGridUsesThreeColumnsAtDesktopWidth(self):
        apps = _apps(3)
        self.page.resize(1000, 600)
        self.page.show()
        self.qtApp.processEvents()
        self.page._renderGrid(self.page.allGrid, apps)

        self.assertIsInstance(self.page.allGrid.itemAtPosition(0, 2).widget(), ApplicationCard)

    def testCatalogGridsUseFinalColumnCountBeforeFirstPaint(self):
        apps = _apps(3)
        self.page.resize(600, 600)
        self.page._renderGrid(self.page.installedGrid, apps, True)
        self.page._renderGrid(self.page.allGrid, apps)

        self.page.resize(1000, 600)
        self.page.show()

        for layout in (self.page.installedGrid, self.page.allGrid):
            with self.subTest(layout=layout):
                item = layout.itemAtPosition(0, 2)
                self.assertIsNotNone(item)
                self.assertIsInstance(item.widget(), ApplicationCard)

    def testLongDescriptionDoesNotExpandItsGridColumn(self):
        apps = _apps(2)
        apps[1]["description"] = "Ghost Downloader " * 80
        self.page.resize(1400, 700)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.qtApp.processEvents()

        self.page._renderGrid(self.page.allGrid, apps)
        self.qtApp.processEvents()

        widths = [
            self.page.allGrid.itemAtPosition(0, column).widget().width()
            for column in range(2)
        ]
        self.assertLessEqual(max(widths) - min(widths), 2)
        expectedWidth = (self.page.allGridWidget.width() - 24) // 3
        self.assertLessEqual(max(widths), expectedWidth + 6)

    def testDescriptionUsesTwoLinesWithoutRedundantToolTip(self):
        card = ApplicationCard()
        lineHeight = card.descriptionLabel.fontMetrics().lineSpacing()
        card.resize(320, card.height())
        card.setApplication(
            {
                "id": 1,
                "name": "Ghost Downloader",
                "description": "Ghost Downloader " * 30,
            }
        )
        self.qtApp.processEvents()

        self.assertTrue(card.descriptionLabel.wordWrap())
        self.assertGreaterEqual(card.descriptionLabel.minimumHeight(), lineHeight * 2)
        self.assertEqual(card.descriptionLabel.toolTip(), "")
        self.assertEqual(card.titleLabel.toolTip(), "")
        lines = card._descriptionElideFilter.displayLines(card.descriptionLabel)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("…"))
        card.deleteLater()

    def testResponsiveGridUsesTwoAndOneColumnsOnNarrowTouchLayouts(self):
        self.page.resize(700, 600)
        self.page.show()
        self.qtApp.processEvents()
        self.assertEqual(self.page._columnCount(), 2)
        self.page.resize(600, 600)
        self.qtApp.processEvents()
        self.assertEqual(self.page._columnCount(), 1)

    def testHiddenAllPageUsesVisibleContentWidth(self):
        self.page.resize(1000, 800)
        self.page.show()
        self.qtApp.processEvents()

        self.page._renderGrid(self.page.allGrid, _apps(3))

        self.assertIsInstance(
            self.page.allGrid.itemAtPosition(0, 2).widget(),
            ApplicationCard,
        )

    def testCatalogTabsDoNotShareTheDetailAnimationStack(self):
        self.assertEqual(self.page.stack.count(), 2)

    def testNoAdCategoryPivotKeepsItsCompactHeight(self):
        self.page.resize(1000, 800)
        self.page.show()
        self.page._prepareAds()
        self.page._switchCatalogTab(1)
        self.qtApp.processEvents()

        self.assertLessEqual(
            self.page.categoryPivot.height(),
            self.page.categoryPivot.sizeHint().height() + 2,
        )

    def testInstalledContentStartsDirectlyBelowCompactTabs(self):
        apps = _apps(1)
        apps[0]["installed"] = True
        self.page.catalog = apps
        self.page.resize(1000, 800)
        self.page.show()
        self.page._renderInstalled()
        self.qtApp.processEvents()
        card = self.page.installedGrid.itemAtPosition(0, 0).widget()
        titleBottom = self.page.installedTitle.mapTo(
            self.page.container,
            QPoint(0, self.page.installedTitle.height()),
        ).y()
        cardTop = card.mapTo(self.page.container, QPoint()).y()
        margins = self.page.rootLayout.contentsMargins()

        self.assertLessEqual(margins.left(), 16)
        self.assertLessEqual(margins.top(), 12)
        self.assertLessEqual(cardTop - titleBottom, 24)

    def testCatalogAndDetailUseHorizontalSnapshotTransitions(self):
        self.assertIsInstance(
            self.page.catalogStack,
            HorizontalTransitionStackedWidget,
        )
        self.assertIsInstance(
            self.page.stack,
            HorizontalTransitionStackedWidget,
        )

        self.page.resize(900, 600)
        self.page.show()
        animationFinished = QSignalSpy(self.page.stack.aniFinished)
        self.page._showDetail(_apps(1)[0])
        self.assertTrue(animationFinished.wait(1000))

        self.assertTrue(self.page.stack._currentSnapshot.pixmap().isNull())
        self.assertTrue(self.page.stack._nextSnapshot.pixmap().isNull())

    def testRapidCatalogTabReversalEndsOnLatestTab(self):
        self.page.resize(900, 600)
        self.page.show()

        self.page.pivot.setCurrentItem("all")
        self.page._switchCatalogTab(1)
        self.page.pivot.setCurrentItem("installed")
        self.page._switchCatalogTab(0)

        deadline = time.monotonic() + 1
        while (
            self.page.catalogStack.currentWidget() is not self.page.overview
            and time.monotonic() < deadline
        ):
            QTest.qWait(10)
        self.assertIs(self.page.catalogStack.currentWidget(), self.page.overview)

    def testRepeatedDetailNavigationReleasesTransientPresetWidgets(self):
        app = _apps(1)[0] | {
            "installed": True,
            "presets": [
                {
                    "id": index,
                    "title": f"Preset {index}",
                    "description": "Description",
                    "action": {"type": "program", "target": "app.exe"},
                }
                for index in range(8)
            ],
        }
        self.page.stack.setAnimationEnabled(False)
        self.page.show()

        def cycle():
            self.page._showDetail(app)
            self.page._backToOverview()
            QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.qtApp.processEvents()

        cycle()
        baseline = len(self.page.findChildren(QWidget))
        for _ in range(20):
            cycle()

        self.assertLessEqual(len(self.page.findChildren(QWidget)), baseline + 2)

    def testDetailContentIsReadyBeforeThePageSwitch(self):
        app = _apps(1)[0]
        app["name"] = "Fresh application"
        observed = []

        with patch.object(
            self.page.stack,
            "setCurrentWidget",
            side_effect=lambda _widget, **_kwargs: observed.append(
                self.page.detailName.text()
            ),
        ):
            self.page._showDetail(app)

        self.assertEqual(observed, ["Fresh application"])

    def testDetailColumnsScrollIndependentlyAndUseOnePresetGroup(self):
        app = _apps(1)[0] | {
            "installed": True,
            "description": "很长的软件简介。" * 120,
            "presets": [
                {
                    "id": index,
                    "title": f"预设 {index}",
                    "description": "固定到主页后执行这个动作",
                    "action": {"type": "program", "target": "app.exe"},
                }
                for index in range(12)
            ],
        }
        self.page.resize(900, 420)
        self.page.show()
        self.page._showDetail(app)
        QTest.qWait(220)

        self.assertIsInstance(self.page.detailLeftScroll, ScrollArea)
        self.assertIsInstance(self.page.presetScroll, ScrollArea)
        self.assertIsNot(
            self.page.detailLeftScroll.verticalScrollBar(),
            self.page.presetScroll.verticalScrollBar(),
        )
        for scrollArea in (self.page.detailLeftScroll, self.page.presetScroll):
            self.assertGreater(
                QScroller.grabbedGesture(scrollArea.viewport()).value,
                0,
            )
            self.assertGreater(scrollArea.verticalScrollBar().maximum(), 0)
        outerScroll = self.page.verticalScrollBar()
        leftScroll = self.page.detailLeftScroll.verticalScrollBar()
        rightScroll = self.page.presetScroll.verticalScrollBar()
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        touchTarget = self.page.presetCards.itemAt(0).widget()
        start = touchTarget.rect().center()
        end = start + QPoint(0, -80)

        QTest.touchEvent(touchTarget, device).press(
            0, start, touchTarget
        ).commit()
        self.qtApp.processEvents()
        QTest.touchEvent(touchTarget, device).move(
            0, end, touchTarget
        ).commit()
        QTest.qWait(100)
        QTest.touchEvent(touchTarget, device).release(
            0, end, touchTarget
        ).commit()
        QTest.qWait(200)

        self.assertGreater(rightScroll.value(), 0)
        self.assertEqual(leftScroll.value(), 0)
        self.assertEqual(outerScroll.value(), 0)
        self.assertIsInstance(self.page.presetGroup, CardWidget)
        self.assertFalse(
            any(
                label.text() == "可用卡片"
                for label in self.page.presetGroup.findChildren(QLabel)
            )
        )
        self.assertEqual(
            len(self.page.presetGroup.findChildren(ToggleToolButton)),
            len(app["presets"]),
        )
        self.assertIs(self.page.presetTitle.parentWidget(), self.page.presetGroup)
        self.assertIs(
            self.page.presetHeaderDivider.parentWidget(), self.page.presetGroup
        )
        for index in range(self.page.presetCards.count()):
            self.assertIsInstance(
                self.page.presetCards.itemAt(index).widget(), CardWidget
            )

        self.page._backToOverview()

    def testAdvertisementCopyAndDetailBackButtonUseCompactGeometry(self):
        margins = self.page.adOverlay.layout().contentsMargins()

        self.assertEqual(margins.left(), 20)
        self.assertEqual(margins.right(), 20)
        self.assertLess(self.page.detailBackButton.height(), 36)
        self.assertLess(
            self.page.detailBackButton.minimumHeight(),
            self.page.detailBackButton.maximumHeight(),
        )

    def testDetailPresetCanBeOpenedWithInstalledAction(self):
        catalogAction = {"type": "program", "target": "new.exe"}
        installedAction = {"type": "program", "target": "current.exe"}
        app = _apps(1)[0] | {
            "id": 7,
            "installed": True,
            "presets": [
                {
                    "id": 11,
                    "title": "静默启动",
                    "description": "使用本机版本的预设",
                    "action": catalogAction,
                }
            ],
            "installed_presets": [
                {
                    "id": 11,
                    "title": "静默启动",
                    "action": installedAction,
                }
            ],
        }
        installed = SimpleNamespace(
            metadata={"presets": app["installed_presets"]}
        )
        self.page.store.installed = Mock(return_value={7: installed})
        self.page.store.executeAction = Mock()

        self.page._renderPresets(app)
        openButton = next(
            button
            for button in self.page.presetGroup.findChildren(PushButton)
            if button.text() == "打开"
        )

        self.assertLess(openButton.height(), 40)
        self.assertLess(openButton.minimumHeight(), openButton.maximumHeight())
        self.assertTrue(openButton.isEnabled())
        openButton.click()
        self.page.store.executeAction.assert_called_once_with(
            installed, installedAction
        )

    def testDetailPresetOpenIsDisabledUntilInstalledPresetExists(self):
        app = _apps(1)[0] | {
            "id": 7,
            "installed": True,
            "presets": [
                {
                    "id": 11,
                    "title": "新版预设",
                    "description": "需要更新后使用",
                    "action": {"type": "program", "target": "new.exe"},
                }
            ],
            "installed_presets": [],
        }

        self.page._renderPresets(app)
        openButton = next(
            button
            for button in self.page.presetGroup.findChildren(PushButton)
            if button.text() == "打开"
        )

        self.assertFalse(openButton.isEnabled())

    def testCatalogUriPresetCanOpenBeforeInstalledManifestRefresh(self):
        action = {"type": "uri", "target": "classisland://app/class-swap"}
        app = _apps(1)[0] | {
            "id": 7,
            "installed": True,
            "presets": [
                {
                    "id": 11,
                    "title": "换课",
                    "description": "打开换课界面",
                    "action": action,
                }
            ],
            "installed_presets": [],
        }
        installed = SimpleNamespace(metadata={"presets": []})
        self.page.store.installed = Mock(return_value={7: installed})
        self.page.store.executeAction = Mock()

        self.page._renderPresets(app)
        openButton = next(
            button
            for button in self.page.presetGroup.findChildren(PushButton)
            if button.text() == "打开"
        )

        self.assertTrue(openButton.isEnabled())
        openButton.click()
        self.page.store.executeAction.assert_called_once_with(installed, action)

    def testCatalogPresetRejectsUnapprovedUriScheme(self):
        app = _apps(1)[0] | {
            "id": 7,
            "installed": True,
            "presets": [
                {
                    "id": 11,
                    "title": "未知协议",
                    "description": "不应从实时目录直接执行",
                    "action": {
                        "type": "uri",
                        "target": "arbitrary-handler://payload",
                    },
                }
            ],
            "installed_presets": [],
        }

        self.page._renderPresets(app)
        openButton = next(
            button
            for button in self.page.presetGroup.findChildren(PushButton)
            if button.text() == "打开"
        )

        self.assertFalse(openButton.isEnabled())

    def testDetailHidesCatalogRefreshButton(self):
        self.page.show()
        self.page._showDetail(_apps(1)[0])
        self.qtApp.processEvents()

        self.assertTrue(self.page.refreshButton.isHidden())
        self.assertTrue(self.page.checkUpdatesButton.isHidden())

        self.page._backToOverview()
        self.qtApp.processEvents()
        self.assertFalse(self.page.refreshButton.isHidden())

    def testDownloadCountIsShownOnlyOnAllApplicationCards(self):
        app = _apps(1)[0] | {"download_count": 1234}

        self.page._renderGrid(self.page.allGrid, [app])
        allCard = self.page.allGrid.itemAtPosition(0, 0).widget()
        self.assertEqual(allCard.downloadCountLabel.text(), "已下载 1,234 次")
        self.assertFalse(allCard.downloadCountLabel.isHidden())

        self.page._renderGrid(self.page.installedGrid, [app], True)
        installedCard = self.page.installedGrid.itemAtPosition(0, 0).widget()
        self.assertTrue(installedCard.downloadCountLabel.isHidden())

    def testInvalidDownloadCountFallsBackToZero(self):
        card = ApplicationCard()
        self.addCleanup(card.deleteLater)

        card.setApplication(_apps(1)[0] | {"download_count": "unknown"})

        self.assertEqual(card.downloadCountLabel.text(), "已下载 0 次")

    def testCardDragDoesNotOpenDetail(self):
        card = ApplicationCard()
        card.resize(320, 156)
        card.show()
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))
        start = card.rect().center()
        end = start + QPoint(QApplication.startDragDistance() + 1, 0)

        QTest.mousePress(card, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(card, end)
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, pos=end)

        self.assertEqual(clicks, [])
        card.deleteLater()

    def testTouchScrollStartingOnCardDoesNotOpenDetail(self):
        apps = _apps(12)
        for app in apps:
            app["recommended"] = True
        self.page.catalog = apps
        self.page.resize(500, 300)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._renderAll()
        QTest.qWait(20)
        self.page._showDetail(apps[0])
        self.page._backToOverview()
        QTest.qWait(20)
        scrollBar = self.page.verticalScrollBar()
        self.assertGreater(scrollBar.maximum(), 0)
        card = self.page.allGrid.itemAtPosition(0, 0).widget()
        clicks = []
        card.clicked.connect(lambda: clicks.append(True))
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = card.rect().center()
        end = start + QPoint(0, -80)

        QTest.touchEvent(card, device).press(0, start, card).commit()
        self.qtApp.processEvents()
        QTest.touchEvent(card, device).move(0, end, card).commit()
        QTest.qWait(100)
        QTest.touchEvent(card, device).release(0, end, card).commit()
        QTest.qWait(200)

        self.assertGreater(scrollBar.value(), 0)
        self.assertEqual(clicks, [])

    def testCardButtonsKeepTouchFriendlyTargets(self):
        card = ApplicationCard()

        self.assertLess(card.actionButton.height(), 40)
        self.assertGreaterEqual(card.removeButton.height(), 40)
        self.assertGreaterEqual(card.removeButton.width(), 40)
        self.assertLess(card.pinButton.sizeHint().width(), 40)
        self.assertLess(card.pinButton.sizeHint().height(), 40)
        self.assertLess(card.pinButton.minimumHeight(), card.pinButton.maximumHeight())
        for button in (self.page.adPrevious, self.page.adNext):
            self.assertLess(button.sizeHint().height(), 40)
        card.deleteLater()

    def testInstalledApplicationCanBePinnedDirectlyFromItsCard(self):
        app = _apps(1)[0] | {
            "id": 1,
            "name": "Ghost Downloader",
            "description": "下载工具",
            "installed": True,
            "install_dir": "ghost-downloader",
            "icon_url": "https://example.test/icon.png",
            "open_action": {"type": "program", "target": "ghost.exe"},
        }
        item = cfg.pinnedHomeCards
        oldValue = item.value

        def setConfig(configItem, value):
            setattr(configItem, "_ConfigItem__value", value)

        setattr(item, "_ConfigItem__value", [])
        try:
            with patch.object(cfg, "set", side_effect=setConfig):
                self.page._renderGrid(self.page.installedGrid, [app], True)
                card = self.page.installedGrid.itemAtPosition(0, 0).widget()

                self.assertFalse(card.pinButton.isHidden())
                self.assertTrue(card.pinButton.isEnabled())
                card.pinButton.click()

                pinned = cfg.pinnedHomeCards.value
                self.assertEqual(len(pinned), 1)
                self.assertEqual(pinned[0]["preset_id"], 0)
                self.assertEqual(pinned[0]["title"], app["name"])
                self.assertEqual(pinned[0]["description"], app["description"])
                self.assertEqual(pinned[0]["action"], app["open_action"])
                self.assertTrue(card.pinButton.isChecked())

                setattr(item, "_ConfigItem__value", [])
                item.valueChanged.emit([])
                self.assertFalse(card.pinButton.isChecked())

                card.pinButton.click()
                self.assertEqual(len(cfg.pinnedHomeCards.value), 1)
                card.pinButton.click()
                self.assertEqual(cfg.pinnedHomeCards.value, [])
        finally:
            setattr(item, "_ConfigItem__value", oldValue)

    def testBackgroundLaunchFailureIsShownOnTheVisibleWindow(self):
        with patch.object(InfoBar, "error") as showError:
            self.page._launchFailed.emit("程序启动后立即退出")

        showError.assert_called_once()
        self.assertIs(showError.call_args.kwargs["parent"], self.page.window())

    def testInstalledApplicationWithoutOpenActionCannotBePinned(self):
        app = _apps(1)[0] | {
            "id": 1,
            "installed": True,
            "open_action": {"type": "program", "target": "catalog.exe"},
            "installed_open_action": None,
        }

        self.page._renderGrid(self.page.installedGrid, [app], True)
        card = self.page.installedGrid.itemAtPosition(0, 0).widget()

        self.assertFalse(card.pinButton.isHidden())
        self.assertFalse(card.pinButton.isEnabled())
        self.assertEqual(card.actionButton.text(), "未配置打开动作")
        self.assertFalse(card.actionButton.isEnabled())
        self.assertTrue(card.removeButton.isEnabled())

        self.page.currentApp = app
        self.page._updateDetailAction()
        self.assertEqual(self.page.detailAction.text(), "未配置打开动作")
        self.assertFalse(self.page.detailAction.isEnabled())

    def testDetailDownloadUsesValidatedArchitectureFlag(self):
        app = _apps(1)[0] | {
            "id": 1,
            "installed": False,
            "architecture_supported": False,
            "packages": {self.page.store.architecture: {"enabled": True}},
        }

        self.page.currentApp = app
        self.page._updateDetailAction()

        self.assertEqual(self.page.detailAction.text(), "不支持")
        self.assertFalse(self.page.detailAction.isEnabled())

    def testInstalledActionUsesLocalManifestInsteadOfNewCatalogAction(self):
        installed = object()
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        app = _apps(1)[0] | {
            "id": 1,
            "installed": True,
            "open_action": {"type": "program", "target": "new.exe"},
        }

        self.page._onAppAction(app)
        self._waitForLaunch()

        self.page.store.executeAction.assert_called_once_with(installed)

    def testApplicationLaunchRunsOutsideGuiThreadAndRestoresButtons(self):
        app = _apps(1)[0] | {
            "installed": True,
            "open_action": {"type": "program", "target": "demo.exe"},
        }
        installed = object()
        started = threading.Event()
        release = threading.Event()
        self.page.store.installed = Mock(return_value={0: installed})

        def execute(value):
            self.assertIs(value, installed)
            started.set()
            release.wait(1)

        self.page.store.executeAction = Mock(side_effect=execute)
        self.page._renderGrid(self.page.installedGrid, [app], True)
        self.page._renderGrid(self.page.allGrid, [app])
        self.page.currentApp = app
        self.page._updateDetailAction()
        installedCard = self.page.installedGrid.itemAtPosition(0, 0).widget()
        allCard = self.page.allGrid.itemAtPosition(0, 0).widget()
        guiCallback = []

        try:
            QTimer.singleShot(0, lambda: guiCallback.append(True))
            before = time.monotonic()
            self.page._onAppAction(app)

            self.assertLess(time.monotonic() - before, 0.2)
            self.assertTrue(started.wait(1))
            QTest.qWait(20)
            self.assertEqual(guiCallback, [True])
            for button in (
                installedCard.actionButton,
                allCard.actionButton,
                self.page.detailAction,
            ):
                self.assertEqual(button.text(), "打开中")
                self.assertFalse(button.isEnabled())
                self.assertTrue(button._indeterminate)
                self.assertTrue(button._progressTimer.isActive())
            self.assertFalse(installedCard.removeButton.isEnabled())

            self.page._onAppAction(app)
            self.page.store.executeAction.assert_called_once_with(installed)

            release.set()
            self._waitForLaunch()

            for button in (
                installedCard.actionButton,
                allCard.actionButton,
                self.page.detailAction,
            ):
                self.assertEqual(button.text(), "打开")
                self.assertTrue(button.isEnabled())
                self.assertFalse(button._indeterminate)
                self.assertFalse(button._progressTimer.isActive())
            self.assertTrue(installedCard.removeButton.isEnabled())
            self.assertNotIn(app["id"], self.page._downloadStates)
        finally:
            release.set()

    def testApplicationLaunchFailureRestoresButtons(self):
        app = _apps(1)[0] | {
            "installed": True,
            "open_action": {"type": "program", "target": "demo.exe"},
        }
        self.page.store.installed = Mock(return_value={0: object()})
        self.page.store.executeAction = Mock(side_effect=OSError("启动失败"))
        self.page._renderGrid(self.page.installedGrid, [app], True)
        self.page.currentApp = app
        card = self.page.installedGrid.itemAtPosition(0, 0).widget()

        with patch.object(InfoBar, "error") as showError:
            self.page._onAppAction(app)
            self._waitForLaunch()

        showError.assert_called_once()
        self.assertEqual(card.actionButton.text(), "打开")
        self.assertTrue(card.actionButton.isEnabled())
        self.assertFalse(card.actionButton._indeterminate)
        self.assertEqual(self.page.detailAction.text(), "打开")
        self.assertTrue(self.page.detailAction.isEnabled())
        self.assertFalse(self.page.detailAction._indeterminate)
        self.assertNotIn(app["id"], self.page._downloadStates)

    def testApplicationLaunchThreadFailureRestoresButtons(self):
        app = _apps(1)[0] | {
            "installed": True,
            "open_action": {"type": "program", "target": "demo.exe"},
        }
        self.page.store.installed = Mock()
        self.page._renderGrid(self.page.installedGrid, [app], True)
        self.page.currentApp = app
        card = self.page.installedGrid.itemAtPosition(0, 0).widget()

        with patch(
            "app.view.pages.app_store_page.threading.Thread",
            side_effect=RuntimeError("thread construction failed"),
        ), patch.object(InfoBar, "error") as showError:
            self.page._onAppAction(app)

        showError.assert_called_once()
        self.page.store.installed.assert_not_called()
        self.assertFalse(self.page._launching)
        self.assertFalse(self.page._fileOperationThreads)
        self.assertNotIn(app["id"], self.page._downloadStates)
        self.assertEqual(card.actionButton.text(), "打开")
        self.assertTrue(card.actionButton.isEnabled())
        self.assertFalse(card.actionButton._indeterminate)
        self.assertTrue(self.page.detailAction.isEnabled())
        self.assertFalse(self.page.detailAction._indeterminate)

    def testApplicationLaunchThreadStartFailureRestoresButtons(self):
        app = _apps(1)[0] | {
            "installed": True,
            "open_action": {"type": "program", "target": "demo.exe"},
        }
        thread = Mock()
        thread.start.side_effect = RuntimeError("thread start failed")

        with patch(
            "app.view.pages.app_store_page.threading.Thread",
            return_value=thread,
        ), patch.object(InfoBar, "error") as showError:
            self.page._onAppAction(app)

        showError.assert_called_once()
        self.assertFalse(self.page._launching)
        self.assertFalse(self.page._fileOperationThreads)
        self.assertNotIn(app["id"], self.page._downloadStates)

    def testUpdateButtonRulesFollowInstalledAllAndDetailContexts(self):
        installed = object()
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        app = _apps(1)[0] | {
            "id": 1,
            "installed": True,
            "update_available": True,
            "open_action": {"type": "program", "target": "demo.exe"},
            "installed_open_action": {"type": "program", "target": "demo.exe"},
        }

        self.page._renderGrid(self.page.installedGrid, [app], True)
        installedCard = self.page.installedGrid.itemAtPosition(0, 0).widget()
        self.assertEqual(installedCard.actionButton.text(), "更新")

        self.page._renderGrid(self.page.allGrid, [app])
        allCard = self.page.allGrid.itemAtPosition(0, 0).widget()
        self.assertEqual(allCard.actionButton.text(), "打开")
        self.page._onAppAction(app, allowUpdate=False)
        self._waitForLaunch()
        self.page.store.executeAction.assert_called_once_with(installed)

        self.page.currentApp = app
        self.page._updateDetailAction()
        self.assertEqual(self.page.detailAction.text(), "更新")

    def testInstallAndUninstallUseIndeterminateProgress(self):
        app = _apps(1)[0]
        card = ApplicationCard()
        self.addCleanup(card.deleteLater)

        self.page._installing.add(app["id"])
        self.page._setCardState(card, app)
        self.assertTrue(card.actionButton._indeterminate)
        self.assertTrue(card.actionButton._progressTimer.isActive())

        self.page._installing.clear()
        self.page._uninstalling.add(app["id"])
        self.page.currentApp = app
        self.page._updateDetailAction()
        self.assertTrue(self.page.detailAction._indeterminate)

    def testDirectPinnedCardUsesLocalManifestAction(self):
        installed = object()
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}

        self.page.executePinnedCard(
            {
                "app_id": 1,
                "preset_id": 0,
                "title": "Ghost Downloader",
                "description": "下载工具",
                "action": {"type": "program", "target": "new.exe"},
            }
        )

        self.page.store.executeAction.assert_called_once_with(installed)

    def testPinnedCardPropagatesActionFailure(self):
        installed = object()
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        self.page.store.executeAction.return_value = False

        self.assertFalse(
            self.page.executePinnedCard(
                {
                    "app_id": 1,
                    "preset_id": 0,
                    "title": "Ghost Downloader",
                    "description": "下载工具",
                    "action": {"type": "url", "target": "https://example.test"},
                }
            )
        )

    def testPresetPinnedCardUsesMatchingInstalledPresetAction(self):
        installed = SimpleNamespace(
            metadata={
                "presets": [
                    {
                        "id": 7,
                        "action": {
                            "type": "program",
                            "target": "new.exe",
                        },
                    }
                ]
            }
        )
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        self.page.catalog = [
            {
                "id": 1,
                "presets": [
                    {
                        "id": 7,
                        "action": {
                            "type": "program",
                            "target": "catalog.exe",
                        },
                    }
                ],
            }
        ]

        self.page.executePinnedCard(
            {
                "app_id": 1,
                "preset_id": 7,
                "title": "打开设置",
                "description": "",
                "action": {"type": "program", "target": "old.exe"},
            }
        )

        self.page.store.executeAction.assert_called_once_with(
            installed,
            {"type": "program", "target": "new.exe"},
        )

    def testColdStartPinnedCatalogUriUsesStoredSafeAction(self):
        action = {"type": "uri", "target": "classisland://app/class-swap"}
        installed = SimpleNamespace(metadata={"presets": []})
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        self.page._catalogLoaded = False

        self.page.executePinnedCard(
            {
                "app_id": 1,
                "preset_id": 7,
                "title": "换课",
                "description": "",
                "action": action,
            }
        )

        self.page.store.executeAction.assert_called_once_with(installed, action)

    def testPinnedCatalogUriPresetSurvivesInstalledManifestLag(self):
        currentAction = {
            "type": "uri",
            "target": "classisland://app/class-swap",
        }
        installed = SimpleNamespace(metadata={"presets": []})
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        self.page.catalog = [
            {
                "id": 1,
                "presets": [{"id": 7, "action": currentAction}],
            }
        ]

        self.page.executePinnedCard(
            {
                "app_id": 1,
                "preset_id": 7,
                "title": "换课",
                "description": "",
                "action": {
                    "type": "uri",
                    "target": "classisland://app/old-target",
                },
            }
        )

        self.page.store.executeAction.assert_called_once_with(
            installed, currentAction
        )

    def testWithdrawnCatalogPresetDoesNotUseStoredExternalAction(self):
        installed = SimpleNamespace(
            metadata={
                "presets": [
                    {
                        "id": 7,
                        "action": {
                            "type": "uri",
                            "target": "classisland://app/withdrawn",
                        },
                    }
                ]
            }
        )
        self.page.store = Mock()
        self.page.store.installed.return_value = {1: installed}
        self.page.catalog = [{"id": 1, "presets": "malformed"}]

        with patch.object(InfoBar, "warning"):
            self.page.executePinnedCard(
                {
                    "app_id": 1,
                    "preset_id": 7,
                    "title": "已撤回预设",
                    "description": "",
                    "action": {
                        "type": "uri",
                        "target": "classisland://app/withdrawn",
                    },
                }
            )

        self.page.store.executeAction.assert_not_called()

    def testCatalogRefreshKeepsPinnedActionAndCachedIconUntilReplacementLoads(self):
        item = cfg.pinnedHomeCards
        oldValue = item.value
        originalAction = {"type": "program", "target": "old.exe"}
        pinned = {
            "app_id": 1,
            "preset_id": 0,
            "title": "Old name",
            "description": "Old description",
            "action": originalAction,
            "icon_url": "https://example.test/old.png",
            "icon_path": "old-cache.png",
        }

        def setConfig(configItem, value):
            setattr(configItem, "_ConfigItem__value", value)

        setattr(item, "_ConfigItem__value", [pinned])
        self.page.catalog = [
            _apps(1)[0]
            | {
                "id": 1,
                "name": "New name",
                "description": "New description",
                "install_dir": "ghost-downloader",
                "icon_url": "https://example.test/new.png",
                "open_action": {"type": "program", "target": "new.exe"},
            }
        ]
        self.page._mergedCatalog = None
        try:
            with patch.object(cfg, "set", side_effect=setConfig):
                self.page._syncPinnedMetadata()

            updated = cfg.pinnedHomeCards.value[0]
            self.assertEqual(updated["title"], "New name")
            self.assertEqual(updated["description"], "New description")
            self.assertEqual(updated["action"], originalAction)
            self.assertEqual(updated["icon_path"], "old-cache.png")
            self.assertEqual(updated["icon_url"], "https://example.test/new.png")
        finally:
            setattr(item, "_ConfigItem__value", oldValue)

    def testAdsOnlyAdvanceOnVisibleAllAppsPage(self):
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page.show()
        self.page._prepareAds()
        self.assertFalse(self.page.adTimer.isActive())

        self.page._switchCatalogTab(1)
        QTest.qWait(220)
        self.assertTrue(self.page.adTimer.isActive())

        self.page._showDetail(_apps(1)[0])
        self.assertFalse(self.page.adTimer.isActive())

    def testAdvertisementOverlayIsVisibleAndSupportsTouchSwipe(self):
        self.page.ads = [
            {"id": 1, "title": "First", "image_url": ""},
            {"id": 2, "title": "Second", "image_url": ""},
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(500)

        self.assertTrue(self.page.adOverlay.isVisible())
        start = QPoint(self.page.adOverlay.width() - 100, 90)
        end = QPoint(100, 90)
        pageStart = self.page.adOverlay.mapTo(self.page, start)
        pageEnd = self.page.adOverlay.mapTo(self.page, end)
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        QTest.touchEvent(self.page, device).press(
            0, pageStart, self.page
        ).commit()
        self.qtApp.processEvents()
        QTest.touchEvent(self.page, device).move(
            0, pageEnd, self.page
        ).commit()
        self.qtApp.processEvents()
        QTest.touchEvent(self.page, device).release(
            0, pageEnd, self.page
        ).commit()
        self.qtApp.processEvents()

        self.assertEqual(self.page.adFlipView.currentIndex(), 1)

    def testAdvertisementTouchJitterDoesNotLockTheSwipeAxis(self):
        self.page.ads = [
            {"id": 1, "title": "First", "image_url": ""},
            {"id": 2, "title": "Second", "image_url": ""},
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        start = QPoint(self.page.adOverlay.width() // 2, 30)
        jitter = start + QPoint(2, 1)

        def sendTouch(eventType, position):
            point = Mock()
            point.globalPosition.return_value.toPoint.return_value = (
                self.page.adOverlay.mapToGlobal(position)
            )
            event = Mock()
            event.type.return_value = eventType
            event.points.return_value = [point]
            self.page.adOverlay.event(event)

        sendTouch(QEvent.Type.TouchBegin, start)
        sendTouch(QEvent.Type.TouchUpdate, jitter)

        self.assertIsNone(self.page.adOverlay._touchAxis)

        sendTouch(QEvent.Type.TouchCancel, jitter)

    def testAdvertisementArrowCanBeActivatedByTouch(self):
        self.page.ads = [
            {"id": 1, "title": "First", "image_url": ""},
            {"id": 2, "title": "Second", "image_url": ""},
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        globalPosition = self.page.adNext.mapToGlobal(
            self.page.adNext.rect().center()
        )
        self.assertIs(
            self.page.adOverlay._buttonAt(
                self.page.adOverlay.mapFromGlobal(globalPosition)
            ),
            self.page.adNext,
        )

        def sendTouch(eventType):
            point = Mock()
            point.globalPosition.return_value.toPoint.return_value = globalPosition
            event = Mock()
            event.type.return_value = eventType
            event.points.return_value = [point]
            self.page.adOverlay.event(event)

        sendTouch(QEvent.Type.TouchBegin)
        sendTouch(QEvent.Type.TouchEnd)

        self.assertEqual(self.page.adFlipView.currentIndex(), 1)

    def testAdvertisementUsesCenteredCropAndBoundedWidth(self):
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page.resize(1400, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(220)

        self.assertGreaterEqual(self.page.adFrame.width(), 998)
        self.assertLessEqual(self.page.adFrame.width(), 1000)
        self.assertLessEqual(
            abs(
                self.page.adFrame.geometry().center().x()
                - self.page.allPage.rect().center().x()
            ),
            2,
        )
        self.assertEqual(
            self.page.adFlipView.aspectRatioMode,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        )
        self.assertEqual(
            self.page.adFlipView.itemSize,
            self.page.adFlipView.viewport().size(),
        )

    def testAdvertisementControlsUseThemeAndBannerEdges(self):
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": "", "app_id": 1}]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        self.assertIsInstance(self.page.adButton, PrimaryPushButton)
        self.assertLess(self.page.adButton.height(), 32)
        self.assertLess(
            self.page.adButton.minimumHeight(), self.page.adButton.maximumHeight()
        )
        self.assertEqual(self.page.adTimer.interval(), 5000)
        self.assertEqual(self.page.adTitle.toolTip(), "")
        self.assertEqual(self.page.adDescription.toolTip(), "")
        self.assertIn("QWidget#AdvertisementOverlay", self.page.adOverlay.styleSheet())
        self.assertLess(
            self.page.adPrevious.geometry().center().x(),
            self.page.adOverlay.width() // 3,
        )
        self.assertGreater(
            self.page.adNext.geometry().center().x(),
            self.page.adOverlay.width() * 2 // 3,
        )

    def testAdvertisementKeepsNativeFlipViewShapeAndControls(self):
        self.page.ads = [
            {
                "id": 1,
                "title": "First",
                "description": "Description",
                "image_url": "",
                "app_id": 1,
            },
            {
                "id": 2,
                "title": "Second",
                "description": "Description",
                "image_url": "",
                "app_id": 1,
            },
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        self.assertLessEqual(self.page.adFrame.height(), 200)
        self.assertEqual(self.page.adFlipView.borderRadius, 12)
        self.assertIn("border-radius: 12px", self.page.adOverlay.styleSheet())
        self.assertIs(self.page.adPrevious, self.page.adFlipView.preButton)
        self.assertIs(self.page.adNext, self.page.adFlipView.nextButton)
        for button in (self.page.adPrevious, self.page.adNext):
            self.assertLess(button.sizeHint().height(), 40)
        self.assertLessEqual(
            abs(
                self.page.adPrevious.geometry().center().y()
                - self.page.adOverlay.geometry().center().y()
            ),
            1,
        )
        self.assertGreaterEqual(
            self.page.adTitle.geometry().top(),
            self.page.adOverlay.height() // 2 - 8,
        )
        self.assertGreaterEqual(
            self.page.adDescription.geometry().top(),
            self.page.adOverlay.height() // 2,
        )
        self.assertGreaterEqual(
            self.page.adButton.geometry().top(),
            self.page.adOverlay.height() // 2,
        )
        self.assertEqual(self.page.adTitle.geometry().left(), 20)
        self.assertGreaterEqual(
            self.page.adTitle.width(),
            self.page.adOverlay.width() - 120,
        )

        self.page.adNext.click()
        self.assertEqual(self.page.adFlipView.currentIndex(), 1)
        self.page.adPrevious.click()
        self.assertEqual(self.page.adFlipView.currentIndex(), 0)

    def testInstalledEmptyStateHasIconAndBrowseAction(self):
        self.page.catalog = []
        self.page.resize(900, 600)
        self.page.show()
        self.page._renderInstalled()
        self.qtApp.processEvents()

        self.assertFalse(self.page.installedEmpty.isHidden())
        self.assertFalse(self.page.installedEmptyIcon.pixmap().isNull())
        self.assertEqual(
            self.page.installedEmptyButton.height(),
            self.page.installedEmptyButton.sizeHint().height(),
        )

        self.page.installedEmptyButton.click()
        deadline = time.monotonic() + 1
        while (
            self.page.catalogStack.currentWidget() is not self.page.allPage
            and time.monotonic() < deadline
        ):
            QTest.qWait(10)

        self.assertEqual(self.page.pivot.currentRouteKey(), "all")
        self.assertIs(self.page.catalogStack.currentWidget(), self.page.allPage)

    def testInstalledSearchEmptyStateClearsSearchInsteadOfLeavingPage(self):
        app = _apps(1)[0]
        app["installed"] = True
        self.page._mergedCatalog = [app]
        self.page.setSearchText("not-found")

        self.assertFalse(self.page.installedEmpty.isHidden())
        self.assertEqual(
            self.page.installedEmptyTitle.text(),
            "未找到匹配的已安装应用",
        )
        self.assertEqual(self.page.installedEmptyButton.text(), "清除搜索")

        self.page.installedEmptyButton.click()

        self.assertEqual(self.page.searchText, "")
        self.assertEqual(self.page.pivot.currentRouteKey(), "installed")

    def testCategoryRerenderKeepsViewportFrozenUntilLayoutSettles(self):
        apps = _apps(18)
        for app in apps:
            app["recommended"] = True
        self.page.catalog = apps
        self.page.resize(700, 420)
        self.page.show()
        self.page.pivot.setCurrentItem("all")
        self.page._switchCatalogTab(1)
        QTest.qWait(220)
        self.page.categoryPivot.setCurrentItem("all")
        self.page._renderAll()
        self.page.verticalScrollBar().setValue(80)
        before = self.page.verticalScrollBar().value()

        self.page.categoryPivot.setCurrentItem("recommended")
        self.page._switchCategory(0)

        self.assertFalse(self.page.viewport().updatesEnabled())
        QTest.qWait(30)
        self.assertTrue(self.page.viewport().updatesEnabled())
        self.assertEqual(self.page.verticalScrollBar().value(), before)

    def testViewportFreezeStopsOuterTouchScroller(self):
        scroller = QScroller.scroller(self.page.viewport())

        with patch.object(scroller, "stop") as stop:
            self.page._beginViewportUpdate()
            self.page._finishViewportUpdate()

        stop.assert_called_once_with()

    def testAdvertisementGradientDarkensTheWholeLowerArea(self):
        self.page.resize(1000, 800)
        self.page.show()
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        image = self.page.adOverlay.grab().toImage()
        upper = image.pixelColor(image.width() - 10, int(image.height() * 0.48))
        middle = image.pixelColor(image.width() - 10, int(image.height() * 0.72))
        bottom = image.pixelColor(image.width() - 10, image.height() - 10)

        self.assertTrue(
            self.page.adOverlay.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        )
        self.assertGreater(upper.alpha(), 0)
        self.assertLess(upper.alpha(), middle.alpha())
        self.assertLess(middle.alpha(), bottom.alpha())

    def testAdvertisementCopyStaysFixedAboveEverySlide(self):
        self.page.ads = [
            {"id": 1, "title": "First", "description": "one", "image_url": ""},
            {"id": 2, "title": "Second", "description": "two", "image_url": ""},
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        self.page._nextAd()
        QTest.qWait(520)

        self.assertIs(self.page.adOverlay.parentWidget(), self.page.adFlipView)
        self.assertEqual(
            self.page.adOverlay.geometry(),
            self.page.adFlipView.viewport().geometry(),
        )
        self.assertEqual(self.page.adTitle.text(), "Second")
        self.assertEqual(self.page.adDescription.text(), "two")
        self.assertTrue(self.page.adTitle.isVisible())

    def testRestoringFromWideWindowShrinksCatalogContent(self):
        apps = _apps(3)
        for app in apps:
            app["recommended"] = True
        self.page.catalog = apps
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page.resize(1400, 850)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        self.page._renderAll()
        QTest.qWait(30)

        self.page.resize(760, 700)
        QTest.qWait(80)

        self.assertLessEqual(
            self.page.container.width(),
            self.page.viewport().width() + 2,
        )
        self.assertTrue(self.page.allPage.rect().contains(self.page.adFrame.geometry()))
        self.assertLessEqual(
            abs(
                self.page.adFrame.geometry().center().x()
                - self.page.allPage.rect().center().x()
            ),
            2,
        )

    def testAdvertisementResizeKeepsCurrentSlideAligned(self):
        self.page.ads = [
            {"id": 1, "title": "First", "image_url": ""},
            {"id": 2, "title": "Second", "image_url": ""},
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)
        self.page.adFlipView.setCurrentIndex(1)
        QTest.qWait(520)

        self.page.resize(700, 800)
        QTest.qWait(20)

        expected = (
            self.page.adFlipView.item(0).sizeHint().width()
            + 3 * self.page.adFlipView.spacing()
        )
        self.assertEqual(self.page.adFlipView.scrollBar.value(), expected)

    def testAdvertisementRefreshResetsRemovedSlideIndex(self):
        self.page.ads = [
            {"id": 1, "title": "First", "image_url": ""},
            {"id": 2, "title": "Second", "image_url": ""},
            {"id": 3, "title": "Third", "image_url": ""},
        ]
        self.page._prepareAds()
        self.page.adFlipView.setCurrentIndex(2)
        self.page.ads = [{"id": 4, "title": "Only", "image_url": ""}]

        self.page._prepareAds()

        self.assertEqual(self.page.adFlipView.currentIndex(), 0)
        self.page._openAdApp()

    @patch("app.view.pages.app_store_page.QDesktopServices.openUrl")
    def testAdvertisementButtonCanOpenHttpsUrlInSystemBrowser(self, openUrl):
        self.page.ads = [
            {
                "id": 1,
                "title": "Website",
                "image_url": "",
                "button_type": "url",
                "button_url": "https://example.test/product",
            }
        ]
        self.page._prepareAds()

        self.assertFalse(self.page.adButton.isHidden())
        self.assertEqual(self.page.adButton.text(), "打开网页")
        self.page._openAdApp()

        openUrl.assert_called_once()
        self.assertEqual(
            openUrl.call_args.args[0].toString(),
            "https://example.test/product",
        )

    def testDetailStartsAtTopAndBackRestoresCatalogScroll(self):
        apps = _apps(20)
        for app in apps:
            app["recommended"] = True
        self.page.catalog = apps
        self.page.resize(700, 420)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._renderAll()
        QTest.qWait(20)
        self.page.container.setMinimumHeight(self.page.container.sizeHint().height())
        QTest.qWait(20)
        scrollBar = self.page.verticalScrollBar()
        original = min(180, scrollBar.maximum())
        self.assertGreater(original, 0)
        scrollBar.setValue(original)

        self.page._showDetail(apps[0])
        QTest.qWait(20)

        self.assertEqual(scrollBar.value(), 0)

        self.page._backToOverview()
        QTest.qWait(20)

        self.assertEqual(scrollBar.value(), original)

    def testReloadLeavesRemovedLocalOnlyApplicationDetail(self):
        app = _apps(1)[0] | {"id": 7, "installed": True}
        self.page.stack.setAnimationEnabled(False)
        self.page._showDetail(app)

        with patch.object(self.page, "_mergedApps", return_value=[]):
            self.page._reloadState()

        self.assertIsNone(self.page.currentApp)
        self.assertIs(self.page.stack.currentWidget(), self.page.catalogPage)

    def testCatalogRefreshLeavesDetailWhenApplicationWasRemoved(self):
        app = _apps(1)[0] | {"id": 7}
        self.page.stack.setAnimationEnabled(False)
        self.page._showDetail(app)

        self.page._onCatalogLoaded({"apps": [], "ads": []}, {}, "")

        self.assertIsNone(self.page.currentApp)
        self.assertIs(self.page.stack.currentWidget(), self.page.catalogPage)

    def testSearchEnteredInDetailAppliesWhenReturningToList(self):
        apps = _apps(2)
        self.page.catalog = apps
        self.page.resize(900, 600)
        self.page.show()
        self.qtApp.processEvents()
        self.page.pivot.setCurrentItem("all")
        self.page.categoryPivot.setCurrentItem("all")
        self.page._renderAll()
        self.assertIsNotNone(self.page.allGrid.itemAtPosition(0, 0))
        self.page._showDetail(apps[0])
        deadline = time.monotonic() + 1
        while (
            self.page.stack.currentWidget() is not self.page.detail
            and time.monotonic() < deadline
        ):
            QTest.qWait(20)
        self.assertIs(self.page.stack.currentWidget(), self.page.detail)

        self.page.setSearchText("no matching application")
        self.page._backToOverview()

        self.assertIsNone(self.page.allGrid.itemAtPosition(0, 0))

    def testCanceledCatalogWorkerDoesNotEmitLateResult(self):
        store = _BlockingCatalogStore()
        worker = CatalogWorker(store)
        results = []
        worker.finished.connect(lambda *result: results.append(result))
        thread = threading.Thread(target=worker.run)
        thread.start()
        self.assertTrue(store.started.wait(1))

        worker.cancel()
        store.release.set()
        thread.join(1)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results, [])

    def testCatalogIsPublishedBeforeSlowImagesFinish(self):
        store = _SlowImageStore()
        worker = CatalogImageWorker(store, ["https://example.test/icon.png"])
        images = []
        completed = threading.Event()
        worker.imageLoaded.connect(lambda *result: images.append(result))
        worker.completed.connect(completed.set)
        thread = threading.Thread(target=worker.run)
        thread.start()
        self.assertTrue(store.imageStarted.wait(1))
        QTest.qWait(20)

        self.assertEqual(images, [])

        store.releaseImage.set()
        thread.join(1)
        QTest.qWait(20)
        self.assertTrue(completed.is_set())
        self.assertEqual(images, [("https://example.test/icon.png", "cached.png")])

    def testCanceledImageWorkerDoesNotWaitForBlockedRequest(self):
        store = _SlowImageStore()
        worker = CatalogImageWorker(store, ["https://example.test/icon.png"])
        thread = threading.Thread(target=worker.run)
        thread.start()
        self.assertTrue(store.imageStarted.wait(1))

        worker.cancel()
        thread.join(1)

        try:
            self.assertFalse(thread.is_alive())
        finally:
            store.releaseImage.set()
            self.assertTrue(store.imageFinished.wait(1))

    def testRepeatedImageCancellationKeepsTheSharedPoolBounded(self):
        store = _SlowImageStore()
        outerThreads = []
        try:
            for generation in range(5):
                worker = CatalogImageWorker(
                    store,
                    [
                        f"https://example.test/{generation}-{index}.png"
                        for index in range(4)
                    ],
                )
                thread = threading.Thread(target=worker.run)
                thread.start()
                outerThreads.append(thread)
                self.assertTrue(store.imageStarted.wait(1))
                worker.cancel()
                thread.join(1)
                self.assertFalse(thread.is_alive())

            poolThreads = [
                thread
                for thread in threading.enumerate()
                if thread.name.startswith("app-store-image-")
            ]
            self.assertLessEqual(len(poolThreads), CatalogImageWorker._poolSize)
        finally:
            store.releaseImage.set()
            for thread in outerThreads:
                thread.join(1)

    def testCatalogFailureStillRendersInstalledApplications(self):
        app = _apps(1)[0] | {
            "id": 1,
            "installed": True,
            "open_action": {"type": "program", "target": "app.exe"},
        }
        self.page.store = Mock()
        self.page.store.mergeInstalled.return_value = [app]

        with patch.object(InfoBar, "error"):
            self.page._onCatalogLoaded({}, {}, "offline")

        self.assertIsNotNone(self.page.installedGrid.itemAtPosition(0, 0))

    def testCatalogNormalizesMalformedAdvertisements(self):
        for ads in (None, [None, {"id": 1, "title": "Valid"}]):
            with self.subTest(ads=ads):
                self.page._onCatalogLoaded(
                    {"apps": [], "ads": ads},
                    {},
                    "",
                )
                self.assertTrue(all(isinstance(ad, dict) for ad in self.page.ads))

    def testCatalogImageWorkerIgnoresMalformedAndDuplicateUrls(self):
        worker = CatalogImageWorker(
            self.page.store,
            [
                "https://example.test/icon.png",
                ["not", "a", "url"],
                None,
                "https://example.test/icon.png",
                "",
            ],
        )

        self.assertEqual(worker.urls, ("https://example.test/icon.png",))

    def testCatalogNormalizesMalformedImageUrlsBeforeRendering(self):
        self.page._onCatalogLoaded(
            {
                "apps": [_apps(1)[0] | {"icon_url": ["invalid"]}],
                "ads": [
                    {
                        "id": 1,
                        "title": "Ad",
                        "image_url": {"invalid": True},
                    }
                ],
            },
            {},
            "",
        )

        self.assertEqual(self.page.catalog[0]["icon_url"], "")
        self.assertEqual(self.page.ads[0]["image_url"], "")

    def testDownloadThreadConstructionFailureRollsBackStartup(self):
        app = _apps(1)[0]
        worker = Mock()
        self.page.store.downloadSlots = Mock()

        with patch(
            "app.view.pages.app_store_page.downloadWorker",
            return_value=worker,
        ), patch(
            "app.view.pages.app_store_page.threading.Thread",
            side_effect=RuntimeError("thread construction failed"),
        ), patch.object(InfoBar, "error") as showError:
            self.page._onAppAction(app)

        self.page.store.downloadSlots.acquire.assert_called_once_with()
        self.page.store.downloadSlots.release.assert_called_once_with()
        worker.deleteLater.assert_called_once_with()
        showError.assert_called_once()
        self.assertNotIn(app["id"], self.page._downloadJobs)
        self.assertNotIn(app["id"], self.page._downloadStates)

    def testInstallThreadConstructionFailureRollsBackStartup(self):
        app = _apps(1)[0]
        appId = app["id"]
        self.page.store.downloadSlots = Mock()
        self.page._downloadJobs[appId] = (Mock(), Mock())

        with TemporaryDirectory() as directory:
            package = Path(directory) / "demo.zip"
            package.write_bytes(b"package")
            with patch(
                "app.view.pages.app_store_page.threading.Thread",
                side_effect=RuntimeError("thread construction failed"),
            ), patch(
                "app.view.pages.app_store_page.endAppStorePackageOperation"
            ) as endOperation, patch.object(InfoBar, "error") as showError:
                self.page._onDownloadFinished(app, str(package), "", False)

            self.assertFalse(package.exists())

        self.page.store.downloadSlots.release.assert_called_once_with()
        endOperation.assert_called_once_with()
        showError.assert_called_once()
        self.assertNotIn(appId, self.page._downloadJobs)
        self.assertNotIn(appId, self.page._installing)
        self.assertNotIn(appId, self.page._downloadStates)

    def testShutdownWaitsForCooperativeDownloadThread(self):
        worker = _CancelableWorker()
        thread = threading.Thread(target=worker.run)
        thread.start()
        QTest.qWait(20)

        self.page.store.downloadSlots = Mock()
        self.page._downloadJobs[1] = (thread, worker)

        self.page.shutdown()

        self.assertFalse(thread.is_alive())
        self.assertNotIn(1, self.page._downloadJobs)
        self.page.store.downloadSlots.release.assert_called_once_with()

    def testShutdownDefersDownloadReleaseUntilThreadStops(self):
        app = _apps(2)[1]
        worker = _IgnoringCancelWorker()

        def run():
            worker.run()
            self.page._downloadFinishedSignal.emit(app, "", "", True)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.page.store.downloadSlots = Mock()
        self.page._downloadJobs[app["id"]] = (thread, worker)
        slotReleased = threading.Event()
        operationEnded = threading.Event()
        self.page.store.downloadSlots.release.side_effect = slotReleased.set

        try:
            with patch(
                "app.view.pages.app_store_page.SHUTDOWN_WAIT_SECONDS",
                0.01,
            ), patch(
                "app.view.pages.app_store_page.endAppStorePackageOperation",
                side_effect=operationEnded.set,
            ) as endOperation:
                self.page.shutdown()
                self.page.shutdown()

                self.assertTrue(worker.canceled.is_set())
                self.assertTrue(thread.is_alive())
                self.assertFalse(slotReleased.is_set())
                self.assertFalse(operationEnded.is_set())

                worker.release.set()
                self.assertTrue(operationEnded.wait(1))
                QTest.qWait(20)

            self.page.store.downloadSlots.release.assert_called_once_with()
            endOperation.assert_called_once_with()
        finally:
            worker.release.set()
            thread.join(1)

    def testShutdownDefersInstallReleaseUntilThreadStops(self):
        app = _apps(1)[0]
        appId = app["id"]
        installStarted = threading.Event()
        allowInstallToFinish = threading.Event()
        slotReleased = threading.Event()
        operationEnded = threading.Event()
        installThread = None
        self.page.store.downloadSlots = Mock()
        self.page.store.downloadSlots.release.side_effect = slotReleased.set
        self.page._downloadJobs[appId] = (Mock(), Mock())

        def installZip(_app, _path, _cancelEvent):
            installStarted.set()
            allowInstallToFinish.wait()
            return None

        self.page.store.installZip = installZip
        with TemporaryDirectory() as directory:
            package = Path(directory) / "demo.zip"
            package.write_bytes(b"package")
            try:
                with patch(
                    "app.view.pages.app_store_page.SHUTDOWN_WAIT_SECONDS",
                    0.01,
                ), patch(
                    "app.view.pages.app_store_page.endAppStorePackageOperation",
                    side_effect=operationEnded.set,
                ) as endOperation:
                    self.page._onDownloadFinished(
                        app,
                        str(package),
                        "",
                        False,
                    )
                    self.assertTrue(installStarted.wait(1))
                    with self.page._fileOperationLock:
                        installThread = next(
                            iter(self.page._fileOperationThreads)
                        )

                    self.page.shutdown()
                    self.page.shutdown()

                    self.assertTrue(installThread.is_alive())
                    self.assertFalse(slotReleased.is_set())
                    self.assertFalse(operationEnded.is_set())

                    allowInstallToFinish.set()
                    self.assertTrue(operationEnded.wait(1))
                    self.page._onInstallFinished(appId, None, "")

                self.page.store.downloadSlots.release.assert_called_once_with()
                endOperation.assert_called_once_with()
            finally:
                allowInstallToFinish.set()
                if installThread is not None:
                    installThread.join(1)

    def testShutdownHasBoundedWaitForUncooperativeDownload(self):
        worker = _IgnoringCancelWorker()
        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()
        self.page.store.downloadSlots = Mock()
        self.page._downloadJobs[1] = (thread, worker)

        started = time.monotonic()
        try:
            with patch(
                "app.view.pages.app_store_page.SHUTDOWN_WAIT_SECONDS",
                0.01,
            ):
                self.page.shutdown()
        finally:
            worker.release.set()
            thread.join(1)

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertTrue(worker.canceled.is_set())
        self.assertNotIn(1, self.page._downloadJobs)

    def testUninstallRunsOutsideTheGuiThreadAndReportsCompletion(self):
        app = _apps(1)[0] | {"name": "Demo", "installed": True}
        started = threading.Event()
        release = threading.Event()
        local = object()
        self.page.store.installed = Mock(return_value={0: local})

        def uninstall(value):
            self.assertIs(value, local)
            started.set()
            release.wait(1)

        self.page.store.uninstall = uninstall
        self.page.store.executeAction = Mock()
        self.page._renderGrid(self.page.installedGrid, [app], True)
        self.page.currentApp = app
        card = self.page.installedGrid.itemAtPosition(0, 0).widget()
        guiCallback = []
        try:
            with patch.object(MessageBox, "exec", return_value=1), patch.object(
                self.page, "_reloadState"
            ) as reloadState, patch.object(InfoBar, "success"):
                QTimer.singleShot(0, lambda: guiCallback.append(True))
                before = time.monotonic()
                self.page._confirmUninstall(app)

                self.assertLess(time.monotonic() - before, 0.2)
                self.assertTrue(started.wait(1))
                QTest.qWait(20)
                self.assertEqual(guiCallback, [True])
                self.assertEqual(card.actionButton.text(), "卸载中")
                self.assertFalse(card.removeButton.isEnabled())
                self.assertEqual(self.page.detailAction.text(), "卸载中")
                self.assertFalse(self.page.detailAction.isEnabled())
                self.page._onAppAction(app)
                self.page.store.executeAction.assert_not_called()

                release.set()
                deadline = time.monotonic() + 1
                while self.page._uninstalling and time.monotonic() < deadline:
                    QTest.qWait(10)

                self.assertEqual(self.page._uninstalling, set())
                reloadState.assert_called_once_with()
        finally:
            release.set()
