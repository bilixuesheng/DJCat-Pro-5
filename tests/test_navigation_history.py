from types import SimpleNamespace
from unittest import TestCase

from PySide6.QtWidgets import QApplication, QStackedWidget
from qfluentwidgets import qrouter

from app.view.windows.main_window import NAVIGATION_HISTORY_LIMIT, MainWindow


class NavigationHistoryTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.stacked = QStackedWidget()
        self.addCleanup(self.stacked.deleteLater)
        history, stackHistories = qrouter.history, qrouter.stackHistories
        qrouter.history, qrouter.stackHistories = [], {}

        def restore():
            qrouter.history, qrouter.stackHistories = history, stackHistories

        self.addCleanup(restore)
        qrouter.setDefaultRouteKey(self.stacked, "HomePage")

    def testSwitchingPagesForeverKeepsOnlyRecentHistory(self):
        window = SimpleNamespace(stackedWidget=self.stacked)
        for index in range(200):
            qrouter.push(self.stacked, ("SettingPage", "HomePage")[index % 2])
            MainWindow._trimNavigationHistory(window)

        stacked = qrouter.stackHistories[self.stacked]
        self.assertEqual(len(qrouter.history), NAVIGATION_HISTORY_LIMIT)
        self.assertEqual(len(stacked.history), NAVIGATION_HISTORY_LIMIT + 1)
        self.assertEqual(stacked.history[0], "HomePage")
        self.assertEqual(stacked.history[-1], "HomePage")
        self.assertEqual(qrouter.history[-1].routeKey, "HomePage")
