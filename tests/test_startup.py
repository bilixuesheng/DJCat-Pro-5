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
                "'schedule_page', 'home_card_task_page', 'shutdown_page'); "
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
            "[False, False, False, False, False]",
        )

    def testMainWindowImportDefersNavigationPagesExceptHome(self):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.view.windows.main_window; "
                "pages = ('app_store_page', 'credits_page', "
                "'tray_control_page', 'setting_page'); "
                "print([f'app.view.pages.{page}' in sys.modules "
                "for page in pages] + "
                "['app.common.application_store' in sys.modules])",
            ],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            "[False, False, False, False, False]",
        )

    def testMainWindowImportDefersOptionalEditorsAndRenderingDependencies(self):
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.view.windows.main_window; "
                "modules = ('app.view.components.home_card_dialog', "
                "'app.view.components.markdown_view', "
                "'pyqt_github_markdown', 'edge_tts'); "
                "print([module in sys.modules for module in modules])",
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
