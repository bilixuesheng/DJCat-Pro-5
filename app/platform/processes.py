"""按可执行文件所在目录查找和强制结束 Windows 进程。

应用市场判断应用是否在运行、卸载和 Application Update 替换文件前关闭应用、Application
Relocation 开始前关闭从 Application Install Location 运行的程序，都用同一个判定：进程的
可执行文件位于该目录下面。别的程序只是开着里面的文件（资源管理器开着文件夹、Word 打开了
里面的文档）不算，也不会被结束。Process Guard 判断被守护的程序在不在运行，看的是当前会话里
有没有进程的可执行文件正是那个文件。非 Windows 上没有可找的进程，一律当作没有。
"""

import os
import time
from pathlib import Path

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


def _processes(sameSession: bool = False) -> list[tuple[int, Path]]:
    """其他进程的 (进程 ID, 可执行文件)；sameSession 为真时只要和本进程同一个登录会话的。"""
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
            return []
        kernel32 = _kernel32()
        session = wintypes.DWORD()
        if sameSession and not kernel32.ProcessIdToSessionId(
            os.getpid(), ctypes.byref(session)
        ):
            return []
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
                found.append((int(processId), Path(buffer.value).resolve(strict=False)))
            finally:
                kernel32.CloseHandle(handle)
        return found
    except (AttributeError, OSError, ValueError):
        return []


def processesUnder(directory: Path) -> list[tuple[int, Path]]:
    """可执行文件位于 directory 下的进程，按 (进程 ID, 可执行文件) 列出，不含本进程。"""
    try:
        root = Path(directory).resolve(strict=False)
    except (OSError, ValueError):
        return []
    running = []
    for processId, executable in _processes():
        try:
            executable.relative_to(root)
        except ValueError:
            continue
        running.append((processId, executable))
    return running


def runningExecutables() -> list[Path]:
    """当前登录会话里其他进程的可执行文件；别的用户（快速切换用户、远程桌面）开着的不算。"""
    return [executable for _processId, executable in _processes(sameSession=True)]


def terminateProcesses(processIds, timeout: float = TERMINATE_TIMEOUT) -> None:
    """强制结束这些进程，并等它们真正退出（最多 timeout 秒），文件句柄随之释放。"""
    if os.name != "nt":
        return
    try:
        kernel32 = _kernel32()
    except (AttributeError, OSError):
        return
    handles = []
    for processId in processIds:
        handle = kernel32.OpenProcess(
            PROCESS_TERMINATE | SYNCHRONIZE, False, int(processId)
        )
        if not handle:
            continue
        kernel32.TerminateProcess(handle, 1)
        handles.append(handle)
    deadline = time.monotonic() + timeout
    for handle in handles:
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        kernel32.WaitForSingleObject(handle, remaining)
        kernel32.CloseHandle(handle)


def terminateProcessesUnder(
    directory: Path, timeout: float = TERMINATE_TIMEOUT
) -> list[Path]:
    """强制结束可执行文件位于 directory 下的所有进程，返回仍没结束的那些可执行文件。"""
    terminateProcesses([pid for pid, _executable in processesUnder(directory)], timeout)
    return [executable for _pid, executable in processesUnder(directory)]
