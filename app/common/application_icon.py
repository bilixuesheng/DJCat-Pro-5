import os

from PySide6.QtGui import QIcon

from app.config.cfg import cfg
from app.config.paths import ASSET_DIR

# 设置页的几处预览在 paintEvent 里取图标，推移动画期间逐帧重绘。每次新建 QIcon
# 都要把整张图重新解码一遍（默认 256 px 的 logo 约 2.9 ms，自定义大图更久），
# 复用同一个对象只需 0.01 ms。键里带上文件修改时间，同一路径换了图也能生效。
_icons: dict[tuple, QIcon] = {}


def defaultApplicationIconPath() -> str:
    return str(ASSET_DIR / "logo.png")


def _cachedIcon(path: str, fallback: str) -> QIcon:
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        stamp = None
    key = (path, stamp, fallback)
    icon = _icons.get(key)
    if icon is None:
        icon = QIcon(path) if stamp is not None else QIcon()
        if icon.isNull() and path != fallback:
            icon = _cachedIcon(fallback, fallback)
        # 只留当前用得到的几项，换过的旧图不必一直占着解码结果。
        if len(_icons) > 8:
            _icons.clear()
        _icons[key] = icon
    return icon


def applicationIcon() -> QIcon:
    """Resolve the icon shared by the window, splash screen and system tray."""
    default = defaultApplicationIconPath()
    if cfg.applicationIconSource.value != "自定义":
        return _cachedIcon(default, default)
    return _cachedIcon(cfg.applicationIconPath.value, default)


def trayHomeIcon() -> QIcon:
    """The Tray Menu "主页" entry keeps its own cat icon in default mode."""
    cat = str(ASSET_DIR / "logo_cat.png")
    if cfg.applicationIconSource.value != "自定义":
        return _cachedIcon(cat, cat)
    return _cachedIcon(cfg.applicationIconPath.value, cat)
