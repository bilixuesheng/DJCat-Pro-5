from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget
from qfluentwidgets import BodyLabel, ComboBox, qconfig

from app.common import app_font
from app.common.app_font import applyAppFont, previewFamilies, resolveFamilies
from app.config.cfg import DEFAULT_FONT, SYSTEM_FONT, cfg
from app.signal_bus import signalBus
from app.view.components.banner_widget import BannerWidget
from app.view.components.font_picker import (
    ROW_HEIGHT,
    FontPickerDialog,
    FontSettingCard,
    fontChoices,
    fontDisplayName,
)
from app.view.components.markdown_view import MarkdownView
from app.view.pages.broadcast_page import BroadcastWindow
from app.view.pages.countdown_page import CountdownWindow
from tests.support import isolateCfg

FLUENT_DEFAULT = ["Segoe UI", "Microsoft YaHei", "PingFang SC"]
INSTALLED = {"Inter", "KaiTi", "Microsoft YaHei"}
FONT_ITEMS = (cfg.appFontMode, cfg.appFont, cfg.latinFont, cfg.cjkFont)


def _installed(value):
    return value in INSTALLED


class AppFontCase(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        # 清理按登记的反序执行：先把字体换回默认（这时 qconfig 里还是测试用的那串，
        # 已有控件才认得出来并换回），再还原配置，最后还原程序字体。
        self.addCleanup(self.app.setFont, self.app.font())
        isolateCfg(self)
        self.addCleanup(self._restoreDefaultFont)
        patcher = patch.object(app_font, "fontInstalled", _installed)
        patcher.start()
        self.addCleanup(patcher.stop)
        applyAppFont()

    def _restoreDefaultFont(self):
        for item in FONT_ITEMS:
            cfg.set(item, item.defaultValue, save=False)
        applyAppFont()

    def _fluentFamilies(self):
        return qconfig.get(qconfig.fontFamilies)


class PlainWidgetFontTest(AppFontCase):
    def testBannerTitleUsesTheFluentFamilies(self):
        # 主页横幅的"主页"是普通 QLabel，样式表只写字号和粗细。跟着系统消息字体走时，
        # 换成只有西文的系统字体后中文落到 Qt 自己的候补列表，简体中文排第一的是宋体。
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.galleryLabel.ensurePolished()

        self.assertEqual(banner.galleryLabel.font().families(), FLUENT_DEFAULT)

    def testCountdownTitleUsesTheFluentFamilies(self):
        window = CountdownWindow()
        self.addCleanup(window.close)
        window.resize(720, 240)
        window.show()
        self.app.processEvents()

        self.assertEqual(window.titleLabel.font().families(), FLUENT_DEFAULT)

    def testMarkdownTextUsesTheFluentFamilies(self):
        view = MarkdownView(largeText=True)
        self.addCleanup(view.deleteLater)
        view.setMarkdown("# 标题\n\n正文")
        view.resize(600, 400)
        view.show()
        self.app.processEvents()

        for name in ("h1", "paragraph"):
            label = view.findChild(QLabel, name)
            self.assertEqual(label.font().families(), FLUENT_DEFAULT, name)


class ResolveFamiliesTest(AppFontCase):
    def testDefaultIsWhatQFluentWidgetsShipsWith(self):
        self.assertEqual(resolveFamilies("统一", DEFAULT_FONT, DEFAULT_FONT, DEFAULT_FONT), FLUENT_DEFAULT)
        self.assertEqual(
            resolveFamilies("中西文分开", DEFAULT_FONT, DEFAULT_FONT, DEFAULT_FONT), FLUENT_DEFAULT
        )

    def testOneFontKeepsTheDefaultChineseFontBehindIt(self):
        # 只有西文的字体没有汉字，后面不补雅黑，中文就落到 Qt 的候补列表（宋体）。
        self.assertEqual(
            resolveFamilies("统一", "Inter", DEFAULT_FONT, DEFAULT_FONT),
            ["Inter", "Microsoft YaHei", "PingFang SC"],
        )

    def testSeparateFontsPutLatinFirstAndChineseAfter(self):
        self.assertEqual(
            resolveFamilies("中西文分开", "Inter", "Inter", "KaiTi"),
            ["Inter", "KaiTi", "Microsoft YaHei", "PingFang SC"],
        )
        # 统一模式的字体不参与分开模式，反之亦然。
        self.assertEqual(
            resolveFamilies("统一", "KaiTi", "Inter", "KaiTi"),
            ["KaiTi", "Microsoft YaHei", "PingFang SC"],
        )

    def testAMissingFontShowsAsTheDefault(self):
        self.assertEqual(resolveFamilies("统一", "Gone", DEFAULT_FONT, DEFAULT_FONT), FLUENT_DEFAULT)
        self.assertEqual(
            resolveFamilies("中西文分开", DEFAULT_FONT, "Gone", "Gone"), FLUENT_DEFAULT
        )

    def testFollowSystemTakesTheSystemFontForLatin(self):
        system = app_font.systemFontFamily()
        self.assertEqual(
            resolveFamilies("统一", SYSTEM_FONT, DEFAULT_FONT, DEFAULT_FONT),
            list(dict.fromkeys([system, "Microsoft YaHei", "PingFang SC"])),
        )
        # 中文那一档没有「跟随系统」，存了也按默认。
        self.assertEqual(
            resolveFamilies("中西文分开", DEFAULT_FONT, DEFAULT_FONT, SYSTEM_FONT), FLUENT_DEFAULT
        )

    def testAFontIsListedOnce(self):
        self.assertEqual(
            resolveFamilies("中西文分开", DEFAULT_FONT, "Microsoft YaHei", DEFAULT_FONT),
            ["Microsoft YaHei", "PingFang SC"],
        )

    def testPreviewSwapsOneValueInTheModeThatShowsIt(self):
        cfg.set(cfg.latinFont, "Inter", save=False)
        self.assertEqual(
            previewFamilies(cfg.cjkFont, "KaiTi"),
            ["Inter", "KaiTi", "Microsoft YaHei", "PingFang SC"],
        )
        self.assertEqual(
            previewFamilies(cfg.appFont, "KaiTi"), ["KaiTi", "Microsoft YaHei", "PingFang SC"]
        )


class LiveAppFontTest(AppFontCase):
    NEW = ["Inter", "Microsoft YaHei", "PingFang SC"]

    def _change(self):
        cfg.set(cfg.appFont, "Inter", save=False)
        applyAppFont()
        self.app.processEvents()

    def testEveryKindOfWidgetTakesTheNewFontAtOnce(self):
        banner = BannerWidget()
        self.addCleanup(banner.deleteLater)
        banner.show()
        body = BodyLabel("正文")
        self.addCleanup(body.deleteLater)
        body.show()
        combo = ComboBox()
        self.addCleanup(combo.deleteLater)
        combo.addItems(["一", "二"])
        combo.show()
        countdown = CountdownWindow()
        self.addCleanup(countdown.close)
        countdown.resize(720, 240)
        countdown.show()
        projection = BroadcastWindow()
        self.addCleanup(projection.close)
        projection.setContent("标题", "正文")
        projection.show()
        markdown = MarkdownView(largeText=True)
        self.addCleanup(markdown.deleteLater)
        markdown.setMarkdown("# 标题\n\n正文\n\n- 圆点\n\n1. 编号")
        markdown.show()
        self.app.processEvents()
        bullet, number = (
            next(
                label
                for label in markdown.findChildren(QLabel, "list-marker")
                if label.property("kind") == kind
            )
            for kind in ("bullet", "number")
        )

        self._change()

        checked = {
            "横幅标题": banner.galleryLabel,
            "BodyLabel": body,
            "下拉框": combo,
            "倒计时标题": countdown.titleLabel,
            "倒计时时间": countdown.timeLabel,
            "投送标题": projection.titleLabel,
            "投送正文": projection.contentEdit,
            "Markdown 段落": markdown.findChild(QLabel, "paragraph"),
            "Markdown 列表编号": number,
        }
        for name, widget in checked.items():
            with self.subTest(name):
                self.assertEqual(widget.font().families(), self.NEW)
        # 字号和粗细是各自定的，换字体不动它们。
        self.assertEqual(projection.contentEdit.font().pointSizeF(), 26.0)
        self.assertTrue(countdown.titleLabel.font().bold())
        # 列表圆点是渲染器生成的符号，始终用默认字体，换了字体它的大小和高低才不变。
        self.assertEqual(bullet.font().families(), FLUENT_DEFAULT)
        stale = [
            type(widget).__name__
            for widget in QApplication.allWidgets()
            if widget.font().families() == FLUENT_DEFAULT and widget.property("kind") != "bullet"
        ]
        self.assertEqual(stale, [])

    def testAppFontChangedIsSentOnlyWhenTheFamiliesChange(self):
        sent = []

        def record():
            sent.append(True)

        signalBus.appFontChanged.connect(record)
        self.addCleanup(signalBus.appFontChanged.disconnect, record)

        cfg.set(cfg.latinFont, "Inter", save=False)
        applyAppFont()
        self.assertEqual(sent, [])

        self._change()
        self.assertEqual(sent, [True])
        self.assertEqual(self._fluentFamilies(), self.NEW)


class FontPickerTest(AppFontCase):
    FAMILIES = ["Inter", "@Microsoft YaHei", "Microsoft YaHei", "Wingdings", "KaiTi"]
    SYSTEMS = {
        "Inter": [QFontDatabase.WritingSystem.Latin],
        "Microsoft YaHei": [
            QFontDatabase.WritingSystem.Latin,
            QFontDatabase.WritingSystem.SimplifiedChinese,
        ],
        "@Microsoft YaHei": [QFontDatabase.WritingSystem.SimplifiedChinese],
        "Wingdings": [QFontDatabase.WritingSystem.Symbol],
        "KaiTi": [QFontDatabase.WritingSystem.SimplifiedChinese],
    }

    def setUp(self):
        super().setUp()
        for name, value in (
            ("families", lambda *_args: list(self.FAMILIES)),
            ("writingSystems", lambda family: self.SYSTEMS.get(family, [])),
            ("isPrivateFamily", lambda _family: False),
        ):
            patcher = patch.object(QFontDatabase, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch("app.view.components.font_picker.fontInstalled", _installed)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.systemFont = "System Sans"
        patcher = patch(
            "app.view.components.font_picker.systemFontFamily", lambda: self.systemFont
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _values(self, item):
        return [choice.value for choice in fontChoices(item)]

    def testChoicesStartWithDefaultAndSkipVerticalFaces(self):
        self.assertEqual(
            self._values(cfg.appFont),
            [DEFAULT_FONT, SYSTEM_FONT, "Inter", "Microsoft YaHei", "Wingdings", "KaiTi"],
        )

    def testChineseFontListsOnlySimplifiedChineseFonts(self):
        self.assertEqual(self._values(cfg.cjkFont), [DEFAULT_FONT, "Microsoft YaHei", "KaiTi"])

    def testLatinFontListsOnlyFontsWithoutChinese(self):
        # 西文字体带着汉字的话，Qt 让它连汉字一起显示，中文字体永远轮不到。
        self.assertEqual(
            self._values(cfg.latinFont), [DEFAULT_FONT, SYSTEM_FONT, "Inter", "Wingdings"]
        )
        self.systemFont = "Microsoft YaHei"
        self.assertEqual(self._values(cfg.latinFont), [DEFAULT_FONT, "Inter", "Wingdings"])
        self.assertIn(SYSTEM_FONT, self._values(cfg.appFont))

    def testEachNameIsWrittenInItsOwnFaceExceptSymbolFonts(self):
        choices = {choice.value: choice for choice in fontChoices(cfg.appFont)}
        self.assertEqual(choices["KaiTi"].families[0], "KaiTi")
        self.assertEqual(choices["Wingdings"].families, ())

    def testCardShowsAMissingFontAsTheDefault(self):
        self.assertEqual(fontDisplayName(DEFAULT_FONT), "默认")
        self.assertEqual(fontDisplayName("KaiTi"), "KaiTi")
        self.assertEqual(fontDisplayName("Gone"), "Gone（未安装，正在使用默认）")

    def _dialog(self, item, height=700):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.resize(900, height)
        parent.show()
        dialog = FontPickerDialog(item, "选择字体", parent)
        dialog.show()
        self.app.processEvents()
        return dialog

    def testClickingARowSelectsItAndPreviewsTheResultingFont(self):
        cfg.set(cfg.appFontMode, "中西文分开", save=False)
        cfg.set(cfg.latinFont, "Inter", save=False)
        dialog = self._dialog(cfg.cjkFont)
        fontList = dialog.fontList
        self.assertEqual(dialog.selectedValue(), DEFAULT_FONT)

        index = fontList.indexOfValue("KaiTi")
        QTest.mouseClick(fontList, Qt.MouseButton.LeftButton, pos=fontList.rowRect(index).center())

        self.assertEqual(dialog.selectedValue(), "KaiTi")
        self.assertEqual(
            dialog.sampleLabel.font().families(),
            ["Inter", "KaiTi", "Microsoft YaHei", "PingFang SC"],
        )

    def testAShortWindowShrinksTheListInsteadOfOverlappingTheButtons(self):
        # 主窗口最矮 400：卡片被压矮时由字体列表让出高度，不能压到示例文字和按钮上。
        for height in (400, 700):
            with self.subTest(height=height):
                dialog = self._dialog(cfg.appFont, height)
                card = dialog.widget.geometry()
                self.assertTrue(dialog.rect().contains(card))
                self.assertLessEqual(
                    dialog.scrollArea.geometry().bottom(), dialog.sampleLabel.geometry().top()
                )
                self.assertLessEqual(
                    dialog.sampleLabel.geometry().bottom(), dialog.buttonGroup.geometry().top()
                )
                self.assertGreaterEqual(dialog.scrollArea.height(), ROW_HEIGHT * 2)
        # 空间够时按内容高度显示，最多 9 行。
        self.assertEqual(
            dialog.scrollArea.height(), min(dialog.fontList.height(), ROW_HEIGHT * 9)
        )

    def testSearchKeepsOnlyMatchingRows(self):
        dialog = self._dialog(cfg.appFont)
        dialog.searchEdit.setText("kai")
        self.assertEqual(
            [dialog.fontList.choices()[index].value for index in dialog.fontList.visibleIndexes()],
            ["KaiTi"],
        )

    def testCardOpensThePickerWithTheCurrentFontAndSavesTheChoice(self):
        cfg.set(cfg.appFont, "KaiTi", save=False)
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        parent.resize(900, 700)
        card = FontSettingCard(cfg.appFont, "字体", "", parent)
        self.assertEqual(card.valueLabel.text(), "KaiTi")
        opened = []

        def exec_(dialog):
            opened.append(dialog.selectedValue())
            dialog.fontList.setCurrentIndex(dialog.fontList.indexOfValue("Inter"))
            return True

        with patch.object(FontPickerDialog, "exec", exec_):
            card.chooseButton.click()

        self.assertEqual(opened, ["KaiTi"])
        self.assertEqual(cfg.appFont.value, "Inter")
        self.assertEqual(card.valueLabel.text(), "Inter")
