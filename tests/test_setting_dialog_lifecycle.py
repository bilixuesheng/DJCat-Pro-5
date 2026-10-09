from unittest import TestCase
from unittest.mock import patch

from PySide6.QtGui import QColor
from qfluentwidgets import qconfig

from app.config.cfg import THEME_COLOR_PRESETS, cfg
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


class ThemeColorSwatchTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        # 与启动时的 qconfig.load(CONFIG_PATH, cfg) 一致：此后 qconfig 的信号发在 cfg 上。
        patcher = patch.object(qconfig, "_cfg", cfg)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.card = ThemeColorSettingCard()
        self.addCleanup(self.card.deleteLater)

    def testSwatchFollowsAPresetChoice(self):
        name, rgb = THEME_COLOR_PRESETS[1]
        self.card.presetButtons[name].click()

        self.assertEqual(self.card.choiceSwatch._color, QColor(*rgb))

    @patch("app.view.pages.setting_page.ColorDialog")
    def testSwatchFollowsTheCustomColorWhileItIsPicked(self, colorDialog):
        self.card._onButtonClicked(self.card.customButton)
        onColorChanged = colorDialog.return_value.colorChanged.connect.call_args.args[0]

        onColorChanged(QColor(200, 30, 90))

        self.assertEqual(self.card.choiceSwatch._color, QColor(200, 30, 90))
