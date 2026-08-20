from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo
from loguru import logger


# A zero timer can monopolize the event loop; 1 ms removes the practical frame
# cap without delaying an already overdue animation tick.
UNLOCKED_TIMER_INTERVAL_MS = 1


# PySide6 doesn't bind QAnimationDriver, but the pinned Qt runtime exports its
# unified timer on every supported desktop platform.
class _QtAnimationTimer:
    def __init__(self, library, instance, setTimingInterval):
        self._library = library
        self._instance = instance
        self._setTimingInterval = setTimingInterval

    @classmethod
    def create(cls):
        library = cls._loadQtCore()
        symbolPairs = (
            (
                "?instance@QUnifiedTimer@@SAPEAV1@XZ",
                "?setTimingInterval@QUnifiedTimer@@QEAAXH@Z",
            ),
            (
                "_ZN13QUnifiedTimer8instanceEv",
                "_ZN13QUnifiedTimer17setTimingIntervalEi",
            ),
        )

        for instanceName, setIntervalName in symbolPairs:
            try:
                instance = getattr(library, instanceName)
                setTimingInterval = getattr(library, setIntervalName)
            except AttributeError:
                continue

            instance.argtypes = []
            instance.restype = ctypes.c_void_p
            setTimingInterval.argtypes = [ctypes.c_void_p, ctypes.c_int]
            setTimingInterval.restype = None
            return cls(library, instance, setTimingInterval)

        raise RuntimeError("当前 QtCore 未导出 QUnifiedTimer")

    @staticmethod
    def _loadQtCore():
        qtRoot = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PrefixPath))
        libraryPath = Path(
            QLibraryInfo.path(QLibraryInfo.LibraryPath.LibrariesPath)
        )
        binariesPath = Path(
            QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath)
        )

        if sys.platform == "win32":
            names = ("Qt6Core.dll",)
            load = ctypes.WinDLL
        elif sys.platform == "darwin":
            names = (
                "QtCore.framework/QtCore",
                "libQt6Core.6.dylib",
                "libQt6Core.dylib",
            )
            load = ctypes.CDLL
        else:
            names = ("libQt6Core.so.6", "libQt6Core.so")
            load = ctypes.CDLL

        for directory in (libraryPath, binariesPath, qtRoot):
            for name in names:
                path = directory / name
                if path.is_file():
                    return load(str(path))

        raise RuntimeError("找不到 Qt6Core 动态库")

    def setInterval(self, interval: int) -> None:
        instance = self._instance()
        if not instance:
            raise RuntimeError("无法创建 QUnifiedTimer")
        self._setTimingInterval(instance, interval)


_animationTimer: _QtAnimationTimer | None = None


def unlockQtAnimations() -> None:
    global _animationTimer

    if _animationTimer is not None:
        return

    try:
        timer = _QtAnimationTimer.create()
        timer.setInterval(UNLOCKED_TIMER_INTERVAL_MS)
        _animationTimer = timer
    except (OSError, RuntimeError) as error:
        logger.warning("无法解除 Qt 动画帧率限制，将使用默认值: {}", error)
