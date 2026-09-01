import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

from app.config.cfg import WINDOW_BACKGROUND_MODES, WINDOW_BACKGROUND_SCALE_MODES, cfg
from app.view.components.window_background import WindowBackground
from app.view.pages.broadcast_page import BroadcastWindow
from app.view.pages.countdown_page import CountdownWindow
from app.view.pages.fullscreen_clock import FullscreenClockWindow
from app.view.pages.setting_page import SettingPage


class WindowBackgroundTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        cfg.file = Path(self.tempDir.name) / "config.json"
        self.items = (
            cfg.bannerImageSource,
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            cfg.countdownBackgroundMode,
            cfg.countdownBackgroundColor,
            cfg.countdownBackgroundImagePath,
            cfg.countdownBackgroundScaleMode,
            cfg.fullscreenClockBackgroundMode,
            cfg.fullscreenClockBackgroundColor,
            cfg.fullscreenClockBackgroundImagePath,
            cfg.fullscreenClockBackgroundScaleMode,
        )
        self.values = [(item, item.value) for item in self.items]

    def tearDown(self):
        for item, value in self.values:
            cfg.set(item, value, save=False)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def testBackgroundConfigOffersIndependentModesAndScaleModes(self):
        self.assertEqual(WINDOW_BACKGROUND_MODES, ("主题色", "纯色", "图片"))
        self.assertEqual(
            WINDOW_BACKGROUND_SCALE_MODES,
            ("拉伸", "缩放(上)", "缩放(中)", "缩放(下)"),
        )
        self.assertEqual(cfg.broadcastBackgroundMode.defaultValue, "主题色")
        self.assertEqual(cfg.countdownBackgroundMode.defaultValue, "主题色")
        self.assertEqual(cfg.fullscreenClockBackgroundMode.defaultValue, "主题色")

    def testBackgroundPaintsSolidAndImageModes(self):
        parent = QWidget()
        background = WindowBackground(
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            lambda: QColor("#202020"),
            parent,
        )
        background.setGeometry(0, 0, 100, 60)
        parent.resize(100, 60)
        parent.show()
        self.addCleanup(parent.close)

        cfg.set(cfg.broadcastBackgroundMode, "纯色", save=False)
        cfg.set(cfg.broadcastBackgroundColor, QColor("#123456"), save=False)
        self.app.processEvents()
        self.assertEqual(
            background.grab().toImage().pixelColor(50, 30), QColor("#123456")
        )

        with tempfile.TemporaryDirectory() as tempDir:
            path = Path(tempDir) / "background.png"
            image = QImage(4, 2, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.red)
            self.assertTrue(image.save(str(path)))
            cfg.set(cfg.broadcastBackgroundMode, "图片", save=False)
            cfg.set(cfg.broadcastBackgroundImagePath, str(path), save=False)
            for mode in WINDOW_BACKGROUND_SCALE_MODES:
                cfg.set(cfg.broadcastBackgroundScaleMode, mode, save=False)
                self.app.processEvents()
                self.assertEqual(background._image().size(), background.size())

    def testWindowedBorderIsPaintedAboveDarkBackground(self):
        parent = QWidget()
        background = WindowBackground(
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            lambda: QColor("#000000"),
            parent,
        )
        background.setGeometry(0, 0, 100, 60)
        parent.resize(100, 60)
        parent.show()
        self.addCleanup(parent.close)

        cfg.set(cfg.broadcastBackgroundMode, "纯色", save=False)
        cfg.set(cfg.broadcastBackgroundColor, QColor("#000000"), save=False)
        background.setBorderVisible(True)
        self.app.processEvents()

        image = background.grab().toImage()
        self.assertEqual(image.pixelColor(0, 30), QColor("#808080"))
        self.assertEqual(image.pixelColor(50, 30), QColor("#000000"))

        background.setBorderVisible(False)
        self.app.processEvents()
        self.assertEqual(
            background.grab().toImage().pixelColor(0, 30),
            QColor("#000000"),
        )

    def testWindowsKeepContentTransparentOverBackground(self):
        broadcast = BroadcastWindow()
        countdown = CountdownWindow()
        clock = FullscreenClockWindow()
        self.addCleanup(broadcast.close)
        self.addCleanup(countdown.close)
        self.addCleanup(clock.close)

        broadcast._applyStyle()
        broadcast.show()
        broadcast.resize(320, 200)
        countdown.resize(320, 200)
        countdown._applyWindowState()
        clock.resize(320, 200)
        clock._applyWindowState()
        self.app.processEvents()

        self.assertIn("background: transparent", broadcast.styleSheet())
        self.assertIn("background: transparent", broadcast.markdownView.styleSheet())
        self.assertIn("background: transparent", countdown.titleLabel.styleSheet())
        self.assertEqual(broadcast.background.size(), broadcast.size())
        self.assertEqual(countdown.background.size(), countdown.size())
        self.assertEqual(clock.background.size(), clock.size())
        self.assertFalse(broadcast.background._borderVisible)
        self.assertFalse(countdown.background._borderVisible)
        self.assertFalse(clock.background._borderVisible)

        broadcast.is_windowed = True
        countdown.is_windowed = True
        clock.is_windowed = True
        broadcast._applyStyle()
        countdown._applyWindowState()
        clock._applyWindowState()
        self.app.processEvents()

        self.assertTrue(broadcast.background._borderVisible)
        self.assertTrue(countdown.background._borderVisible)
        self.assertTrue(clock.background._borderVisible)

    @patch("app.view.pages.setting_page.QFileDialog.getOpenFileName")
    def testSettingPageSelectsImageAndEnablesImageMode(self, getOpenFileName):
        page = SettingPage()
        self.addCleanup(page.deleteLater)
        getOpenFileName.return_value = ("C:/background.png", "")

        page._onChooseBackgroundImageClicked(
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundMode,
        )

        self.assertEqual(cfg.broadcastBackgroundImagePath.value, "C:/background.png")
        self.assertEqual(cfg.broadcastBackgroundMode.value, "图片")

    def testSettingCardsFollowSelectedImageAndBackgroundTypes(self):
        page = SettingPage()
        self.addCleanup(page.deleteLater)

        cfg.set(cfg.bannerImageSource, "预设: 罗小黑", save=False)
        self.assertTrue(page.chooseImageCard.isHidden())
        cfg.set(cfg.bannerImageSource, "自定义", save=False)
        self.assertFalse(page.chooseImageCard.isHidden())

        for mode, colorVisible, imageVisible in (
            ("主题色", False, False),
            ("纯色", True, False),
            ("图片", False, True),
        ):
            with self.subTest(mode=mode):
                cfg.set(cfg.broadcastBackgroundMode, mode, save=False)
                cfg.set(cfg.countdownBackgroundMode, mode, save=False)
                cfg.set(cfg.fullscreenClockBackgroundMode, mode, save=False)
                self.app.processEvents()
                self.assertEqual(
                    page.broadcastBackgroundColorCard.isHidden(),
                    not colorVisible,
                )
                self.assertEqual(
                    page.broadcastBackgroundImageCard.isHidden(),
                    not imageVisible,
                )
                self.assertEqual(
                    page.broadcastBackgroundScaleCard.isHidden(),
                    not imageVisible,
                )
                self.assertEqual(
                    page.countdownBackgroundColorCard.isHidden(),
                    not colorVisible,
                )
                self.assertEqual(
                    page.countdownBackgroundImageCard.isHidden(),
                    not imageVisible,
                )
                self.assertEqual(
                    page.countdownBackgroundScaleCard.isHidden(),
                    not imageVisible,
                )
                self.assertEqual(
                    page.fullscreenClockBackgroundColorCard.isHidden(),
                    not colorVisible,
                )
                self.assertEqual(
                    page.fullscreenClockBackgroundImageCard.isHidden(),
                    not imageVisible,
                )
                self.assertEqual(
                    page.fullscreenClockBackgroundScaleCard.isHidden(),
                    not imageVisible,
                )

        cfg.set(cfg.broadcastBackgroundMode, "主题色", save=False)
        page.setSearchText("背景颜色")
        self.assertTrue(page.broadcastBackgroundColorCard.isHidden())
        cfg.set(cfg.broadcastBackgroundMode, "纯色", save=False)
        self.assertFalse(page.broadcastBackgroundColorCard.isHidden())
        page.setSearchText("")

    @patch("app.view.pages.setting_page.ColorDialog")
    def testBackgroundColorDialogUsesChineseTitle(self, colorDialog):
        page = SettingPage()
        self.addCleanup(page.deleteLater)

        page.broadcastBackgroundColorCard._showColorDialog()

        self.assertEqual(colorDialog.call_args.args[1], "选择背景颜色")
        self.assertNotIn("Choose", colorDialog.call_args.args[1])
        colorDialog.return_value.deleteLater.assert_called_once_with()
