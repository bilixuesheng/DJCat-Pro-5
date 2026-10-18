from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import Theme, qconfig, setTheme, setThemeColor

from app.config.cfg import (
    CUSTOM_THEME_COLOR,
    THEME_COLOR_PRESETS,
    cfg,
    currentThemeColor,
    migrateConfig,
)
from app.view.components.window_background import closeButtonColors
from app.view.pages.broadcast_page import VerticalButton
from app.view.pages.setting_page import ThemeColorSettingCard
from tests.support import isolateCfg

GREEN = QColor(49, 101, 49)
BLUE = QColor(76, 194, 255)
BLACK = QColor(0, 0, 0)
WHITE = QColor(255, 255, 255)
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
        setTheme(Theme.LIGHT, save=False)

    def _button(self, primary, forceDark=True):
        button = VerticalButton(FIF.CLOSE, "关闭", primary=primary, forceDark=forceDark)
        self.addCleanup(button.deleteLater)
        return button

    def testOnlyPureBlackOrWhiteCloseButtonHasEdge(self):
        # 罗小黑的关闭按钮落在倒计时和时钟的黑底上，只能靠这道细边分辨；纯白同理。
        for color, edge in (
            (GREEN, None),
            (BLUE, None),
            (QColor("#050505"), None),
            (BLACK, QColor(255, 255, 255, 110)),
            (WHITE, QColor(0, 0, 0, 40)),
        ):
            setThemeColor(color)
            self.assertEqual(closeButtonColors().edge, edge, color.name())
            for primary in (True, False):
                self.assertIn("border: none", self._button(primary).styleSheet())

    def testPureWhiteCloseButtonHasBlackForeground(self):
        setThemeColor(WHITE)
        self.assertEqual(self._button(True)._foregroundColor(), QColor("black"))
        setThemeColor(BLACK)
        self.assertEqual(self._button(True)._foregroundColor(), QColor("white"))

    def testPureBlackAndWhiteStillChangeOnHoverAndPress(self):
        # lighter()/darker() 对纯黑纯白不起作用。
        for color in (BLACK, WHITE):
            setThemeColor(color)
            colors = closeButtonColors()
            self.assertEqual(len({colors.normal.name(), colors.hover.name(), colors.pressed.name()}), 3)

    def testCloseButtonFollowsThemeColorWhileOpen(self):
        setThemeColor(GREEN)
        button = self._button(True)
        projectionButton = self._button(False, forceDark=False)
        setThemeColor(BLACK)
        self.assertIn("background-color: #000000", button.styleSheet())
        self.assertEqual(button._closeColors.edge, QColor(255, 255, 255, 110))
        setTheme(Theme.DARK, save=False)
        self.assertIn("rgba(255, 255, 255, 26)", projectionButton.styleSheet())

    def testEdgeIsOneStrokeWithoutBrightJoints(self):
        # 样式表的圆角边框在直边和圆弧的接头处叠出亮点（110 叠成 173）。
        setThemeColor(BLACK)
        button = self._button(True)
        image = QImage(button.size() * 3, QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(3)
        image.fill(BLACK)
        button.render(image, QPoint(), renderFlags=QWidget.RenderFlag.DrawChildren)
        ring = [image.pixelColor(x, y).red() for x in range(image.width()) for y in range(3)]
        ring += [image.pixelColor(x, y).red() for y in range(image.height()) for x in range(3)]
        self.assertGreater(max(ring), 100)
        self.assertLess(max(ring), 120)
