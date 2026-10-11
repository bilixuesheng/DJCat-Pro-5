"""Error Report 的客户端一侧：把用户看到的异常连同调用栈发给服务端。

路径一律换成相对程序目录的写法，用户目录换成 ``~``，机器只带 Machine Identity，不带
日志：归并由服务端按 Error Signature 做，日志每行都带时间，发过去也只会干扰归并。
同一次运行里同一处代码的同一种异常只发一次，计时器反复抛出的错误不会刷屏。
"""

import os
import platform
import re
import sys
import threading
import traceback
from pathlib import PureWindowsPath

import requests
from loguru import logger

from app.config.constants import ERROR_REPORT_API, VERSION
from app.config.paths import APP_DIR

MAX_REPORTS_PER_SESSION = 20
# 与服务端的上限一致；递归错误的调用栈动辄上千帧，不截就超过服务端的请求大小。
MAX_FRAMES = 64
MAX_TRACEBACK_LENGTH = 32_000
MAX_MESSAGE_LENGTH = 2_000

_sentKeys = set()
_lock = threading.Lock()


def isPackaged() -> bool:
    # 只有发出去的程序才上报：源码运行和测试不能往线上服务端灌报错。
    return getattr(sys, "frozen", False) or "__compiled__" in globals()


def _scrubPaths(text: str) -> str:
    """Drop the install location and the Windows user name from ``text``."""
    for root, replacement in ((str(APP_DIR), None), (os.path.expanduser("~"), "~")):
        root = root.rstrip("\\/")
        if len(root) < 3:
            continue
        # 异常消息里的路径常是 repr 出来的双反斜杠，Qt 给的路径用正斜杠。
        for separator in ("\\\\", "\\", "/"):
            prefix = re.escape(root.replace("\\", separator).replace("/", separator))
            if replacement is None:
                text = re.sub(prefix + re.escape(separator), "", text, flags=re.IGNORECASE)
            else:
                # 只换整段目录名：用户目录 C:\Users\stu 不能吃掉 C:\Users\student 的前半截。
                text = re.sub(
                    prefix + r"(?![^\\/'\"\s])", replacement, text, flags=re.IGNORECASE
                )
    return text


def frameFile(filename: str) -> str:
    """Where a frame's code lives, without saying where DJCat or Python is installed."""
    path = filename.replace("\\", "/")
    appDir = str(APP_DIR).replace("\\", "/").rstrip("/") + "/"
    if path.lower().startswith(appDir.lower()):
        return path[len(appDir):]
    _, marker, inside = path.rpartition("site-packages/")
    if marker:
        return inside
    if path.startswith("/") or PureWindowsPath(filename).drive:
        return path.rsplit("/", 1)[-1]
    return path


def _exceptionType(excType) -> str:
    module = getattr(excType, "__module__", "") or ""
    name = getattr(excType, "__qualname__", None) or getattr(excType, "__name__", "Exception")
    return name if module in ("builtins", "__main__") else f"{module}.{name}"


def _message(excValue) -> str:
    try:
        return str(excValue)
    except Exception:
        return repr(excValue)


def buildReport(excType, excValue, excTraceback, machineId: str) -> dict:
    frames = [
        {"file": frameFile(frame.filename), "function": frame.name, "line": frame.lineno or 0}
        for frame in traceback.extract_tb(excTraceback)[-MAX_FRAMES:]
    ]
    text = "".join(traceback.format_exception(excType, excValue, excTraceback))
    return {
        "machine_id": machineId,
        "client_version": VERSION,
        "os": platform.platform(),
        "exception_type": _exceptionType(excType),
        "message": _scrubPaths(_message(excValue))[:MAX_MESSAGE_LENGTH],
        "frames": frames,
        # 回溯最后几行是异常本身，太长时留尾部。
        "traceback": _scrubPaths(text).rstrip()[-MAX_TRACEBACK_LENGTH:],
    }


def _sessionKey(report: dict) -> tuple:
    return (
        report["exception_type"],
        tuple((frame["file"], frame["function"], frame["line"]) for frame in report["frames"]),
    )


def _send(report: dict) -> None:
    response = None
    try:
        # 不跟随跳转：requests 会把跳转后的 POST 改成 GET，报错就丢了。
        response = requests.post(
            ERROR_REPORT_API, json=report, timeout=10, allow_redirects=False
        )
        if response.status_code != 200:
            logger.warning("报错上报被服务端拒绝：HTTP {}", response.status_code)
    except requests.RequestException as error:
        logger.warning("报错上报失败：{}", error)
    finally:
        if response is not None:
            response.close()


def reportError(excType, excValue, excTraceback) -> bool:
    """Send this exception to the server in the background; False when it is skipped."""
    if not isPackaged() or issubclass(excType, (KeyboardInterrupt, SystemExit)):
        return False
    from app.common.ai_markdown import machineId

    report = buildReport(excType, excValue, excTraceback, machineId())
    key = _sessionKey(report)
    with _lock:
        if key in _sentKeys or len(_sentKeys) >= MAX_REPORTS_PER_SESSION:
            return False
        _sentKeys.add(key)
    threading.Thread(target=_send, args=(report,), name="ErrorReport", daemon=True).start()
    return True
