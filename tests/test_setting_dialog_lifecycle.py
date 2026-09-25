from unittest import TestCase
from unittest.mock import patch

from app.view.pages.setting_page import ThemeColorSettingCard
from tests.support import isolateCfg


class ThemeColorDialogLifecycleTest(TestCase):
    def setUp(self):
        isolateCfg(self)

    @patch("app.view.pages.setting_page.ColorDialog")
    def testCustomColorDialogIsDeletedWhenExecRaises(self, colorDialog):
        colorDialog.return_value.exec.side_effect = RuntimeError("dialog failed")
        card = ThemeColorSettingCard()
        self.addCleanup(card.deleteLater)

        with self.assertRaisesRegex(RuntimeError, "dialog failed"):
            card._onButtonClicked(card.customButton)

        colorDialog.return_value.deleteLater.assert_called_once_with()
