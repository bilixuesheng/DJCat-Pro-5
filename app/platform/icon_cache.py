from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtSvg import QSvgRenderer
from qfluentwidgets.common import icon as _fluentIcon
from qfluentwidgets.components.widgets import info_bar as _fluentInfoBar

# QFluentWidgets 每次绘制图标都新建 QSvgRenderer，把 SVG 从资源里重新读出并解析一遍；
# 透明背景的页面滚动时每帧都要重绘所有可见图标，解析占了单个图标绘制的八成以上。
# 只缓存内容不会变的来源：Qt 资源路径和 SVG 源码本身。磁盘文件可能被替换，照旧每次读。
CACHE_LIMIT = 512

_renderers: OrderedDict = OrderedDict()
_svgSources: OrderedDict = OrderedDict()
_originalDrawSvgIcon = _fluentIcon.drawSvgIcon
_originalWriteSvg = _fluentIcon.writeSvg


def _remember(cache: OrderedDict, key, value):
    cache[key] = value
    if len(cache) > CACHE_LIMIT:
        cache.popitem(last=False)
    return value


def _rendererKey(icon):
    if isinstance(icon, str):
        return icon if icon.startswith(":/") else None
    if isinstance(icon, QByteArray):
        return icon.data()
    if isinstance(icon, (bytes, bytearray)):
        return bytes(icon)
    return None


def drawSvgIcon(icon, painter, rect) -> None:
    key = _rendererKey(icon)
    if key is None:
        _originalDrawSvgIcon(icon, painter, rect)
        return
    renderer = _renderers.get(key)
    if renderer is None:
        renderer = _remember(_renderers, key, QSvgRenderer(icon))
    else:
        _renderers.move_to_end(key)
    renderer.render(painter, QRectF(rect))


def writeSvg(iconPath: str, indexes=None, **attributes) -> str:
    if not isinstance(iconPath, str) or not iconPath.startswith(":/"):
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
