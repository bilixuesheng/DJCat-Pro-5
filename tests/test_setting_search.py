import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow


class SettingSearchTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.quotaPatcher = patch.object(SettingPage, "_refreshAIQuota")
        self.quotaPatcher.start()
        with (
            patch.object(MainWindow, "_startMachineRegistration"),
            patch.object(MainWindow, "checkForUpdates"),
            patch("app.view.windows.main_window.SystemTrayIcon"),
        ):
            self.window = MainWindow(isSilent=True)

    def tearDown(self):
        self.window.tray = None
        self.window.deleteLater()
        self.app.processEvents()
        self.quotaPatcher.stop()

    def testSearchVisibilityUpdatesWhenNavigationStarts(self):
        self.assertTrue(self.window.searchEdit.isHidden())

        self.window.switchTo(self.window.settingPage)

        self.assertFalse(self.window.searchEdit.isHidden())
        self.assertIsNot(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
            "The transition should still be running when the search appears",
        )

        QTest.qWait(350)
        self.assertIs(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
        )

        self.window.searchEdit.setText("主题")
        self.window.switchTo(self.window.homePage)

        self.assertTrue(self.window.searchEdit.isHidden())
        self.assertEqual(self.window.searchEdit.text(), "")
        self.assertIs(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
            "The transition should still be running when the search disappears",
        )
