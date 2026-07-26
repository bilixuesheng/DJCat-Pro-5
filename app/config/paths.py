from pathlib import Path

from PySide6.QtCore import QStandardPaths

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
APP_DATA_DIR = Path(
    QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation
    )
) / "DJCatPro"
CONFIG_PATH = APP_DATA_DIR / "UserConfig.json"
