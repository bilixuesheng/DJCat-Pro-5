import json
import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets"
APP_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False) or "__compiled__" in globals()
    else Path(__file__).resolve().parents[2]
)
LOG_DIR = APP_DIR / "Log"
USER_DATA_DIR = Path(
    QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.GenericDataLocation
    )
) / "DJCatPro"
PORTABLE_DATA_DIR = APP_DIR / "DJCatPro"
_PORTABLE_FALLBACK_FAILED = False
if PORTABLE_DATA_DIR.is_dir():
    APP_DATA_DIR = PORTABLE_DATA_DIR
elif USER_DATA_DIR.is_dir():
    APP_DATA_DIR = USER_DATA_DIR
else:
    try:
        PORTABLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
        APP_DATA_DIR = PORTABLE_DATA_DIR
    except OSError:
        APP_DATA_DIR = USER_DATA_DIR
        _PORTABLE_FALLBACK_FAILED = True
CONFIG_PATH = APP_DATA_DIR / "UserConfig.json"
UPDATE_DIR = APP_DIR / "Updata"
UPDATE_ZIP_PATH = UPDATE_DIR / "DJCat-Pro.zip"
UPDATE_STAGING_DIR = UPDATE_DIR / "staging"
PROGRAM_DIR = APP_DATA_DIR / "Program"
APP_STORE_CACHE_DIR = APP_DATA_DIR / "AppStoreCache"
APP_STORE_DOWNLOAD_DIR = APP_STORE_CACHE_DIR / "downloads"
HOME_CARD_ICON_DIR = APP_DATA_DIR / "HomeCardIcons"


def isPortable() -> bool:
    return APP_DATA_DIR == PORTABLE_DATA_DIR


def _rebaseConfigPaths(configPath: Path, source: Path, target: Path) -> None:
    if not configPath.is_file():
        return
    with configPath.open("r", encoding="utf-8") as file:
        data = json.load(file)
    # 配置里的路径由 APP_DATA_DIR 拼出，而它没有被 resolve()：8.3 短名、目录联接和映射
    # 网络盘展开后都是另一串字符，只比展开后的形式会漏掉整份配置。写回时用 target 原样，
    # 它就是下次启动 paths.py 算出的 APP_DATA_DIR。
    sources = {str(source), str(source.resolve())}
    targetText = str(target)

    def rebase(value):
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rebase(item) for item in value]
        if not isinstance(value, str):
            return value
        valueKey = os.path.normcase(value)
        for sourceText in sources:
            sourceKey = os.path.normcase(sourceText)
            if valueKey == sourceKey:
                return targetText
            if valueKey.startswith(sourceKey + os.sep):
                return targetText + value[len(sourceText) :]
        return value

    updated = rebase(data)
    temporary = configPath.with_suffix(f"{configPath.suffix}.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(updated, file, ensure_ascii=False, indent=4)
    temporary.replace(configPath)


def migrateAppData(target: Path) -> None:
    source = APP_DATA_DIR
    target = Path(target)
    if source == target:
        return
    if not isPortable():
        staging = target.with_name(f"{target.name}.migrating")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            if source.exists():
                shutil.copytree(source, staging, dirs_exist_ok=True)
            _rebaseConfigPaths(staging / CONFIG_PATH.name, source, target)
            staging.replace(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return

    target.mkdir(parents=True, exist_ok=True)
    if source.exists():
        shutil.copytree(source, target, dirs_exist_ok=True)
    _rebaseConfigPaths(target / CONFIG_PATH.name, source, target)
    if not source.exists():
        return
    backup = source.with_name(f"{source.name}.bak")
    index = 2
    while backup.exists():
        backup = source.with_name(f"{source.name}.bak-{index}")
        index += 1
    source.rename(backup)
