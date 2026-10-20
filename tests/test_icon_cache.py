import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon
from qfluentwidgets.common import icon as fluentIcon

from app.platform import icon_cache
from app.view.components.asset_icon import AssetIcon


def _render(icon, **attributes):
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    icon.render(painter, QRectF(0, 0, 24, 24), **attributes)
    painter.end()
    return pixmap.toImage()


class FluentIconCacheTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        icon_cache.cacheFluentSvgIcons()

    def testResourceIconIsParsedOnceAndDrawsTheSame(self):
        expected = QPixmap(24, 24)
        expected.fill(Qt.GlobalColor.transparent)
        painter = QPainter(expected)
        icon_cache._originalDrawSvgIcon(
            FluentIcon.EDIT.path(), painter, QRectF(0, 0, 24, 24)
        )
        painter.end()

        with patch.object(
            icon_cache, "QSvgRenderer", wraps=icon_cache.QSvgRenderer
        ) as renderer:
            icon_cache._renderers.clear()
            first = _render(FluentIcon.EDIT)
            for _ in range(5):
                _render(FluentIcon.EDIT)

        self.assertEqual(renderer.call_count, 1)
        self.assertEqual(first, expected.toImage())

    def testColoredIconsAreCachedPerColor(self):
        red = _render(FluentIcon.EDIT, fill=QColor("red").name())
        blue = _render(FluentIcon.EDIT, fill=QColor("blue").name())

        self.assertNotEqual(red, blue)
        self.assertEqual(red, _render(FluentIcon.EDIT, fill=QColor("red").name()))

    def testFilesOnDiskAreReadEveryTime(self):
        # 磁盘上的 SVG 可能被原地替换，按路径缓存会一直画旧图。
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "icon.svg"
            path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
                '<rect width="1" height="1" fill="#ff0000"/></svg>',
                encoding="utf-8",
            )
            with patch.object(
                icon_cache, "QSvgRenderer", wraps=icon_cache.QSvgRenderer
            ) as renderer:
                for _ in range(3):
                    pixmap = QPixmap(8, 8)
                    painter = QPainter(pixmap)
                    fluentIcon.drawSvgIcon(str(path), painter, QRectF(0, 0, 8, 8))
                    painter.end()

        self.assertEqual(renderer.call_count, 0)

    def testShippedAssetIconIsParsedOnceAndDrawsTheSame(self):
        # app/assets 只有 Client Update 会替换，而更新后程序会重启。
        expected = QPixmap(24, 24)
        expected.fill(Qt.GlobalColor.transparent)
        painter = QPainter(expected)
        icon_cache._originalDrawSvgIcon(
            AssetIcon.SHIFTS.path(), painter, QRectF(0, 0, 24, 24)
        )
        painter.end()

        with patch.object(
            icon_cache, "QSvgRenderer", wraps=icon_cache.QSvgRenderer
        ) as renderer:
            icon_cache._renderers.clear()
            first = _render(AssetIcon.SHIFTS)
            for _ in range(5):
                _render(AssetIcon.SHIFTS)
                _render(AssetIcon.SHIFTS, fill=QColor("red").name())

        self.assertEqual(renderer.call_count, 2)
        self.assertEqual(first, expected.toImage())

    def testCacheIsBounded(self):
        icon_cache._renderers.clear()
        pixmap = QPixmap(4, 4)
        painter = QPainter(pixmap)
        for index in range(icon_cache.CACHE_LIMIT + 20):
            source = (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
                f'<rect width="1" height="1" fill="#{index:06x}"/></svg>'
            ).encode()
            fluentIcon.drawSvgIcon(source, painter, QRectF(0, 0, 4, 4))
        painter.end()

        self.assertEqual(len(icon_cache._renderers), icon_cache.CACHE_LIMIT)


def _draw(icon, ratio, rect, draw=None):
    pixmap = QPixmap(round(40 * ratio), round(40 * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QColor(240, 244, 249))
    painter = QPainter(pixmap)
    (draw or fluentIcon.drawSvgIcon)(icon, painter, rect)
    painter.end()
    return pixmap.toImage()


def _original(icon, painter, rect):
    icon_cache._originalDrawSvgIcon(icon, painter, rect)


class FluentIconPixmapCacheTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        icon_cache.cacheFluentSvgIcons()

    def setUp(self):
        icon_cache._pixmaps.clear()
        icon_cache._pixmapBytes = 0

    def testIconsOnWholeDevicePixelsAreRasterizedOnceAndLookTheSame(self):
        rect = QRectF(4, 6, 16, 16)
        for ratio in (1.0, 1.5, 3.0):
            for icon in (FluentIcon.EDIT, FluentIcon.SETTING, FluentIcon.HOME):
                with self.subTest(ratio=ratio, icon=icon.name):
                    expected = _draw(icon.path(), ratio, rect, _original)
                    first = _draw(icon.path(), ratio, rect)
                    cached = dict(icon_cache._pixmaps)
                    size = round(16 * ratio)
                    self.assertIn((icon.path(), size, size), cached)
                    images = [first] + [_draw(icon.path(), ratio, rect) for _ in range(4)]

                    self.assertEqual(
                        {key: pixmap.cacheKey() for key, pixmap in icon_cache._pixmaps.items()},
                        {key: pixmap.cacheKey() for key, pixmap in cached.items()},
                    )
                    for image in images:
                        self.assertEqual(image, expected)

    def testScaledOrFractionalIconsAreDrawnDirectly(self):
        def scaled(icon, painter, rect):
            painter.scale(1.25, 1.25)
            fluentIcon.drawSvgIcon(icon, painter, rect)

        for draw, rect in ((scaled, QRectF(0, 0, 16, 16)), (None, QRectF(0.5, 0, 16, 16))):
            with self.subTest(rect=rect):
                _draw(FluentIcon.EDIT.path(), 1.0, rect, draw)

        self.assertEqual(len(icon_cache._pixmaps), 0)

    def testPixmapCacheStaysWithinItsBudget(self):
        with patch.object(icon_cache, "PIXMAP_CACHE_BYTES", 64 * 64 * 4 * 3):
            for index in range(10):
                source = (
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1">'
                    f'<rect width="1" height="1" fill="#{index:06x}"/></svg>'
                ).encode()
                pixmap = QPixmap(64, 64)
                painter = QPainter(pixmap)
                fluentIcon.drawSvgIcon(source, painter, QRectF(0, 0, 64, 64))
                painter.end()

        self.assertEqual(len(icon_cache._pixmaps), 3)
        self.assertEqual(icon_cache._pixmapBytes, 64 * 64 * 4 * 3)
