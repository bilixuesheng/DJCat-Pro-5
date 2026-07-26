from unittest import TestCase
from unittest.mock import patch

import djcat


class WindowStub:
    def __init__(self, isSilent=False):
        self.isShown = not isSilent


class StartupTest(TestCase):
    def testNormalStartupShowsMainWindow(self):
        with patch.object(djcat, "MainWindow", WindowStub):
            window = djcat.startApp(isSilent=False)

        self.assertTrue(window.isShown)

    def testSilentStartupKeepsMainWindowHidden(self):
        with patch.object(djcat, "MainWindow", WindowStub):
            window = djcat.startApp(isSilent=True)

        self.assertFalse(window.isShown)
