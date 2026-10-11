from unittest import TestCase

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import (
    PushButton,
    Theme,
    qconfig,
    setCustomStyleSheet,
    setTheme,
    setThemeColor,
)
from qfluentwidgets.common import style_sheet as fluentStyleSheet
from qfluentwidgets.common.style_sheet import (
    FluentStyleSheet,
    StyleSheetCompose,
    getStyleSheet,
    styleSheetManager,
)

from app.platform.style_sheet import optimizeFluentStyleSheets
from tests.support import isolateCfg


class StyleSheetNestingTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        optimizeFluentStyleSheets()

    def setUp(self):
        isolateCfg(self)
        self.addCleanup(setThemeColor, qconfig.themeColor.value)
        self.addCleanup(setTheme, qconfig.themeMode.value)
        self.button = PushButton("按钮")
        setCustomStyleSheet(
            self.button,
            "PushButton { padding: 1px; }",
            "PushButton { padding: 2px; }",
        )
        self.addCleanup(self._deleteButton)

    def _deleteButton(self):
        self.button.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _nestedLevels(self):
        source = styleSheetManager.source(self.button)
        levels = 0
        while isinstance(source.sources[0], StyleSheetCompose):
            source = source.sources[0]
            levels += 1
        return levels

    def testThemeChangesLeaveEachWidgetsStyleSheetAsItWas(self):
        for lazy in (False, True):
            with self.subTest(lazy=lazy):
                setTheme(Theme.LIGHT, lazy=lazy)
                lightStyleSheet = self.button.styleSheet()
                for theme in (Theme.DARK, Theme.LIGHT) * 3:
                    setTheme(theme, lazy=lazy)

                self.assertEqual(self._nestedLevels(), 0)
                if not lazy:
                    self.assertEqual(self.button.styleSheet(), lightStyleSheet)

    def testThemeColorChangesLeaveEachWidgetsStyleSheetAsItWas(self):
        setThemeColor(QColor("#336699"))
        styleSheet = self.button.styleSheet()
        for color in ("#993366", "#336699") * 3:
            setThemeColor(QColor(color))

        self.assertEqual(self._nestedLevels(), 0)
        self.assertEqual(self.button.styleSheet(), styleSheet)

    def testCustomStyleSheetStillFollowsTheTheme(self):
        setTheme(Theme.DARK)
        self.assertIn("padding: 2px", self.button.styleSheet())
        self.assertNotIn("padding: 1px", self.button.styleSheet())
        setTheme(Theme.LIGHT)
        self.assertIn("padding: 1px", self.button.styleSheet())
        self.assertNotIn("padding: 2px", self.button.styleSheet())


class _CountingWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.styleSheetsSet = 0

    def setStyleSheet(self, styleSheet):
        self.styleSheetsSet += 1
        super().setStyleSheet(styleSheet)


class UnchangedStyleSheetTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        optimizeFluentStyleSheets()

    def setUp(self):
        isolateCfg(self)
        self.addCleanup(setThemeColor, qconfig.themeColor.value)
        self.addCleanup(setTheme, qconfig.themeMode.value)
        setTheme(Theme.LIGHT)
        # 主窗口的样式表不含主题色，主窗口页面栈带的就是它。
        self.widget = _CountingWidget()
        self.addCleanup(self.widget.deleteLater)
        fluentStyleSheet.setStyleSheet(self.widget, FluentStyleSheet.FLUENT_WINDOW)

    def testThemeColorChangeDoesNotReapplyAStyleSheetThatStaysTheSame(self):
        applied = self.widget.styleSheetsSet
        setThemeColor(QColor("#993366"))

        self.assertEqual(self.widget.styleSheetsSet, applied)

    def testThemeChangeStillAppliesTheNewStyleSheet(self):
        light = self.widget.styleSheet()
        setTheme(Theme.DARK)

        self.assertNotEqual(self.widget.styleSheet(), light)
        self.assertEqual(
            self.widget.styleSheet().rstrip(),
            getStyleSheet(FluentStyleSheet.FLUENT_WINDOW, Theme.DARK).rstrip(),
        )
