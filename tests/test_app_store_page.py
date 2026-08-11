import os
import sys
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import DrillInTransitionStackedWidget

from app.view.pages.app_store_page import AppStorePage, ApplicationCard


class _Store:
    architecture = "x86_64"

    def mergeInstalled(self, apps):
        return list(apps)


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

    def testResponsiveGridUsesThreeColumnsAtDesktopWidth(self):
        apps = _apps(3)
        self.page.allGridWidget.resize(950, 600)
        self.page._renderGrid(self.page.allGrid, apps)

        self.assertIsInstance(self.page.allGrid.itemAtPosition(0, 2).widget(), ApplicationCard)

    def testResponsiveGridUsesTwoAndOneColumnsOnNarrowTouchLayouts(self):
        self.page.allGridWidget.resize(700, 600)
        self.assertEqual(self.page._columnCount(self.page.allGrid), 2)
        self.page.allGridWidget.resize(500, 600)
        self.assertEqual(self.page._columnCount(self.page.allGrid), 1)

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
