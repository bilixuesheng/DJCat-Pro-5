from unittest import TestCase
from unittest.mock import patch

from PySide6.QtGui import QColor
from qfluentwidgets import Theme, qconfig, setTheme

from app.config.cfg import (
    CUSTOM_THEME_COLOR,
    THEME_COLOR_PRESETS,
    cfg,
    currentThemeColor,
    migrateConfig,
)
from app.view.pages.broadcast_page import VerticalButton
from app.view.pages.setting_page import ThemeColorSettingCard
from tests.support import isolateCfg

GREEN = QColor(49, 101, 49)
BLUE = QColor(76, 194, 255)
BLACK = QColor(0, 0, 0)
RED = QColor(200, 30, 30)


class ThemeColorPresetTest(TestCase):
    def setUp(self):
        isolateCfg(self)

    def testLuoXiaoHeiIsThirdPresetInPureBlack(self):
        self.assertEqual(
            [name for name, _ in THEME_COLOR_PRESETS], ["树人绿", "系统蓝", "罗小黑"]
        )
        self.assertEqual(QColor(*THEME_COLOR_PRESETS[2][1]), BLACK)
        self.assertEqual(cfg.themeColorPreset.defaultValue, "树人绿")

    def testCurrentThemeColorFollowsPresetOrCustomThemeColor(self):
        cfg.set(cfg.customThemeColor, RED, save=False)
        cfg.set(cfg.themeColorPreset, "罗小黑", save=False)
        self.assertEqual(currentThemeColor(), BLACK)
        cfg.set(cfg.themeColorPreset, CUSTOM_THEME_COLOR, save=False)
        self.assertEqual(currentThemeColor(), RED)


class ThemeColorMigrationTest(TestCase):
    def setUp(self):
        isolateCfg(self)

    def _migrate(self, preset, hasCustom=None):
        cfg.set(cfg.themeColorPreset, preset, save=False)
        cfg.set(cfg.hasCustomThemeColor, hasCustom, save=False)
        migrateConfig()
        return cfg.hasCustomThemeColor.value

    def testUserOnCustomKeepsCurrentColorAsCustomThemeColor(self):
        self.assertIs(self._migrate(CUSTOM_THEME_COLOR), True)

    def testUserOnPresetHasNoCustomThemeColor(self):
        # 旧版选预设时 CustomThemeColor 里存的是预设色，不是用户自定义过的颜色。
        self.assertIs(self._migrate("系统蓝"), False)

    def testMigratedValueIsLeftAlone(self):
        self.assertIs(self._migrate("系统蓝", True), True)


class ThemeColorSettingCardTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.themeColorPreset, "树人绿", save=False)
        cfg.set(cfg.customThemeColor, GREEN, save=False)
        cfg.set(cfg.hasCustomThemeColor, False, save=False)
        qconfig.set(qconfig.themeColor, GREEN, save=False)
        patcher = patch("app.view.pages.setting_page.ColorDialog")
        self.colorDialog = patcher.start()
        self.addCleanup(patcher.stop)
        self.card = ThemeColorSettingCard()
        self.addCleanup(self.card.deleteLater)

    def _acceptDialogWith(self, color):
        dialog = self.colorDialog.return_value

        def accept():
            for call in dialog.colorChanged.connect.call_args_list:
                call.args[0](QColor(color))

        dialog.exec.side_effect = accept

    def _cancelDialog(self):
        self.colorDialog.return_value.exec.side_effect = None

    def testChoosingColorSelectsCustomAndRemembersIt(self):
        self._acceptDialogWith(RED)
        self.card.chooseColorButton.click()

        self.assertEqual(cfg.themeColorPreset.value, CUSTOM_THEME_COLOR)
        self.assertEqual(cfg.customThemeColor.value, RED)
        self.assertIs(cfg.hasCustomThemeColor.value, True)
        self.assertEqual(qconfig.themeColor.value, RED)
        self.assertTrue(self.card.customButton.isChecked())
        self.assertEqual(self.card.choiceLabel.text(), "自定义")
        self.assertFalse(self.card.customSwatch.isHidden())

    def testPresetKeepsCustomThemeColorForOneClickReturn(self):
        self._acceptDialogWith(RED)
        self.card.chooseColorButton.click()
        self.colorDialog.reset_mock()

        self.card.presetButtons["罗小黑"].click()
        self.assertEqual(qconfig.themeColor.value, BLACK)
        self.assertEqual(cfg.customThemeColor.value, RED)
        self.assertEqual(self.card.choiceLabel.text(), "预设: 罗小黑")
        self.assertFalse(self.card.customSwatch.isHidden())

        self.card.customButton.click()
        self.colorDialog.assert_not_called()
        self.assertEqual(cfg.themeColorPreset.value, CUSTOM_THEME_COLOR)
        self.assertEqual(qconfig.themeColor.value, RED)

    def testCustomRowWithoutCustomThemeColorOpensDialog(self):
        self.assertTrue(self.card.customSwatch.isHidden())
        self._acceptDialogWith(RED)
        self.card.customButton.click()
        self.colorDialog.assert_called_once()
        self.assertEqual(qconfig.themeColor.value, RED)

    def testCancelChangesNothing(self):
        self.card.presetButtons["系统蓝"].click()
        self._cancelDialog()

        self.card.customButton.click()

        self.assertEqual(cfg.themeColorPreset.value, "系统蓝")
        self.assertIs(cfg.hasCustomThemeColor.value, False)
        self.assertEqual(qconfig.themeColor.value, BLUE)
        self.assertTrue(self.card.presetButtons["系统蓝"].isChecked())
        self.assertEqual(self.card.choiceLabel.text(), "预设: 系统蓝")

    def testDialogStartsFromCustomThemeColorElseCurrentColor(self):
        self.card.presetButtons["系统蓝"].click()
        self._cancelDialog()
        self.card.chooseColorButton.click()
        self.assertEqual(QColor(self.colorDialog.call_args.args[0]), BLUE)

        self._acceptDialogWith(RED)
        self.card.chooseColorButton.click()
        self.card.presetButtons["树人绿"].click()
        self._cancelDialog()
        self.card.chooseColorButton.click()
        self.assertEqual(QColor(self.colorDialog.call_args.args[0]), RED)

    def testColorEqualToPresetStaysCustom(self):
        self._acceptDialogWith(BLACK)
        self.card.chooseColorButton.click()
        self.assertEqual(cfg.themeColorPreset.value, CUSTOM_THEME_COLOR)
        self.assertTrue(self.card.customButton.isChecked())


class CornerButtonEdgeTest(TestCase):
    def setUp(self):
        isolateCfg(self)

    def testEveryCornerButtonHasPreviewEdge(self):
        # 罗小黑的关闭按钮落在倒计时和时钟的黑底上，只能靠这道细边分辨。
        setTheme(Theme.LIGHT, save=False)
        for primary, forceDark, edge in (
            (True, True, "rgba(255, 255, 255, 110)"),
            (False, True, "rgba(255, 255, 255, 110)"),
            (True, False, "rgba(0, 0, 0, 40)"),
            (False, False, "rgba(0, 0, 0, 40)"),
        ):
            button = VerticalButton(None, "关闭", primary=primary, forceDark=forceDark)
            self.addCleanup(button.deleteLater)
            self.assertIn(f"border: 1px solid {edge}", button.styleSheet())
