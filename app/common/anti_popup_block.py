"""反弹窗拦截的规则：伪装产品名的取值、随机换名、启动自检与提示显隐。

见 docs/adr/0014-anti-window-close-productname-disguise.md。本模块不碰 Qt，也不
负责真正改写 exe——写入由 updater.exe 的 ``--stamp-product-name`` 模式在电教猫退出后
完成（运行中的 exe 被锁、改不了），这里只决定"该不该改、改成什么"，以及只读地读出
磁盘上当前的产品名供启动自检比对。
"""

from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

from app.config.constants import APP_NAME

# 关闭开关时写回的诚实产品名；构建期 Nuitka 也是用它(APP_NAME)写进版本资源的。
HONEST_PRODUCT_NAME = APP_NAME
# 首次打开开关时的默认伪装名，也是用户实测可行的那个。
DEFAULT_DISGUISED_NAME = "DJCat Pro"

# 像正常软件名的英文词，拼出来再加一位数字（游戏随机 ID 式）。
# 不用随机十六进制：一串乱码产品名在文件属性里反而显眼、更招杀毒怀疑。
_FIRST_WORDS = (
    "Smart", "Daily", "Bright", "Campus", "Classroom", "Easy", "Quick",
    "Prime", "Clear", "Focus", "Active", "Simple", "Open", "Study", "Neat",
)
_SECOND_WORDS = (
    "Class", "Teach", "Board", "Desk", "Study", "Learn", "Lesson", "Screen",
    "Note", "Slate",
)
_THIRD_WORDS = (
    "Helper", "Assistant", "Tool", "Box", "Hub", "Mate", "Pro", "Kit", "Suite",
)


def randomDisguisedName(exclude: str = "") -> str:
    """两三段英文词拼接 + 末尾 2–9 的数字；避开诚实名和 ``exclude``（当前名）。"""
    excluded = {HONEST_PRODUCT_NAME}
    if exclude:
        excluded.add(exclude)
    name = DEFAULT_DISGUISED_NAME
    for _ in range(100):
        parts = [random.choice(_FIRST_WORDS), random.choice(_SECOND_WORDS)]
        if random.random() < 0.5:
            parts.append(random.choice(_THIRD_WORDS))
        name = "".join(parts) + f" {random.randint(2, 9)}"
        if name not in excluded:
            return name
    return name


def desiredProductName(enabled: bool, disguisedName: str) -> str:
    """开着就是伪装名，关着就是诚实名——启动自检和落地都以它为准。"""
    name = (disguisedName or DEFAULT_DISGUISED_NAME).strip()
    return name if enabled else HONEST_PRODUCT_NAME


def needsReapply(enabled: bool, disguisedName: str, currentName: str | None) -> bool:
    """磁盘上的产品名与目标不一致时为真（多半是被 Client Update 还原了）。

    读不到（``None``）时不触发：宁可这次不改，也不要因为读不出而反复退出重启。
    """
    if currentName is None:
        return False
    return currentName != desiredProductName(enabled, disguisedName)


def tipShouldShow(
    enabled: bool, permanentlyDismissed: bool, sessionDismissed: bool
) -> bool:
    """反拦截提示：开着绝不显示；否则没永久关、本次也没关过才显示。"""
    if enabled:
        return False
    return not permanentlyDismissed and not sessionDismissed


def currentExePath() -> Path:
    return Path(sys.executable).resolve()


def exeProductName(path: "Path | None" = None) -> "str | None":
    """只读地读出 exe 版本资源里的 ProductName；非 Windows 或读不到返回 ``None``。

    只读文件、不加写锁，所以运行中也能读自己。失败一律吞成 ``None``，由
    :func:`needsReapply` 决定"读不到就不动"。
    """
    if sys.platform != "win32":
        return None
    exe = str(path or currentExePath())
    try:
        import ctypes
        from ctypes import wintypes

        version = ctypes.WinDLL("version")
        handle = wintypes.DWORD(0)
        size = version.GetFileVersionInfoSizeW(exe, ctypes.byref(handle))
        if not size:
            return None
        buffer = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(exe, 0, size, buffer):
            return None

        # 先取翻译（语言 + 代码页），再按它拼出 ProductName 的子块路径。
        pointer = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(
            buffer, "\\VarFileInfo\\Translation",
            ctypes.byref(pointer), ctypes.byref(length),
        ) or not length.value:
            return None
        lang, codepage = struct.unpack("<HH", ctypes.string_at(pointer.value, 4))

        sub = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\ProductName"
        value = ctypes.c_wchar_p()
        count = wintypes.UINT()
        if not version.VerQueryValueW(
            buffer, sub, ctypes.byref(value), ctypes.byref(count)
        ) or not count.value:
            return None
        return value.value
    except Exception:  # noqa: BLE001 - 读不到就当没有，绝不因此崩溃
        return None
