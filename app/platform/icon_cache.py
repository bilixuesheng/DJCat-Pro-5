from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget
from qfluentwidgets.common import icon as _fluentIcon
from qfluentwidgets.components.widgets import info_bar as _fluentInfoBar

from app.config.paths import ASSET_DIR

# QFluentWidgets 每次绘制图标都新建 QSvgRenderer，把 SVG 从资源里重新读出并解析一遍；
# 透明背景的页面滚动时每帧都要重绘所有可见图标，解析占了单个图标绘制的八成以上。
# 只缓存内容不会变的来源：Qt 资源路径、随程序发布的 app/assets 和 SVG 源码本身。
# app/assets 只有 Client Update 会替换，换完程序就重启了；其他磁盘文件可能被替换，照旧每次读。
CACHE_LIMIT = 512
# 画好的位图另算字节：300% 下一个 16 px 图标就是 48 × 48，滚动时每帧都要重新光栅化。
PIXMAP_CACHE_BYTES = 16 * 1024 * 1024

_renderers: OrderedDict = OrderedDict()
_svgSources: OrderedDict = OrderedDict()
_pixmaps: OrderedDict = OrderedDict()
_pixmapBytes = 0
_UNSCALED = (
    QTransform.TransformationType.TxNone,
    QTransform.TransformationType.TxTranslate,
)
_originalDrawSvgIcon = _fluentIcon.drawSvgIcon
_originalWriteSvg = _fluentIcon.writeSvg
_ASSET_PREFIX = ASSET_DIR.as_posix() + "/"


def _remember(cache: OrderedDict, key, value):
    cache[key] = value
    if len(cache) > CACHE_LIMIT:
        cache.popitem(last=False)
    return value


def _unchanging(path) -> bool:
    return isinstance(path, str) and path.startswith((":/", _ASSET_PREFIX))


def _rendererKey(icon):
    if isinstance(icon, str):
        return icon if _unchanging(icon) else None
    if isinstance(icon, QByteArray):
        return icon.data()
    if isinstance(icon, (bytes, bytearray)):
        return bytes(icon)
    return None


def _renderer(key, icon) -> QSvgRenderer:
    renderer = _renderers.get(key)
    if renderer is None:
        return _remember(_renderers, key, QSvgRenderer(icon))
    _renderers.move_to_end(key)
    return renderer


def _deviceRect(painter, rect: QRectF):
    """The icon's rect in whole device pixels, or None when a bitmap would not match."""
    device = painter.device()
    if not isinstance(device, (QWidget, QPixmap, QImage)):
        return None
    if painter.worldTransform().type() not in _UNSCALED:
        return None
    if painter.compositionMode() != QPainter.CompositionMode.CompositionMode_SourceOver:
        return None
    ratio = device.devicePixelRatioF()
    origin = painter.worldTransform().map(rect.topLeft()) * ratio
    values = (origin.x(), origin.y(), rect.width() * ratio, rect.height() * ratio)
    if any(abs(value - round(value)) > 1e-6 for value in values) or values[2] < 1 or values[3] < 1:
        return None
    return ratio, round(values[2]), round(values[3])


def _pixmap(key, renderer, ratio, width, height) -> QPixmap:
    global _pixmapBytes
    cacheKey = (key, width, height)
    pixmap = _pixmaps.get(cacheKey)
    if pixmap is not None:
        _pixmaps.move_to_end(cacheKey)
    else:
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, width, height))
        painter.end()
        _pixmaps[cacheKey] = pixmap
        _pixmapBytes += width * height * 4
        while _pixmapBytes > PIXMAP_CACHE_BYTES and len(_pixmaps) > 1:
            _, evicted = _pixmaps.popitem(last=False)
            _pixmapBytes -= evicted.width() * evicted.height() * 4
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def drawSvgIcon(icon, painter, rect) -> None:
    key = _rendererKey(icon)
    if key is None:
        _originalDrawSvgIcon(icon, painter, rect)
        return
    renderer = _renderer(key, icon)
    rect = QRectF(rect)
    deviceRect = _deviceRect(painter, rect)
    if deviceRect is None:
        renderer.render(painter, rect)
        return
    # 图标落在整设备像素上、没有缩放时，先画成位图再贴，结果与直接画相同。
    painter.drawPixmap(rect.topLeft(), _pixmap(key, renderer, *deviceRect))


def writeSvg(iconPath: str, indexes=None, **attributes) -> str:
    if not _unchanging(iconPath):
        return _originalWriteSvg(iconPath, indexes, **attributes)
    try:
        key = (
            iconPath,
            tuple(indexes) if indexes else None,
            tuple(sorted(attributes.items())),
        )
        hash(key)
    except TypeError:
        return _originalWriteSvg(iconPath, indexes, **attributes)
    source = _svgSources.get(key)
    if source is None:
        source = _remember(
            _svgSources,
            key,
            _originalWriteSvg(iconPath, indexes, **attributes),
        )
    else:
        _svgSources.move_to_end(key)
    return source


def cacheFluentSvgIcons() -> None:
    """Parse each QFluentWidgets SVG icon once instead of on every paint."""
    for module in (_fluentIcon, _fluentInfoBar):
        module.drawSvgIcon = drawSvgIcon
        module.writeSvg = writeSvg
