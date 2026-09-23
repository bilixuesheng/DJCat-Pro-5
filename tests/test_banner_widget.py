import os
import tempfile
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.components.banner_widget import BannerWidget


class BannerSourceImageTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDir.cleanup)
        self.configFile = cfg.file
        self.source = cfg.bannerImageSource.value
        self.path = cfg.bannerImagePath.value
        cfg.file = Path(self.tempDir.name) / "config.json"
        self.addCleanup(self._restore)

    def _restore(self):
        cfg.set(cfg.bannerImageSource, self.source)
        cfg.set(cfg.bannerImagePath, self.path)
        cfg.file = self.configFile

    def _banner(self):
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.resize(900, 300)
        banner._create_cached_pixmap(900, 300)
        return banner

    def testHomeBannerAndSettingPreviewShareOneDecodedImage(self):
        # 设置页的横幅预览是第二个 BannerWidget。QPixmap 自带的 QPixmapCache 只收
        # 10 MB 以内的图，"树人门"（解码后 15 MB）和常见的自定义照片放不进去，
        # 两个横幅就各解码一份，打开过一次设置页后常驻整个会话。
        cfg.set(cfg.bannerImageSource, "预设: 树人门")
        home, preview = self._banner(), self._banner()

        self.assertIsNotNone(home._source_pixmap)
        self.assertEqual(
            home._source_pixmap.cacheKey(), preview._source_pixmap.cacheKey()
        )

    def testAReplacedCustomImageIsDecodedAgain(self):
        path = Path(self.tempDir.name) / "banner.png"
        image = QImage(64, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ce352c"))
        self.assertTrue(image.save(str(path)))
        cfg.set(cfg.bannerImagePath, str(path))
        cfg.set(cfg.bannerImageSource, "自定义")
        first = self._banner()._source_pixmap.cacheKey()

        image.fill(QColor("#2c7ace"))
        self.assertTrue(image.save(str(path)))
        os.utime(path, ns=(1, 1))

        banner = self._banner()
        self.assertNotEqual(banner._source_pixmap.cacheKey(), first)
        self.assertEqual(
            banner._source_pixmap.toImage().pixelColor(10, 10).name(), "#2c7ace"
        )
