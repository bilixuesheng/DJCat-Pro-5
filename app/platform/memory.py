import sys


def emptyWorkingSet() -> bool:
    if sys.platform != "win32":
        return False

    from ctypes import WinDLL, wintypes

    kernel32 = WinDLL("kernel32", use_last_error=True)
    psapi = WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL
    return bool(psapi.EmptyWorkingSet(kernel32.GetCurrentProcess()))
