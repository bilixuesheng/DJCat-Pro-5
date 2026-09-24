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

    def runWithTranslators(self, body, bundledOnly=False):
        """在独立进程里装翻译器：翻译器是 QApplication 全局的，会影响同进程的其他测试。"""
        repo = Path(__file__).resolve().parents[1]
        prelude = (
            "import os\n"
            "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
            "from PySide6.QtWidgets import QApplication\n"
            "import djcat\n"
            "app = QApplication([])\n"
        )
        if bundledOnly:
            # 打包版里 QLibraryInfo 指不到 PySide6 的 translations，只剩随包带的那一份。
            prelude += (
                "import shutil, tempfile\n"
                "from pathlib import Path\n"
                "from unittest.mock import patch\n"
                "from PySide6.QtCore import QLibraryInfo\n"
                "import app.config.paths as paths\n"
                "source = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)\n"
                "bundled = Path(tempfile.mkdtemp())\n"
                "shutil.copy(Path(source) / 'qtbase_zh_CN.qm', bundled)\n"
                "paths.QT_TRANSLATIONS_DIR = bundled\n"
                "with patch.object(QLibraryInfo, 'path', return_value=tempfile.mkdtemp()):\n"
                "    djcat.installTranslators(app)\n"
            )
        else:
            prelude += "djcat.installTranslators(app)\n"
        result = subprocess.run(
            [sys.executable, "-c", prelude + body],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip().splitlines()[-1]

    def testFluentTranslatorShowsBuiltInSwitchAndEditMenuInChinese(self):
        output = self.runWithTranslators(
            "from qfluentwidgets import LineEdit, SwitchButton\n"
            "from qfluentwidgets.components.widgets.menu import LineEditMenu\n"
            "button = SwitchButton()\n"
            "off = button.getText()\n"
            "button.setChecked(True)\n"
            "menu = LineEditMenu(LineEdit())\n"
            "menu.createActions()\n"
            "print([off, button.getText()] + [a.text() for a in menu.action_list])\n"
        )

        self.assertEqual(
            output, "['关', '开', '剪切', '复制', '粘贴', '撤回', '全选']"
        )

    def testQtTranslatorShowsNativeContextMenusInChinese(self):
        body = (
            "from PySide6.QtCore import QCoreApplication\n"
            "from PySide6.QtWidgets import QLineEdit\n"
            "edit = QLineEdit()\n"
            "menu = edit.createStandardContextMenu()\n"
            "texts = [a.text().split('\\t')[0] for a in menu.actions() if a.text()]\n"
            "link = QCoreApplication.translate('QWidgetTextControl', 'Copy &Link Location')\n"
            "print(texts + [link])\n"
        )
        expected = (
            "['撤消(&U)', '重做(&R)', '剪切(&T)', '复制(&C)', '粘贴(&P)', '删除', "
            "'全选', '复制链接地址(&L)']"
        )

        for bundledOnly in (False, True):
            with self.subTest(bundledOnly=bundledOnly):
                self.assertEqual(self.runWithTranslators(body, bundledOnly), expected)
