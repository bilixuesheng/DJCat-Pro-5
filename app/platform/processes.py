"""按可执行文件所在目录查找和强制结束 Windows 进程。

应用市场判断应用是否在运行、卸载和 Application Update 替换文件前关闭应用、Application
Relocation 开始前关闭从 Application Install Location 运行的程序，都用同一个判定：进程的
可执行文件位于该目录下面。别的程序只是开着里面的文件（资源管理器开着文件夹、Word 打开了
里面的文档）不算，也不会被结束。非 Windows 上没有可找的进程，一律当作没有。
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
    return kernel32


def processesUnder(directory: Path) -> list[tuple[int, Path]]:
    """可执行文件位于 directory 下的进程，按 (进程 ID, 可执行文件) 列出，不含本进程。"""
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
        root = Path(directory).resolve(strict=False)
        running = []
        count = bytesNeeded.value // ctypes.sizeof(wintypes.DWORD)
        for processId in processIds[:count]:
            if not processId or processId == os.getpid():
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
                executable = Path(buffer.value).resolve(strict=False)
                try:
                    executable.relative_to(root)
                except ValueError:
                    continue
                running.append((int(processId), executable))
            finally:
                kernel32.CloseHandle(handle)
        return running
    except (AttributeError, OSError, ValueError):
        return []


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
