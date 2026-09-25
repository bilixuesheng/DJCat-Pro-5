import os
from unittest import TestCase

from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.view.components.banner_widget import BannerWidget
from tests.support import isolateCfg


class BannerSourceImageTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        self.tempDir = isolateCfg(self)

    def _banner(self):
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.resize(900, 300)
        banner._createCachedPixmap(900, 300)
        return banner

    def testHomeBannerAndSettingPreviewShareOneDecodedImage(self):
        # 设置页的横幅预览是第二个 BannerWidget。QPixmap 自带的 QPixmapCache 只收
        # 10 MB 以内的图，"树人门"（解码后 15 MB）和常见的自定义照片放不进去，
        # 两个横幅就各解码一份，打开过一次设置页后常驻整个会话。
        cfg.set(cfg.bannerImageSource, "预设: 树人门")
        home, preview = self._banner(), self._banner()

        self.assertIsNotNone(home._sourcePixmap)
        self.assertEqual(
            home._sourcePixmap.cacheKey(), preview._sourcePixmap.cacheKey()
        )

    def testAReplacedCustomImageIsDecodedAgain(self):
        path = self.tempDir / "banner.png"
        image = QImage(64, 32, QImage.Format.Format_ARGB32)
        image.fill(QColor("#ce352c"))
        self.assertTrue(image.save(str(path)))
        cfg.set(cfg.bannerImagePath, str(path))
        cfg.set(cfg.bannerImageSource, "自定义")
        first = self._banner()._sourcePixmap.cacheKey()

        image.fill(QColor("#2c7ace"))
        self.assertTrue(image.save(str(path)))
        os.utime(path, ns=(1, 1))

        banner = self._banner()
        self.assertNotEqual(banner._sourcePixmap.cacheKey(), first)
        self.assertEqual(
            banner._sourcePixmap.toImage().pixelColor(10, 10).name(), "#2c7ace"
        )


class BannerHighDpiTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def testTheCachedBannerIsRenderedAtDevicePixels(self):
        # 150%/200% 缩放下按逻辑尺寸渲染再被放大，横幅会发虚。
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.devicePixelRatioF = lambda: 2.0

        pixmap = banner._createCachedPixmap(450, 150)

        self.assertEqual((pixmap.width(), pixmap.height()), (900, 300))
        self.assertEqual(pixmap.devicePixelRatio(), 2.0)

    def testMovingToAScreenWithAnotherScaleRebuildsTheCache(self):
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.resize(450, 150)
        banner.show()
        banner.grab()
        first = banner._cachedPixmap

        banner.devicePixelRatioF = lambda: 1.5
        banner.grab()

        self.assertIsNot(banner._cachedPixmap, first)
        self.assertEqual(banner._cachedPixmap.devicePixelRatio(), 1.5)
