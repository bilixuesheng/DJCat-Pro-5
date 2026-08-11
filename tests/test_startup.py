import subprocess
import sys
from pathlib import Path
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

    def testMainWindowImportDefersTaskPageModules(self):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; "
                "import app.view.windows.main_window; "
                "pages = ('broadcast_page', 'countdown_page', "
                "'schedule_page', 'shutdown_page'); "
                "print([f'app.view.pages.{page}' in sys.modules "
                "for page in pages])",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            "[False, False, False, False]",
        )

    def testMainWindowImportDefersApplicationStorePage(self):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.view.windows.main_window; "
                "print('app.view.pages.app_store_page' in sys.modules)",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.stdout.strip().splitlines()[-1], "False")
