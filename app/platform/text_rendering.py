"""Let Qt cache the glyphs of large text instead of filling their outlines every paint.

Qt's raster engine caches a glyph as a bitmap only up to 64 device pixels; anything
bigger is drawn from its outline on every repaint. At 300% scaling the 26 pt body of a
Projection is about 104 device pixels, so each scroll step re-filled every visible
Chinese character's outline (a quarter second per frame). Qt reads the limit once,
at the first text it draws, so it has to be set before QApplication exists.
"""

import os

# 300% 下投送正文约 104、标题和一级标题约 195 个设备像素都在内；时钟和倒计时的
# 大数字仍按轮廓画，它们每秒只重画一次，而 Windows 上每个缓存像素要占 4 字节。
MAX_CACHED_GLYPH_SIZE = 256


def cacheLargeGlyphs() -> None:
    os.environ.setdefault("QT_MAX_CACHED_GLYPH_SIZE", str(MAX_CACHED_GLYPH_SIZE))
