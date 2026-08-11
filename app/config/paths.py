import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False) or "__compiled__" in globals()
    else Path(__file__).resolve().parents[2]
)
APP_DATA_DIR = Path(
    QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation
    )
) / "DJCatPro"
CONFIG_PATH = APP_DATA_DIR / "UserConfig.json"
UPDATE_DIR = APP_DIR / "Updata"
UPDATE_INSTALLER_PATH = UPDATE_DIR / "DJCat-Pro.exe"
PROGRAM_DIR = APP_DATA_DIR / "Program"
APP_STORE_CACHE_DIR = APP_DATA_DIR / "AppStoreCache"
APP_STORE_DOWNLOAD_DIR = APP_STORE_CACHE_DIR / "downloads"
