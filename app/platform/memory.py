"""把电教猫暂时用不到的内存页交还给 Windows，并在日志里记下修剪前后的占用。

`EmptyWorkingSet` 只是把常驻内存里的页换出去：任务管理器"内存"一栏会大幅下降，提交的内存
（private bytes）不变，之后碰到哪页再把哪页调回来。所以只在主窗口藏在托盘里一阵子之后做一次，
不定时反复做。教室机上到底省了多少，只能看这里记的那一行日志。非 Windows 上什么都不做。
"""

import ctypes
import os
from ctypes import wintypes

from loguru import logger

_MEGABYTE = 1024 * 1024


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _processApi():
    """(本进程句柄, psapi)。"""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessMemoryCountersEx),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    psapi.EmptyWorkingSet.argtypes = (wintypes.HANDLE,)
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    return kernel32.GetCurrentProcess(), psapi


def _memoryCounters() -> tuple[int, int]:
    """本进程的 (工作集, private bytes)，单位字节。"""
    process, psapi = _processApi()
    counters = _ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize, counters.PrivateUsage


def _emptyWorkingSet() -> None:
    process, psapi = _processApi()
    if not psapi.EmptyWorkingSet(process):
        raise ctypes.WinError(ctypes.get_last_error())


def trimWorkingSet() -> None:
    if os.name != "nt":
        return
    try:
        before, _ = _memoryCounters()
        _emptyWorkingSet()
        after, private = _memoryCounters()
    except OSError:
        logger.exception("修剪内存失败")
        return
    logger.info(
        "修剪内存：工作集 {}→{} MB，private {} MB",
        before // _MEGABYTE,
        after // _MEGABYTE,
        private // _MEGABYTE,
    )
