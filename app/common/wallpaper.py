"""Wallpaper Task：固定或按 Wallpaper Rotation 轮换地换 Windows 桌面壁纸。

列表只记图片路径，不复制图片；找不到的图跳过但留在列表里。Current Wallpaper 记在
`cfg.homeCardTaskState`，跟着图片走而不跟着列表位置。理由见 docs/adr/0013-interval-and-wallpaper-tasks.md。
"""

from __future__ import annotations

import os
import re
import stat
import threading

from PySide6.QtCore import QObject, Signal

from app.common.home_card_tasks import FIXED_WALLPAPER, wallpaperKey
from app.common.home_cards import WALLPAPER_IMAGE_SUFFIXES
from app.platform.wallpaper import setDesktopWallpaper

WALLPAPER_FILE_FILTER = "图片 (*.jpg *.jpeg *.png *.bmp)"
_HIDDEN_ATTRIBUTES = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2) | getattr(
    stat, "FILE_ATTRIBUTE_SYSTEM", 0x4
)


def isWallpaperImage(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in WALLPAPER_IMAGE_SUFFIXES


def wallpaperFileExists(path: str) -> bool:
    return bool(path) and os.path.isfile(os.path.expandvars(path))


def nextRotationWallpaper(
    rotation: list[str],
    current: str = "",
    successor: str = "",
    exists=wallpaperFileExists,
) -> str | None:
    """这次轮到哪张：Current Wallpaper 之后下一张找得到的图，最后一张之后回到第一张。

    Current Wallpaper 已经不在列表里时，从 `successor` 开始（删掉它时原来排在它后面的那张）；
    两个都不在就从第一张开始。一张都找不到时是 None。
    """
    if not rotation:
        return None
    keys = [wallpaperKey(path) for path in rotation]
    if current and wallpaperKey(current) in keys:
        start = keys.index(wallpaperKey(current)) + 1
    elif successor and wallpaperKey(successor) in keys:
        start = keys.index(wallpaperKey(successor))
    else:
        start = 0
    for offset in range(len(rotation)):
        path = rotation[(start + offset) % len(rotation)]
        if exists(path):
            return path
    return None


def _naturalKey(text: str) -> list:
    # 按段比较，数字段按数值：「2.jpg」排在「10.jpg」前面。
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", text)
    ]


def _isHidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith("."):
        return True
    try:
        attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return True
    return bool(attributes & _HIDDEN_ATTRIBUTES)


def scanWallpaperFolder(folder: str, canceled=lambda: False) -> list[str]:
    """文件夹里（含各层子文件夹）能设为壁纸的图片，按相对路径自然排序。

    跳过隐藏和系统文件夹与文件，不跟随符号链接和目录联接。
    """
    found = []
    pending = [(folder, ())]
    while pending and not canceled():
        directory, relative = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            if _isHidden(entry):
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not entry.is_junction():
                        pending.append((entry.path, (*relative, entry.name)))
                elif entry.is_file(follow_symlinks=False) and isWallpaperImage(entry.name):
                    found.append(((*relative, entry.name), entry.path))
            except OSError:
                continue
    found.sort(key=lambda item: [_naturalKey(part) for part in item[0]])
    return [path for _relative, path in found]


class WallpaperWorker(QObject):
    """在后台线程里执行一次 Wallpaper Task。

    `applied` 在轮换换上一张后发出，MainWindow 据此改写 Current Wallpaper；`finished` 的接口与
    ActionSequenceWorker 相同，自动任务的运行、退出等待和报错共用一套。
    """

    applied = Signal(str, str)
    finished = Signal(str, object)

    def __init__(self, task: dict, state: dict, parent=None):
        super().__init__(parent)
        self.taskId = task["id"]
        self._wallpaper = task["wallpaper"]
        self._current = state.get("wallpaper", "")
        self._successor = state.get("wallpaperNext", "")
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        # 换壁纸只有一次系统调用，开始了就等它做完。
        pass

    def wait(self, timeout=None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            errors = self._apply()
        except Exception as error:
            errors = [str(error)]
        try:
            self.finished.emit(self.taskId, errors)
        except RuntimeError:
            pass

    def _apply(self) -> list[str]:
        if self._wallpaper["mode"] == FIXED_WALLPAPER:
            path = self._wallpaper["fixed"]
            if not path:
                return ["没有选择壁纸图片"]
            if not wallpaperFileExists(path):
                return [f"找不到壁纸图片 {path}"]
            error = setDesktopWallpaper(os.path.expandvars(path))
            return [error] if error else []

        rotation = self._wallpaper["rotation"]
        if not rotation:
            return ["轮换列表里没有图片"]
        path = nextRotationWallpaper(rotation, self._current, self._successor)
        if path is None:
            return ["轮换列表里的图片都找不到了"]
        error = setDesktopWallpaper(os.path.expandvars(path))
        if error:
            return [error]
        try:
            self.applied.emit(self.taskId, path)
        except RuntimeError:
            pass
        return []
