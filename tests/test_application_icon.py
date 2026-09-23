import os
import tempfile
import time
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.common.application_icon import applicationIcon, trayHomeIcon
from app.config.cfg import cfg


def _saveIcon(path, color):
    image = QImage(24, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def _color(icon):
    return icon.pixmap(24, 24).toImage().pixelColor(12, 12).name()


class ApplicationIconTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDir.cleanup)
        self.configFile = cfg.file
        self.source = cfg.applicationIconSource.value
        self.path = cfg.applicationIconPath.value
        cfg.file = Path(self.tempDir.name) / "config.json"
        self.addCleanup(self._restore)

    def _restore(self):
        cfg.set(cfg.applicationIconSource, self.source)
        cfg.set(cfg.applicationIconPath, self.path)
        cfg.file = self.configFile

    def testRepeatedLookupsReuseTheDecodedIcon(self):
        # 设置页预览在 paintEvent 里取图标；每次都新建 QIcon 会整张重新解码。
        self.assertIs(applicationIcon(), applicationIcon())
        self.assertIs(trayHomeIcon(), trayHomeIcon())

    def testChangingTheSettingResolvesTheNewIcon(self):
        path = Path(self.tempDir.name) / "custom.png"
        _saveIcon(path, "#ce352c")
        default = applicationIcon()

        cfg.set(cfg.applicationIconPath, str(path))
        cfg.set(cfg.applicationIconSource, "自定义")

        self.assertIsNot(applicationIcon(), default)
        self.assertEqual(_color(applicationIcon()), "#ce352c")
        self.assertEqual(_color(trayHomeIcon()), "#ce352c")

    def testReplacingTheFileAtTheSamePathIsPickedUp(self):
        path = Path(self.tempDir.name) / "custom.png"
        _saveIcon(path, "#ce352c")
        cfg.set(cfg.applicationIconPath, str(path))
        cfg.set(cfg.applicationIconSource, "自定义")
        self.assertEqual(_color(applicationIcon()), "#ce352c")

        time.sleep(0.02)
        _saveIcon(path, "#2c7ace")
        os.utime(path, None)

        self.assertEqual(_color(applicationIcon()), "#2c7ace")

    def testAMissingCustomFileFallsBackToTheDefault(self):
        default = _color(applicationIcon())
        cfg.set(cfg.applicationIconPath, str(Path(self.tempDir.name) / "gone.png"))
        cfg.set(cfg.applicationIconSource, "自定义")

        self.assertEqual(_color(applicationIcon()), default)
