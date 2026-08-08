import subprocess
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import djcat


class WindowStub:
    def __init__(self, isSilent=False, showSplash=True):
        self.isShown = not isSilent
        self.showSplash = showSplash


class StartupTest(TestCase):
    def testNormalStartupShowsMainWindow(self):
        with patch.object(djcat, "MainWindow", WindowStub):
            window = djcat.startApp(isSilent=False)

        self.assertTrue(window.isShown)

    def testSilentStartupKeepsMainWindowHidden(self):
        with patch.object(djcat, "MainWindow", WindowStub):
            window = djcat.startApp(isSilent=True)

        self.assertFalse(window.isShown)

    def testExternalStartupScreenDisablesWindowSplash(self):
        with patch.object(djcat, "MainWindow", WindowStub):
            window = djcat.startApp(isSilent=False, showSplash=False)

        self.assertTrue(window.isShown)
        self.assertFalse(window.showSplash)

    def testEntryPointDefersMainWindowImport(self):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, djcat; "
                "print('app.view.windows.main_window' in sys.modules)",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "False")
