"""Process Guard：电教猫运行期间，被守护的程序一不在就把它拉起来。

规则都在这里，MainWindow 只负责把配置交进来、在退出和关机时叫停、把停止原因显示出来。
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, QProcess, Signal

from app.common.home_card_tasks import PROCESS_GUARD_TRIGGER, normalizeHomeCardTasks
from app.common.install_location import applicationsBlocked, installLocation
from app.common.process_environment import externalProcessEnvironment
from app.platform.processes import runningExecutables

CHECK_INTERVAL = 3
# 开机静默启动时被守护的程序可能也在自启：教室电脑多是机械硬盘，自启慢，10 秒级不够。
STARTUP_HOLD_SECONDS = 60
# 只看到一次空缺不算：程序自我重启（自更新、换账号）时旧进程退出到新进程出现之间有几秒空档。
CONFIRM_CHECKS = 2
# 拉起后撑不过这么久就没了，算一次反复退出；连续这么多次就放弃：崩溃循环，或者选中的是拉起主程序就退出的启动器。
QUICK_EXIT_SECONDS = 30
QUICK_EXIT_LIMIT = 6

REPEATED_EXIT = "反复退出"
MISSING_PROGRAM = "文件不存在"
NEEDS_ELEVATION = "需要管理员权限"
LAUNCH_FAILED = "无法启动"
ERROR_ELEVATION_REQUIRED = 740


def _key(path) -> str:
    return os.path.normcase(str(Path(os.path.expandvars(str(path))).resolve(strict=False)))


def stopLabel(reason: str) -> str:
    """停止原因的简称，卡片摘要用；Windows 给的报错原文只在提示里出现。"""
    return reason if reason in (REPEATED_EXIT, MISSING_PROGRAM, NEEDS_ELEVATION) else LAUNCH_FAILED


def stopMessage(reason: str) -> str:
    """停止守护时提示里的说明。"""
    if reason == REPEATED_EXIT:
        return "程序打开后反复退出，已停止守护。选中的可能是启动器，请改选它打开的主程序。"
    if reason == MISSING_PROGRAM:
        return "程序文件不存在，已停止守护。"
    if reason == NEEDS_ELEVATION:
        return "程序需要管理员权限，电教猫无法打开它，已停止守护。"
    return f"无法打开程序（{reason}），已停止守护。"


def isSameProgram(first, second) -> bool:
    """两个路径是不是同一个程序：展开环境变量后按完整路径比较，不分大小写。"""
    return _key(first) == _key(second)


def guardRules(tasks) -> list[dict]:
    """Home Card Task 列表里选了程序的 Process Guard，不论是否启用。"""
    return [
        task
        for task in normalizeHomeCardTasks(tasks)
        if task["trigger"] == PROCESS_GUARD_TRIGGER and task["program"]["target"]
    ]


def launchProgram(program: dict) -> str | None:
    """启动被守护的程序，失败时返回原因。

    电教猫以普通权限运行，CreateProcess 遇到要求管理员权限的程序直接拒绝（错误 740），
    不弹 UAC：讲台上一遍遍弹 UAC，学生点"否"照样失败。
    """
    target = os.path.expandvars(program["target"])
    if not Path(target).is_file():
        return MISSING_PROGRAM
    workingDir = os.path.expandvars(program.get("working_dir", "")) or None
    try:
        subprocess.Popen(
            [target, *QProcess.splitCommand(program.get("arguments", ""))],
            cwd=workingDir,
            env=externalProcessEnvironment(globals().get("__compiled__")),
        )
    except OSError as error:
        if getattr(error, "winerror", None) == ERROR_ELEVATION_REQUIRED:
            return NEEDS_ELEVATION
        return str(error)
    except ValueError as error:
        return str(error)
    return None


def _within(key: str, directory) -> bool:
    root = _key(directory).rstrip(os.sep)
    return key == root or key.startswith(root + os.sep)


def guardedUnder(directory, tasks, enabled: bool) -> bool:
    """启用中的 Process Guard 里有没有守护 directory 下面的程序。"""
    return enabled and any(
        task["enabled"] and _within(_key(task["program"]["target"]), directory)
        for task in guardRules(tasks)
    )


def _relocating(key: str) -> bool:
    """Application Relocation 跨盘复制可能要好几分钟，这期间从旧位置拉起会占住文件、让迁移失败。

    卸载和 Application Update 不用另外避让：它们强制关闭程序后几毫秒内就换掉目录，
    而守护要隔一次检查再确认一遍才拉起。
    """
    return applicationsBlocked() and _within(key, installLocation())


@dataclass
class _Guarded:
    program: dict
    key: str
    misses: int = 0
    firstMissAt: float = 0.0
    launchedAt: float | None = None
    quickExits: int = 0
    stoppedReason: str = ""


class ProcessGuard(QObject):
    stopped = Signal(str, str)

    def __init__(
        self,
        parent=None,
        runningPrograms=runningExecutables,
        launch=launchProgram,
        clock=time.monotonic,
    ):
        super().__init__(parent)
        self._runningPrograms = runningPrograms
        self._launch = launch
        self._clock = clock
        self._lock = threading.Lock()
        self._guarded: dict[str, _Guarded] = {}
        self._holdUntil = float("-inf")
        self._halted = threading.Event()
        self._thread = None

    def setRules(self, tasks, enabled: bool) -> None:
        """按 Home Card Task 列表和自动任务总开关换上要守护的规则。

        没变的规则保留检查进度和停止状态；新出现的（刚启用、刚打开总开关、换了程序）从头开始。
        同一个程序只守护列表里的第一条。
        """
        rules = []
        if enabled:
            keys = set()
            for task in guardRules(tasks):
                if not task["enabled"]:
                    continue
                program = task["program"]
                key = _key(program["target"])
                if key not in keys:
                    keys.add(key)
                    rules.append((task["id"], program, key))
        with self._lock:
            if self._halted.is_set():
                return
            previous = self._guarded
            self._guarded = {
                taskId: (
                    previous[taskId]
                    if taskId in previous and previous[taskId].program == program
                    else _Guarded(program, key)
                )
                for taskId, program, key in rules
            }

    def holdLaunches(self, seconds: float) -> None:
        """接下来 seconds 秒只检查不拉起，期间程序自己起来了就什么都不做。"""
        self._holdUntil = self._clock() + seconds

    def start(self) -> None:
        """在后台线程里检查：枚举进程和启动程序都可能卡住界面。"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        """不再守护任何程序：从托盘退出、Windows 关机或注销、定时关机执行时调用，之后不能再开始。"""
        with self._lock:
            self._halted.set()
            self._guarded = {}

    def _run(self) -> None:
        while not self._halted.is_set():
            try:
                self.tick()
            except Exception:
                logger.exception("进程守护检查失败")
            self._halted.wait(CHECK_INTERVAL)

    def stoppedReasons(self) -> dict[str, str]:
        """本次运行内已经停止守护的规则：任务 ID → 原因。"""
        with self._lock:
            return {
                taskId: state.stoppedReason
                for taskId, state in self._guarded.items()
                if state.stoppedReason
            }

    def tick(self) -> None:
        with self._lock:
            guarded = [
                (taskId, state)
                for taskId, state in self._guarded.items()
                if not state.stoppedReason
            ]
        if not guarded:
            return
        running = {_key(path) for path in self._runningPrograms()}
        now = self._clock()
        for taskId, state in guarded:
            if state.key in running:
                state.misses = 0
                if (
                    state.launchedAt is not None
                    and now - state.launchedAt >= QUICK_EXIT_SECONDS
                ):
                    state.launchedAt = None
                    state.quickExits = 0
                continue
            state.misses += 1
            if state.misses == 1:
                state.firstMissAt = now
            if state.misses < CONFIRM_CHECKS:
                continue
            if state.launchedAt is not None:
                quick = state.firstMissAt - state.launchedAt < QUICK_EXIT_SECONDS
                state.quickExits = state.quickExits + 1 if quick else 0
                state.launchedAt = None
                if state.quickExits >= QUICK_EXIT_LIMIT:
                    self._stop(taskId, state, REPEATED_EXIT)
                    continue
            if now < self._holdUntil or _relocating(state.key):
                continue
            with self._lock:
                if self._guarded.get(taskId) is not state:
                    continue
            logger.info("进程守护拉起 {}", state.program["target"])
            error = self._launch(dict(state.program))
            if error:
                self._stop(taskId, state, error)
                continue
            state.launchedAt = now
            state.misses = 0

    def _stop(self, taskId: str, state: _Guarded, reason: str) -> None:
        with self._lock:
            # 检查途中规则被关掉或换了程序，就不再替旧规则报停止。
            if self._guarded.get(taskId) is not state:
                return
            state.stoppedReason = reason
        logger.warning("进程守护停止 {}：{}", state.program["target"], reason)
        try:
            self.stopped.emit(taskId, reason)
        except RuntimeError:
            # MainWindow 退出时可能已经销毁了它，后台线程还在收尾。
            pass
