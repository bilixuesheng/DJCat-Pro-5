from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.platform.memory import emptyWorkingSet
from app.view.windows.main_window import MainWindow


class MemoryLifecycleTest(TestCase):
    @patch("app.platform.memory.sys.platform", "linux")
    def testWorkingSetTrimIsWindowsOnly(self):
        self.assertFalse(emptyWorkingSet())

    @patch("app.view.windows.main_window.QTimer.singleShot")
    @patch("app.view.windows.main_window.cfg.set")
    def testHidingMainWindowSchedulesWorkingSetTrim(self, _, singleShot):
        window = MagicMock()
        event = MagicMock()

        MainWindow.closeEvent(window, event)

        event.ignore.assert_called_once_with()
        window.hide.assert_called_once_with()
        singleShot.assert_called_once_with(0, window, emptyWorkingSet)
