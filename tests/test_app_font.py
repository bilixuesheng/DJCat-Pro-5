from unittest import TestCase

from PySide6.QtWidgets import QApplication, QLabel
from qfluentwidgets import qconfig

from app.common.app_font import applyAppFont
from app.view.components.banner_widget import BannerWidget
from app.view.components.markdown_view import MarkdownView
from app.view.pages.countdown_page import CountdownWindow
from tests.support import isolateCfg


class AppFontTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        originalFont = self.app.font()
        self.addCleanup(self.app.setFont, originalFont)
        isolateCfg(self)
        applyAppFont()

    def _fluentFamilies(self):
        return qconfig.get(qconfig.fontFamilies)

    def testBannerTitleUsesTheFluentFamilies(self):
        # 主页横幅的"主页"是普通 QLabel，样式表只写字号和粗细。跟着系统消息字体走时，
        # 换成只有西文的系统字体后中文落到 Qt 自己的候补列表，简体中文排第一的是宋体。
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.galleryLabel.ensurePolished()

        self.assertEqual(banner.galleryLabel.font().families(), self._fluentFamilies())

    def testCountdownTitleUsesTheFluentFamilies(self):
        window = CountdownWindow()
        self.addCleanup(window.close)
        window.resize(720, 240)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.titleLabel.font().families(), self._fluentFamilies())

    def testMarkdownTextUsesTheFluentFamilies(self):
        view = MarkdownView(largeText=True)
        self.addCleanup(view.deleteLater)
        view.setMarkdown("# 标题\n\n正文")
        view.resize(600, 400)
        view.show()
        self.app.processEvents()

        for name in ("h1", "paragraph"):
            label = view.findChild(QLabel, name)
            self.assertEqual(label.font().families(), self._fluentFamilies(), name)
