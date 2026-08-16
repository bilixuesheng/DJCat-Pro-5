import os
import sys
import threading
import time
from unittest import TestCase
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    DrillInTransitionStackedWidget,
    PrimaryPushButton,
    ToolTipFilter,
)

from app.view.pages.app_store_page import ApplicationCard, AppStorePage, CatalogWorker


class _Store:
    architecture = "x86_64"

    def mergeInstalled(self, apps):
        return list(apps)


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

    def fetchCatalog(self):
        return {
            "apps": [{"id": 1, "icon_url": "https://example.test/icon.png"}],
            "ads": [],
        }

    def imagePath(self, _url):
        self.imageStarted.set()
        self.releaseImage.wait()
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
        self.addCleanup(self.page.deleteLater)

    def testPagerClickDoesNotRebuildItems(self):
        apps = _apps(16)
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
        self.page._allAppsForPage = lambda: _apps(16)
        self.page._renderAll()

        self.assertGreaterEqual(self.page.pagerPrevious.width(), 40)
        self.assertGreaterEqual(self.page.pagerPrevious.height(), 40)
        self.assertGreaterEqual(self.page.pagerNext.width(), 40)
        self.assertFalse(self.page.pagerPrevious.isEnabled())
        self.assertTrue(self.page.pagerNext.isEnabled())

        self.page.pagerNext.click()

        self.assertEqual(self.page._currentPage, 1)
        self.assertFalse(self.page.pagerNext.isEnabled())

    def testRecommendedCategoryShowsEveryRecommendedAppWithoutPager(self):
        apps = _apps(16)
        for app in apps:
            app["recommended"] = True
        self.page.catalog = apps
        self.page.categoryPivot.setCurrentItem("recommended")

        self.page._renderAll()

        self.assertTrue(self.page.pager.isHidden())
        self.assertEqual(self.page.allGrid.count(), 16)

    def testProgressUpdatesExistingCardAndDisablesAction(self):
        apps = _apps(1)
        self.page._allAppsForPage = lambda: apps
        self.page._renderAll()
        card = self.page.allGrid.itemAtPosition(0, 0).widget()
        self.page._downloadJobs[0] = object()

        self.page._onDownloadProgress(0, 50, 100)

        self.assertIs(self.page.allGrid.itemAtPosition(0, 0).widget(), card)
        self.assertEqual(card.actionButton.text(), "下载中 50%")
        self.assertFalse(card.actionButton.isEnabled())
        self.assertFalse(card.removeButton.isEnabled())

    def testRerenderHidesCardsBeforeDeferredDeletion(self):
        self.page._renderGrid(self.page.allGrid, _apps(1))
        oldCard = self.page.allGrid.itemAtPosition(0, 0).widget()

        self.page._renderGrid(self.page.allGrid, _apps(1))

        self.assertTrue(oldCard.isHidden())

    def testResponsiveGridUsesThreeColumnsAtDesktopWidth(self):
        apps = _apps(3)
        self.page.resize(1000, 600)
        self.page.show()
        self.qtApp.processEvents()
        self.page._renderGrid(self.page.allGrid, apps)

        self.assertIsInstance(self.page.allGrid.itemAtPosition(0, 2).widget(), ApplicationCard)

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

    def testDescriptionUsesTwoLinesAndFluentToolTip(self):
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
        self.assertTrue(card.descriptionLabel.findChildren(ToolTipFilter))
        self.assertTrue(card.titleLabel.findChildren(ToolTipFilter))
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

    def testDetailStackUsesDrillInTransition(self):
        self.assertIsInstance(self.page.stack, DrillInTransitionStackedWidget)

    def testDetailHidesCatalogRefreshButton(self):
        self.page.show()
        self.page._showDetail(_apps(1)[0])
        self.qtApp.processEvents()

        self.assertTrue(self.page.refreshButton.isHidden())

        self.page._backToOverview()
        self.qtApp.processEvents()
        self.assertFalse(self.page.refreshButton.isHidden())

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

    def testCardButtonsKeepTouchFriendlyTargets(self):
        card = ApplicationCard()

        self.assertGreaterEqual(card.actionButton.height(), 40)
        self.assertGreaterEqual(card.removeButton.height(), 40)
        self.assertGreaterEqual(card.removeButton.width(), 40)
        self.assertGreaterEqual(self.page.adPrevious.width(), 40)
        self.assertGreaterEqual(self.page.adNext.width(), 40)
        card.deleteLater()

    def testAdsOnlyAdvanceOnVisibleAllAppsPage(self):
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page.show()
        self.page._prepareAds()
        self.assertFalse(self.page.adTimer.isActive())

        self.page._switchCatalogTab(1)
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
        self.qtApp.processEvents()

        self.assertTrue(self.page.adOverlay.isVisible())
        start = QPoint(self.page.adOverlay.width() - 30, 40)
        end = QPoint(30, 40)
        QTest.mousePress(self.page.adOverlay, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.page.adOverlay, end)
        QTest.mouseRelease(self.page.adOverlay, Qt.MouseButton.LeftButton, pos=end)

        self.assertEqual(self.page.adFlipView.currentIndex(), 1)

    def testAdvertisementUsesCenteredCropAndBoundedWidth(self):
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page.resize(1400, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

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
        self.assertGreaterEqual(self.page.adButton.height(), 40)
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
            {"id": 1, "title": "First", "image_url": ""},
            {"id": 2, "title": "Second", "image_url": ""},
        ]
        self.page.resize(1000, 800)
        self.page.show()
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        self.assertLessEqual(self.page.adFrame.height(), 240)
        self.assertEqual(self.page.adFlipView.borderRadius, 12)
        self.assertIn("border-radius: 12px", self.page.adOverlay.styleSheet())
        self.assertIs(self.page.adPrevious, self.page.adFlipView.preButton)
        self.assertIs(self.page.adNext, self.page.adFlipView.nextButton)

        self.page.adNext.click()
        self.assertEqual(self.page.adFlipView.currentIndex(), 1)
        self.page.adPrevious.click()
        self.assertEqual(self.page.adFlipView.currentIndex(), 0)

    def testAdvertisementGradientDarkensTheWholeLowerArea(self):
        self.page.resize(1000, 800)
        self.page.show()
        self.page.ads = [{"id": 1, "title": "Ad", "image_url": ""}]
        self.page._switchCatalogTab(1)
        self.page._prepareAds()
        QTest.qWait(20)

        image = self.page.adOverlay.grab().toImage()
        middle = image.pixelColor(image.width() - 10, int(image.height() * 0.72))
        bottom = image.pixelColor(image.width() - 10, image.height() - 10)

        self.assertGreaterEqual(middle.alpha(), 180)
        self.assertGreaterEqual(bottom.alpha(), 240)

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
        QTest.qWait(350)
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
        worker = CatalogWorker(store)
        results = []
        images = []
        completed = threading.Event()
        worker.finished.connect(lambda *result: results.append(result))
        worker.imageLoaded.connect(lambda *result: images.append(result))
        worker.completed.connect(completed.set)
        thread = threading.Thread(target=worker.run)
        thread.start()
        self.assertTrue(store.imageStarted.wait(1))
        QTest.qWait(20)

        self.assertEqual(results[0][0]["apps"][0]["id"], 1)
        self.assertEqual(images, [])

        store.releaseImage.set()
        thread.join(1)
        QTest.qWait(20)
        self.assertTrue(completed.is_set())
        self.assertEqual(images, [("https://example.test/icon.png", "cached.png")])

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
