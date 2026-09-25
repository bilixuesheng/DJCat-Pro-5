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
