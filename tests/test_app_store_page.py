import os
import sys
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, QThread, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStackedLayout
from qfluentwidgets import DrillInTransitionStackedWidget

from app.view.pages.app_store_page import AppStorePage, ApplicationCard, CatalogWorker


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


class _BlockingCatalogStore:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def fetchCatalog(self):
        self.started.set()
        self.release.wait()
        return {"apps": [], "ads": []}


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
        self.page._allAppsForPage = lambda: apps
        self.page._renderAll()
        item = self.page.pager.item(1)

        self.page.pager._setPressedItem(item)

        self.assertEqual(self.page._currentPage, 1)
        self.assertEqual(self.page.pager.count(), 2)
        self.assertIsNotNone(self.page.allGrid.itemAtPosition(0, 0))

    def testSinglePageHidesPager(self):
        self.page._allAppsForPage = lambda: _apps(1)
        self.page._renderAll()

        self.assertTrue(self.page.pager.isHidden())

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

        self.assertEqual(
            self.page.adStack.stackingMode(),
            QStackedLayout.StackingMode.StackAll,
        )
        self.assertTrue(self.page.adOverlay.isVisible())
        start = QPoint(self.page.adOverlay.width() - 30, 40)
        end = QPoint(30, 40)
        QTest.mousePress(self.page.adOverlay, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(self.page.adOverlay, end)
        QTest.mouseRelease(self.page.adOverlay, Qt.MouseButton.LeftButton, pos=end)

        self.assertEqual(self.page.adFlipView.currentIndex(), 1)

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

    def testShutdownWaitsForActiveDownloadThread(self):
        worker = _CancelableWorker()
        thread = QThread(self.page)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        thread.start()
        QTest.qWait(20)

        self.page.store.downloadSlots = Mock()
        self.page._downloadJobs[1] = (thread, worker)

        self.page.shutdown()

        self.assertFalse(thread.isRunning())
        self.assertNotIn(1, self.page._downloadJobs)
        self.page.store.downloadSlots.release.assert_called_once_with()
