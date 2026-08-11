from __future__ import annotations

import copy
import ctypes
import os
import subprocess
import threading
import uuid
import webbrowser
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QProcess, QSize, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from qfluentwidgets import FluentIcon as FIF

from app.config.paths import HOME_CARD_ICON_DIR


DEFAULT_HOME_CARD_NAMES = ("全屏投送", "考试倒计时", "定时关机", "定时播报")
ACTION_TYPES = ("program", "shell", "url", "path", "delay")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class HomeCardError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex


def _text(value, default="") -> str:
    return str(value).strip() if value is not None else default


def normalize_action(value: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    action_type = _text(value.get("type")).lower()
    if action_type not in ACTION_TYPES:
        return None
    action = {"id": _text(value.get("id")) or new_id(), "type": action_type}
    if action_type == "program":
        action.update(
            {
                "target": _text(value.get("target")),
                "arguments": _text(value.get("arguments")),
                "working_dir": _text(value.get("working_dir")),
                "wait": bool(value.get("wait", False)),
            }
        )
    elif action_type == "shell":
        action.update(
            {
                "command": _text(value.get("command")),
                "working_dir": _text(value.get("working_dir")),
                "wait": bool(value.get("wait", False)),
                "show_console": bool(value.get("show_console", False)),
            }
        )
    elif action_type in {"url", "path"}:
        action["target"] = _text(value.get("target"))
    else:
        try:
            seconds = max(1, min(86400, int(value.get("seconds", 1))))
        except (TypeError, ValueError):
            seconds = 1
        action["seconds"] = seconds
    return action


def normalize_custom_cards(value) -> list[dict]:
    result = []
    card_ids = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        title = _text(raw.get("title"))
        actions = [
            action
            for action in (normalize_action(item) for item in raw.get("actions", []))
            if action is not None
        ]
        if not title or not actions:
            continue
        icon = raw.get("icon") if isinstance(raw.get("icon"), dict) else {}
        if icon.get("type") == "file" and _text(icon.get("file")):
            normalized_icon = {"type": "file", "file": Path(_text(icon["file"])).name}
        else:
            name = _text(icon.get("name"), "APPLICATION")
            normalized_icon = {
                "type": "fluent",
                "name": name if name in FIF.__members__ else "APPLICATION",
            }
        card_id = _text(raw.get("id")) or new_id()
        if card_id in card_ids:
            card_id = new_id()
        card_ids.add(card_id)
        action_ids = set()
        for action in actions:
            if action["id"] in action_ids:
                action["id"] = new_id()
            action_ids.add(action["id"])
        result.append(
            {
                "id": card_id,
                "title": title[:40],
                "description": _text(raw.get("description"))[:120],
                "icon": normalized_icon,
                "actions": actions,
            }
        )
    return result


def icon_path(icon: dict | None) -> Path | None:
    if not isinstance(icon, dict) or icon.get("type") != "file":
        return None
    filename = Path(_text(icon.get("file"))).name
    if not filename:
        return None
    root = HOME_CARD_ICON_DIR.resolve()
    path = (root / filename).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def icon_for_data(icon: dict | None):
    if isinstance(icon, dict) and icon.get("type") == "file":
        path = icon_path(icon)
        if path and path.is_file():
            loaded = QIcon(str(path))
            if not loaded.isNull():
                return loaded
    name = icon.get("name", "APPLICATION") if isinstance(icon, dict) else "APPLICATION"
    return getattr(FIF, name, FIF.APPLICATION)


def save_icon_image(image: QImage) -> str:
    if image.isNull():
        raise HomeCardError("图标图片无效")
    try:
        HOME_CARD_ICON_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{new_id()}.png"
        path = HOME_CARD_ICON_DIR / filename
        if not image.convertToFormat(QImage.Format.Format_ARGB32).save(str(path), "PNG"):
            raise HomeCardError("无法保存图标图片")
        return filename
    except OSError as error:
        raise HomeCardError(f"无法保存图标图片: {error}") from error


def remove_cached_icon(icon: dict | None) -> None:
    path = icon_path(icon)
    if path and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def _image_from_path(path: Path) -> list[QImage]:
    if path.suffix.lower() in IMAGE_SUFFIXES:
        image = QImage(str(path))
        return [image] if not image.isNull() else []
    if os.name != "nt":
        pixmap = QIcon(str(path)).pixmap(QSize(64, 64))
        image = pixmap.toImage()
        return [image] if not image.isNull() else []

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hicon = ctypes.c_void_p
    extract = shell32.ExtractIconExW
    extract.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(hicon),
        ctypes.POINTER(hicon),
        wintypes.UINT,
    ]
    extract.restype = wintypes.UINT
    destroy = user32.DestroyIcon
    destroy.argtypes = [hicon]
    destroy.restype = wintypes.BOOL

    count = extract(str(path), -1, None, None, 0)
    if count in (0, 0xFFFFFFFF):
        return []
    images = []
    for start in range(0, count, 64):
        batch = min(64, count - start)
        handles = (hicon * batch)()
        extracted = extract(str(path), start, handles, None, batch)
        for handle in handles[:extracted]:
            value = handle.value if hasattr(handle, "value") else handle
            if not value:
                continue
            try:
                image = QImage.fromHICON(value).copy()
                if not image.isNull():
                    images.append(image)
            finally:
                destroy(handle)
    return images


