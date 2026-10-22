"""以管理员身份启动程序：ShellExecuteEx 的 runas，会弹 UAC。

电教猫以普通权限运行。CreateProcess（`subprocess.Popen`）遇到清单要求管理员权限的程序直接
返回错误 740，不弹 UAC；资源管理器里双击走的是 ShellExecute，由它读清单、弹 UAC。
"""

import os
import subprocess
from functools import cache

ERROR_ELEVATION_REQUIRED = 740
ERROR_CANCELLED = 1223
_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SEE_MASK_NO_CONSOLE = 0x00008000
_SW_HIDE = 0
_SW_SHOWNORMAL = 1
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 0x102
_INFINITE = 0xFFFFFFFF


@cache
def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetProcessId.argtypes = (wintypes.HANDLE,)
    kernel32.GetProcessId.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


class ElevatedProcess:
    """以管理员身份运行的进程，提供 Application Launch 用到的那部分 `Popen` 接口。

    普通权限按进程 ID 打不开管理员进程，查询、等待和结束都只能靠 ShellExecuteEx 给的句柄。
    """

    def __init__(self, handle: int, args: list[str]):
        self._handle = handle
        self.args = args
        self.pid = int(_kernel32().GetProcessId(handle))
        self.returncode = None

    def poll(self) -> int | None:
        if (
            self.returncode is None
            and _kernel32().WaitForSingleObject(self._handle, 0) == _WAIT_OBJECT_0
        ):
            self._readExitCode()
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            milliseconds = _INFINITE if timeout is None else int(timeout * 1000)
            result = _kernel32().WaitForSingleObject(self._handle, milliseconds)
            if result == _WAIT_TIMEOUT:
                raise subprocess.TimeoutExpired(self.args, timeout)
            if result != _WAIT_OBJECT_0:
                import ctypes

                raise ctypes.WinError(ctypes.get_last_error())
            self._readExitCode()
        return self.returncode

    def kill(self) -> None:
        if self.poll() is None and not _kernel32().TerminateProcess(self._handle, 1):
            import ctypes

            raise ctypes.WinError(ctypes.get_last_error())

    def _readExitCode(self) -> None:
        import ctypes
        from ctypes import wintypes

        exitCode = wintypes.DWORD()
        # 进程已经结束，只是读不出退出码时按失败算。
        read = _kernel32().GetExitCodeProcess(self._handle, ctypes.byref(exitCode))
        self.returncode = exitCode.value if read else -1

    def __del__(self):
        handle, self._handle = getattr(self, "_handle", None), None
        if handle:
            _kernel32().CloseHandle(handle)


def startElevated(
    args: list[str],
    cwd=None,
    window: int | None = None,
    hidden: bool = False,
) -> ElevatedProcess | None:
    """弹 UAC 以管理员身份启动 args；UAC 里点「否」返回 None，其他失败抛 OSError。

    一直等到 UAC 有了答复才返回，只能在后台线程里调用。
    """
    if os.name != "nt":
        raise OSError("只有 Windows 能以管理员身份启动程序")
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(ShellExecuteInfo)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | (_SEE_MASK_NO_CONSOLE if hidden else 0)
    info.hwnd = window or None
    info.lpVerb = "runas"
    info.lpFile = str(args[0])
    info.lpParameters = subprocess.list2cmdline(args[1:])
    info.lpDirectory = str(cwd) if cwd else None
    info.nShow = _SW_HIDE if hidden else _SW_SHOWNORMAL

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(ShellExecuteInfo),)
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    ole32 = ctypes.windll.ole32
    # ShellExecuteEx 可能经由 COM 处理，在后台线程里调用前先初始化。
    initialized = ole32.CoInitializeEx(None, 0x2 | 0x4) >= 0
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            error = ctypes.get_last_error()
            if error == ERROR_CANCELLED:
                return None
            raise ctypes.WinError(error)
    finally:
        if initialized:
            ole32.CoUninitialize()
    if not info.hProcess:
        raise OSError("没有取得进程句柄")
    return ElevatedProcess(info.hProcess, [str(arg) for arg in args])
