import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import MSFluentWindow

from app.config.cfg import cfg
from app.config.constants import APP_NAME
from app.view.pages.setting_page import SettingPage
from app.view.windows.main_window import MainWindow


class SettingSearchTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.windowTitle = cfg.windowTitle.value
        cfg.file = Path(self.tempDir.name) / "config.json"
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
        self.window._shutdownResources()
        self.window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.quotaPatcher.stop()
        cfg.set(cfg.windowTitle, self.windowTitle)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testSearchVisibilityUpdatesWhenNavigationStarts(self):
        self.assertTrue(self.window.searchEdit.isHidden())

        self.window.switchTo(self.window.settingPage)

        self.assertFalse(self.window.searchEdit.isHidden())
        self.assertIsNot(
            self.window.stackedWidget.currentWidget(),
            self.window.settingPage,
            "The transition should still be running when the search appears",
        )

        QTest.qWait(500)
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

    def testDuplicateNavigationDuringTransitionIsIgnored(self):
        with patch.object(MSFluentWindow, "switchTo", autospec=True) as switchTo:
            self.window.switchTo(self.window.settingPage)
            self.window.switchTo(self.window.settingPage)

        switchTo.assert_called_once_with(self.window, self.window.settingPage)

    def testCustomWindowTitleUpdatesAndBlankRestoresDefault(self):
        titleEdit = self.window.settingPage.windowTitleCard.lineEdit
        titleEdit.setText("值班控制台")
        titleEdit.editingFinished.emit()
        self.assertEqual(cfg.windowTitle.value, "值班控制台")
        self.assertEqual(self.window.windowTitle(), "值班控制台")

        titleEdit.setText("   ")
        titleEdit.editingFinished.emit()
        self.assertEqual(self.window.windowTitle(), APP_NAME)

    def testRepeatedQueuedDestinationRunsOnlyOnce(self):
        changes = []
        self.window.stackedWidget.currentChanged.connect(
            lambda _: changes.append(self.window.stackedWidget.currentWidget())
        )

        self.window.switchTo(self.window.settingPage)
        self.window.switchTo(self.window.creditsPage)
        self.window.switchTo(self.window.creditsPage)
        QTest.qWait(800)

        self.assertEqual(
            changes,
            [self.window.settingPage, self.window.creditsPage],
        )
        self.assertIsNone(self.window._navigationTarget)
        self.assertIsNone(self.window._pendingNavigation)

    def testLatestQueuedDestinationReplacesIntermediateDestination(self):
        changes = []
        schedulePage = self.window._getSchedulePage()
        self.window.stackedWidget.currentChanged.connect(
            lambda _: changes.append(self.window.stackedWidget.currentWidget())
        )

        self.window.switchTo(self.window.settingPage)
        self.window.switchTo(self.window.creditsPage)
        self.window.switchTo(schedulePage)
        QTest.qWait(800)

        self.assertEqual(
            changes,
            [self.window.settingPage, schedulePage],
        )
        self.assertIs(
            self.window.stackedWidget.currentWidget(),
            schedulePage,
        )

    def testTaskPagesAreCreatedOnlyWhenFirstOpened(self):
        pageSpecs = (
            ("全屏投送", "broadcastEditPage"),
            ("考试倒计时", "countdownPage"),
            ("定时播报", "schedulePage"),
            ("定时关机", "shutdownPage"),
        )
        self.assertTrue(
            all(getattr(self.window, name) is None for _, name in pageSpecs)
        )

        for title, name in pageSpecs:
            with self.subTest(page=name):
                previousCount = self.window.stackedWidget.count()
                self.window.homePage.all_cards[title].clicked.emit()
                QTest.qWait(500)
                page = getattr(self.window, name)

                self.assertIsNotNone(page)
                self.assertIs(self.window.stackedWidget.currentWidget(), page)
                self.assertEqual(
                    self.window.stackedWidget.count(),
                    previousCount + 1,
                )

                self.window._navToHome()
                QTest.qWait(500)
                self.window.homePage.all_cards[title].clicked.emit()
                QTest.qWait(500)

                self.assertIs(getattr(self.window, name), page)
                self.assertEqual(
                    self.window.stackedWidget.count(),
                    previousCount + 1,
                )

                self.window._navToHome()
                QTest.qWait(500)

    def testBackgroundSchedulesDoNotLoadManagementPages(self):
        broadcastTask = {"type": "系统TTS", "content": "测试"}
        shutdownTask = {"notify": False}

        with (
            patch.object(
                self.window,
                "_scheduledTask",
                side_effect=(broadcastTask, shutdownTask),
            ),
            patch.object(self.window, "_playAudioTask") as playAudio,
            patch.object(self.window, "_handleShutdownTask") as handleShutdown,
        ):
            self.window._checkSchedule()

        playAudio.assert_called_once_with(broadcastTask)
        handleShutdown.assert_called_once_with(shutdownTask)
        self.assertIsNone(self.window.schedulePage)
        self.assertIsNone(self.window.shutdownPage)
