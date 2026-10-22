"""按可执行文件所在目录查找和强制结束 Windows 进程。

应用市场判断应用是否在运行、卸载和 Application Update 替换文件前关闭应用、Application
Relocation 开始前关闭从 Application Install Location 运行的程序，都用同一个判定：进程的
可执行文件位于该目录下面。别的程序只是开着里面的文件（资源管理器开着文件夹、Word 打开了
里面的文档）不算，也不会被结束。Process Guard 判断被守护的程序在不在运行，看的是当前会话里
有没有进程的可执行文件正是那个文件。电教猫以普通权限运行，结束不了以管理员身份运行的程序，
结束后还在的进程会标出是不是这个原因。非 Windows 上没有可找的进程，一律当作没有。
"""

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

ERROR_ACCESS_DENIED = 5
PROCESS_TERMINATE = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SYNCHRONIZE = 0x00100000
TERMINATE_TIMEOUT = 5.0


def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.ProcessIdToSessionId.argtypes = (
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    return kernel32


@lru_cache(maxsize=1024)
def _resolvedImage(path: str) -> Path:
    # Process Guard 每 3 秒列一遍进程，resolve() 要逐个打开文件；同一个可执行文件只解析一次。
    return Path(path).resolve(strict=False)


def _processes(sameSession: bool = False) -> list[tuple[int, Path]] | None:
    """其他进程的 (进程 ID, 可执行文件)；sameSession 为真时只要和本进程同一个登录会话的。

    列不出来时返回 None，与"一个都没有"区分开。
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        processIds = (wintypes.DWORD * 4096)()
        bytesNeeded = wintypes.DWORD()
        if not ctypes.windll.psapi.EnumProcesses(
            processIds, ctypes.sizeof(processIds), ctypes.byref(bytesNeeded)
        ):
            return None
        kernel32 = _kernel32()
        session = wintypes.DWORD()
        if sameSession and not kernel32.ProcessIdToSessionId(
            os.getpid(), ctypes.byref(session)
        ):
            return None
        found = []
        count = bytesNeeded.value // ctypes.sizeof(wintypes.DWORD)
        for processId in processIds[:count]:
            if not processId or processId == os.getpid():
                continue
            # ProcessIdToSessionId 要 PROCESS_QUERY_INFORMATION，普通权限拿不到提权进程的，
            # 读不出会话就当同一个会话：别的用户的进程连下面的有限查询都打不开。
            processSession = wintypes.DWORD()
            if (
                sameSession
                and kernel32.ProcessIdToSessionId(processId, ctypes.byref(processSession))
                and processSession.value != session.value
            ):
                continue
            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, processId
            )
            if not handle:
                continue
            try:
                length = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(length.value)
                if not kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(length)
                ):
                    continue
                found.append((int(processId), _resolvedImage(buffer.value)))
            finally:
                kernel32.CloseHandle(handle)
        return found
    except (AttributeError, OSError, ValueError):
        return None


def processesUnder(directory: Path) -> list[tuple[int, Path]]:
    """可执行文件位于 directory 下的进程，按 (进程 ID, 可执行文件) 列出，不含本进程。"""
    processes = _processes()
    if not processes:
        return []
    try:
        root = Path(directory).resolve(strict=False)
    except (OSError, ValueError):
        return []
    running = []
    for processId, executable in processes:
        try:
            executable.relative_to(root)
        except ValueError:
            continue
        running.append((processId, executable))
    return running


def runningExecutables() -> list[Path] | None:
    """当前登录会话里其他进程的可执行文件（已 resolve）；别的用户（快速切换用户、远程桌面）
    开着的不算。列不出来时返回 None。"""
    processes = _processes(sameSession=True)
    if processes is None:
        return None
    return [executable for _processId, executable in processes]


class Survivor(NamedTuple):
    """强制结束后仍在运行的进程。elevated 为真时是普通权限打不开它：它以管理员身份运行。"""

    executable: Path
    elevated: bool


def terminateProcesses(processIds, timeout: float = TERMINATE_TIMEOUT) -> set[int]:
    """强制结束这些进程，并等它们真正退出（最多 timeout 秒），文件句柄随之释放。

    返回因为权限不够打不开的进程 ID：普通权限的电教猫结束不了以管理员身份运行的程序。
    """
    if os.name != "nt":
        return set()
    try:
        import ctypes

        kernel32 = _kernel32()
    except (AttributeError, OSError):
        return set()
    handles = []
    denied = set()
    for processId in processIds:
        handle = kernel32.OpenProcess(
            PROCESS_TERMINATE | SYNCHRONIZE, False, int(processId)
        )
        if not handle:
            if ctypes.get_last_error() == ERROR_ACCESS_DENIED:
                denied.add(int(processId))
            continue
        kernel32.TerminateProcess(handle, 1)
        handles.append(handle)
    deadline = time.monotonic() + timeout
    for handle in handles:
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        kernel32.WaitForSingleObject(handle, remaining)
        kernel32.CloseHandle(handle)
    return denied


def terminateProcessesUnder(
    directory: Path, timeout: float = TERMINATE_TIMEOUT
) -> list[Survivor]:
    """强制结束可执行文件位于 directory 下的所有进程，返回仍没结束的那些。"""
    denied = terminateProcesses(
        [pid for pid, _executable in processesUnder(directory)], timeout
    )
    return [
        Survivor(executable, pid in denied)
        for pid, executable in processesUnder(directory)
    ]
