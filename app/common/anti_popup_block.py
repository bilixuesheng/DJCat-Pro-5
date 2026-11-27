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
from datetime import date
from pathlib import Path

from app.config.constants import APP_NAME

# 关闭开关时写回的诚实产品名；构建期 Nuitka 也是用它(APP_NAME)写进版本资源的。
HONEST_PRODUCT_NAME = APP_NAME
# 首次打开开关时的默认伪装名，也是用户实测可行的那个。
DEFAULT_DISGUISED_NAME = "DJCat Pro"

# 管理模式：自动管理按轮换间隔换随机名，手动管理只随用户手动换名。
MODE_AUTO = "auto"
MODE_MANUAL = "manual"
# 轮换间隔天数的下限与默认（上限只约束界面数值框，逻辑里不设上限）。
MIN_ROTATE_DAYS = 1
DEFAULT_ROTATE_DAYS = 3

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


def normalizeCustomName(text: str) -> "str | None":
    """手动自定义名的最低校验：去首尾空白后非空、且不等于诚实名。

    用户选了"最低校验"，这里不限长度、不限字符、也不拦中文——填一个仍会被按名
    命中的名字是用户自担的选择。不合格（空、或就是「电教猫 Pro 5」）返回 ``None``，
    由调用方据此不触发重启。
    """
    name = (text or "").strip()
    if not name or name == HONEST_PRODUCT_NAME:
        return None
    return name


def _parseIsoDate(text: str) -> "date | None":
    if not text:
        return None
    try:
        return date.fromisoformat(str(text).strip()[:10])
    except ValueError:
        return None


def startupRotationPlan(
    enabled: bool,
    mode: str,
    rotateDays: int,
    rotatedOn: str,
    today: date,
) -> "tuple[bool, date | None]":
    """自动管理在启动时的轮换决定。

    返回 ``(shouldRotate, baselineToSet)``：

    - ``shouldRotate`` 为真：调用方生成随机名、改产品名，并把「上次换名日期」存成
      ``baselineToSet``（即 ``today``），再走退出重启。**先落定基线再重启**，这样即使
      改名失败，下次启动也不会因为同一到点而反复重启成环。
    - ``shouldRotate`` 为假而 ``baselineToSet`` 非 ``None``：只建立基线、不换名——用于
      旧配置或首次没有基线的情况，免得升级后立刻轮换一次。
    - 两者都为假 / ``None``：什么都不做。

    关掉开关或处于手动管理时永不轮换。基线落在未来（主板电池没电、时钟被重置）时
    当作时钟出错，立即换并重设基线；错过多个周期也只换一次。与 ``interval_tasks`` 同形。
    """
    if not enabled or mode != MODE_AUTO:
        return (False, None)
    baseline = _parseIsoDate(rotatedOn)
    if baseline is None:
        return (False, today)
    if baseline > today:
        return (True, today)
    interval = max(MIN_ROTATE_DAYS, int(rotateDays))
    if (today - baseline).days >= interval:
        return (True, today)
    return (False, None)


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
