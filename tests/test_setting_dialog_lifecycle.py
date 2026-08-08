import ast
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock


class ThemeColorDialogLifecycleTest(TestCase):
    @classmethod
    def setUpClass(cls):
        sourcePath = (
            Path(__file__).parents[1]
            / "app"
            / "view"
            / "pages"
            / "setting_page.py"
        )
        module = ast.parse(sourcePath.read_text(encoding="utf-8"))
        cardClass = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef)
            and node.name == "ThemeColorSettingCard"
        )
        method = next(
            node
            for node in cardClass.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_onButtonClicked"
        )
        cls.methodCode = compile(
            ast.fix_missing_locations(
                ast.Module(body=[method], type_ignores=[])
            ),
            str(sourcePath),
            "exec",
        )

    def testCustomColorDialogIsDeletedWhenExecRaises(self):
        dialog = Mock()
        dialog.exec.side_effect = RuntimeError("dialog failed")
        config = Mock()
        config.customThemeColor.value = "green"
        namespace = {
            "ColorDialog": Mock(return_value=dialog),
            "THEME_COLOR_PRESETS": (),
            "QColor": Mock(),
            "cfg": config,
        }
        exec(self.methodCode, namespace)

        card = Mock()
        card.customButton = Mock()
        card.customButton.text.return_value = "自定义颜色"
        card.presetButtons = {}
        card.window.return_value = object()

        with self.assertRaisesRegex(RuntimeError, "dialog failed"):
            namespace["_onButtonClicked"](card, card.customButton)

        dialog.deleteLater.assert_called_once_with()
