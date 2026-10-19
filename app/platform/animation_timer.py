from __future__ import annotations

import ctypes
import os
import sys

from loguru import logger


# A zero timer can monopolize the event loop; 1 ms removes the practical frame
# cap without delaying an already overdue animation tick.
UNLOCKED_TIMER_INTERVAL_MS = 1
DEFAULT_TIMER_INTERVAL_MS = 16


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

    # Only the QtCore this process already runs on: Nuitka puts it beside
    # djcat.exe, not where QLibraryInfo points, and loading another copy is never
    # acceptable.
    @staticmethod
    def _loadQtCore():
        if sys.platform == "win32":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
            kernel32.GetModuleHandleW.restype = ctypes.c_void_p
            handle = kernel32.GetModuleHandleW("Qt6Core.dll")
            if not handle:
                raise RuntimeError("进程里没有加载 Qt6Core")
            return ctypes.WinDLL("Qt6Core.dll", handle=handle)

        return ctypes.CDLL("libQt6Core.so.6", mode=os.RTLD_NOLOAD)

    def setInterval(self, interval: int) -> None:
        instance = self._instance()
        if not instance:
            raise RuntimeError("无法创建 QUnifiedTimer")
        self._setTimingInterval(instance, interval)


_animationTimer: _QtAnimationTimer | None = None
_timerUnavailable = False


def setSuperFrameRateEnabled(enabled: bool) -> None:
    """Super Frame Rate Optimization: a 1 ms Animation Tick, or Qt's own 16 ms.

    Off from startup never touches Qt's private symbols. A switch takes effect at
    once, running animations included: Qt restarts its driver on a new interval.
    """
    global _animationTimer, _timerUnavailable

    if _animationTimer is None and (not enabled or _timerUnavailable):
        return
    try:
        if _animationTimer is None:
            _animationTimer = _QtAnimationTimer.create()
        _animationTimer.setInterval(
            UNLOCKED_TIMER_INTERVAL_MS if enabled else DEFAULT_TIMER_INTERVAL_MS
        )
    except (OSError, RuntimeError) as error:
        _animationTimer = None
        _timerUnavailable = True
        logger.warning("无法解除 Qt 动画帧率限制，将使用默认值: {}", error)