def extract_icon_images(path: str | Path) -> list[QImage]:
    source = Path(path)
    if not source.is_file():
        raise HomeCardError("图标文件不存在")
    try:
        images = _image_from_path(source)
    except (OSError, ctypes.ArgumentError, ValueError) as error:
        raise HomeCardError(f"无法读取图标文件: {error}") from error
    if not images:
        raise HomeCardError("文件中没有可用图标")
    return images


def validate_action(action: dict) -> str:
    action = normalize_action(action)
    if action is None:
        return "动作数据无效"
    action_type = action["type"]
    if action_type == "program":
        if not action["target"]:
            return "请输入程序或命令"
        if action["working_dir"] and not Path(os.path.expandvars(action["working_dir"])).is_dir():
            return "工作目录不存在"
    elif action_type == "shell":
        if not action["command"]:
            return "请输入 Shell 命令"
        if action["working_dir"] and not Path(os.path.expandvars(action["working_dir"])).is_dir():
            return "工作目录不存在"
    elif action_type == "url":
        target = action["target"]
        if not target:
            return "请输入网页地址"
        if "://" not in target:
            target = f"https://{target}"
        parsed = urlparse(target)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or any(
            char in target for char in "\r\n\x00"
        ):
            return "网页地址只支持 HTTP 或 HTTPS"
    elif action_type == "path":
        if not action["target"] or not Path(os.path.expandvars(action["target"])).exists():
            return "本地文件或文件夹不存在"
    return ""


def _wait_process(
    process,
    cancel: threading.Event,
) -> str | None:
    while process.poll() is None:
        if cancel.wait(0.1):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            return None
    return f"进程退出码: {process.returncode}" if process.returncode else None


def execute_action(action: dict, cancel: threading.Event) -> str | None:
    action = normalize_action(action)
    if action is None:
        return "动作数据无效"
    error = validate_action(action)
    if error:
        return error
    action_type = action["type"]
    if action_type == "delay":
        return None if not cancel.wait(action["seconds"]) else None
    if action_type == "url":
        target = action["target"]
        target = target if "://" in target else f"https://{target}"
        return None if webbrowser.open(target, new=2) else "无法打开网页"
    if action_type == "path":
        target = os.path.expandvars(action["target"])
        try:
            if hasattr(os, "startfile"):
                os.startfile(target)
            else:
                webbrowser.open(Path(target).resolve().as_uri())
            return None
        except OSError as error:
            return str(error)

    working_dir = os.path.expandvars(action.get("working_dir", "")) or None
    try:
        if action_type == "program":
            target = os.path.expandvars(action["target"])
            arguments = QProcess.splitCommand(action["arguments"])
            process = subprocess.Popen([target, *arguments], cwd=working_dir)
        else:
            flags = 0
            if os.name == "nt":
                flags = (
                    subprocess.CREATE_NEW_CONSOLE
                    if action["show_console"]
                    else subprocess.CREATE_NO_WINDOW
                )
            process = subprocess.Popen(
                action["command"],
                cwd=working_dir,
                shell=True,
                creationflags=flags,
            )
    except (OSError, ValueError) as error:
        return str(error)
    if action["wait"]:
        return _wait_process(process, cancel)
    return None


class ActionSequenceWorker(QObject):
    finished = Signal(str, object)

    def __init__(self, card_id: str, get_actions, parent=None):
        super().__init__(parent)
        self.card_id = card_id
        self.get_actions = get_actions
        self.cancel_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()

    def wait(self) -> None:
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        executed = set()
        errors = []
        while not self.cancel_event.is_set():
            actions = self.get_actions(self.card_id)
            if actions is None:
                break
            action = next(
                (item for item in actions if item.get("id") not in executed),
                None,
            )
            if action is None:
                break
            executed.add(action["id"])
            try:
                error = execute_action(copy.deepcopy(action), self.cancel_event)
            except Exception as error:
                error = str(error)
            if error:
                errors.append(f"{action.get('type', '动作')}: {error}")
        try:
            self.finished.emit(self.card_id, errors)
        except RuntimeError:
            # HomePage may be deleted while the daemon thread is finishing.
            pass


__all__ = [
    "ACTION_TYPES",
    "ActionSequenceWorker",
    "DEFAULT_HOME_CARD_NAMES",
    "HomeCardError",
    "execute_action",
    "extract_icon_images",
    "icon_for_data",
    "new_id",
    "normalize_action",
    "normalize_custom_cards",
    "remove_cached_icon",
    "save_icon_image",
    "validate_action",
]
