"""Log（日志）：DJCat 按天写下的诊断记录，以及更新器留在程序目录的那份更新记录。"""

import contextlib
import shutil
import time
from pathlib import Path

from loguru import logger

from app.config.paths import APP_DIR, LOG_DIR

LOG_RETENTION_DAYS = 14
LOG_FILE_NAME = "djcatpro日志_{time:YYYY-MM-DD}.log"
_LOG_GLOB = "djcatpro日志_*.log"
UPDATER_LOG_PATH = APP_DIR / "updater.log"
# 旧版本把日志写在程序目录里，Client Update 整目录换名时会被一起丢掉。
LEGACY_LOG_DIR = APP_DIR / "Log"


def configureLogging() -> None:
    _adoptLegacyLogs()
    _removeExpiredLogs()
    logger.add(
        str(LOG_DIR / LOG_FILE_NAME),
        rotation="00:00",
        # 设了 rotation 后，loguru 只在跨零点轮转时执行保留期，进程退出时不执行；
        # 每天开关机、从不跨零点运行的电脑全靠上面启动时的清理。
        retention=f"{LOG_RETENTION_DAYS} days",
        enqueue=True,
        encoding="utf-8",
    )


def _removeExpiredLogs() -> None:
    deadline = time.time() - LOG_RETENTION_DAYS * 24 * 60 * 60
    for path in _dailyLogs() + _updaterLog():
        with contextlib.suppress(OSError):
            if path.stat().st_mtime <= deadline:
                path.unlink()


def clearableLogSize() -> int:
    total = 0
    for path in _clearableLogs():
        with contextlib.suppress(OSError):
            total += path.stat().st_size
    return total


def clearLogs() -> None:
    for path in _clearableLogs():
        with contextlib.suppress(OSError):
            path.unlink()


def _dailyLogs() -> list[Path]:
    return [path for path in LOG_DIR.glob(_LOG_GLOB) if path.is_file()]


def _updaterLog() -> list[Path]:
    return [UPDATER_LOG_PATH] if UPDATER_LOG_PATH.is_file() else []


def _clearableLogs() -> list[Path]:
    # 最新的一份正被 loguru 写着，Windows 上删不掉；清理后显示的大小也不算它，
    # 否则清完按钮还亮着，再点也没有变化。
    return sorted(_dailyLogs(), key=_modifiedTime)[:-1] + _updaterLog()


def _modifiedTime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _adoptLegacyLogs() -> None:
    if not LEGACY_LOG_DIR.is_dir():
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for path in LEGACY_LOG_DIR.iterdir():
        target = LOG_DIR / path.name
        if target.exists():
            continue
        with contextlib.suppress(OSError):
            shutil.move(path, target)
    with contextlib.suppress(OSError):
        LEGACY_LOG_DIR.rmdir()
