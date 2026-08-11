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
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            cfg.countdownBackgroundMode,
            cfg.countdownBackgroundColor,
            cfg.countdownBackgroundImagePath,
            cfg.countdownBackgroundScaleMode,
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

    def testWindowsKeepContentTransparentOverBackground(self):
        broadcast = BroadcastWindow()
        countdown = CountdownWindow()
        self.addCleanup(broadcast.close)
        self.addCleanup(countdown.close)

        broadcast._applyStyle()
        broadcast.show()
        broadcast.resize(320, 200)
        countdown.resize(320, 200)
        countdown._applyWindowState()
        self.app.processEvents()

        self.assertIn("background: transparent", broadcast.styleSheet())
        self.assertIn("background: transparent", broadcast.markdownView.styleSheet())
        self.assertIn("background: transparent", countdown.titleLabel.styleSheet())
        self.assertEqual(broadcast.background.size(), broadcast.size())
        self.assertEqual(countdown.background.size(), countdown.size())

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
