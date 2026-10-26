"""换当前用户的 Windows 桌面壁纸。"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDWININICHANGE = 0x02


def setDesktopWallpaper(path: str) -> str | None:
    """换成这张图，所有屏幕同一张，契合度沿用 Windows 当前设置；失败时返回原因。

    Windows 要转码图片并向所有窗口广播设置变化，可能要一会儿，只在后台线程里调用。
    壁纸被组策略锁定时 Windows 照样回答成功，这里看不出来。
    """
    if os.name != "nt":
        return "只有 Windows 能更换桌面壁纸"
    prototype = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.LPCWSTR,
        wintypes.UINT,
        use_last_error=True,
    )
    systemParametersInfo = prototype(
        ("SystemParametersInfoW", ctypes.WinDLL("user32", use_last_error=True))
    )
    if systemParametersInfo(
        SPI_SETDESKWALLPAPER,
        0,
        os.path.abspath(path),
        SPIF_UPDATEINIFILE | SPIF_SENDWININICHANGE,
    ):
        return None
    code = ctypes.get_last_error()
    reason = ctypes.FormatError(code).strip() if code else "未知错误"
    return f"Windows 没能换上壁纸：{reason}"
