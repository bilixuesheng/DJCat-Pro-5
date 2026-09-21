from PySide6.QtGui import QIcon

from app.config.cfg import cfg
from app.config.paths import ASSET_DIR


def defaultApplicationIconPath() -> str:
    return str(ASSET_DIR / "logo.png")


def applicationIcon() -> QIcon:
    """Resolve the icon shared by the window, splash screen and system tray."""
    icon = QIcon(
        cfg.applicationIconPath.value
        if cfg.applicationIconSource.value == "自定义"
        else defaultApplicationIconPath()
    )
    return icon if not icon.isNull() else QIcon(defaultApplicationIconPath())


def trayHomeIcon() -> QIcon:
    """The Tray Menu "主页" entry keeps its own cat icon in default mode."""
    if cfg.applicationIconSource.value != "自定义":
        return QIcon(str(ASSET_DIR / "logo_cat.png"))
    icon = QIcon(cfg.applicationIconPath.value)
    return icon if not icon.isNull() else QIcon(str(ASSET_DIR / "logo_cat.png"))
