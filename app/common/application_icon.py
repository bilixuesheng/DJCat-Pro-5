import os

from PySide6.QtGui import QIcon

from app.config.cfg import cfg
from app.config.paths import ASSET_DIR

# 设置页的几处预览在 paintEvent 里取图标，每次新建 QIcon 都会把整张图重新解码，
# 所以复用同一个对象。键里带上文件修改时间，同一路径换了图也能生效。
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
    """Resolve the icon shared by the main window and splash screen."""
    default = defaultApplicationIconPath()
    if cfg.applicationIconSource.value != "自定义":
        return _cachedIcon(default, default)
    return _cachedIcon(cfg.applicationIconPath.value, default)


def _customTrayIcon() -> QIcon | None:
    if cfg.trayIconSource.value != "自定义":
        return None
    icon = _cachedIcon(cfg.trayIconPath.value, cfg.trayIconPath.value)
    # 自定义的托盘图片丢了就退回跟随，而不是让托盘变成空白。
    return None if icon.isNull() else icon


def trayIcon() -> QIcon:
    """The Tray Icon follows the Application Icon unless it has its own image."""
    custom = _customTrayIcon()
    return custom if custom is not None else applicationIcon()


def trayHomeIcon() -> QIcon:
    """The Tray Menu "主页" entry follows the Tray Icon, but while both follow
    the default it keeps its own cat icon."""
    custom = _customTrayIcon()
    if custom is not None:
        return custom
    cat = str(ASSET_DIR / "logo_cat.png")
    if cfg.applicationIconSource.value != "自定义":
        return _cachedIcon(cat, cat)
    return _cachedIcon(cfg.applicationIconPath.value, cat)
