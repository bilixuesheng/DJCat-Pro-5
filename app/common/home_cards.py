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
from PySide6.QtGui import QIcon, QImage
from qfluentwidgets import FluentIcon as FIF

from app.common.process_environment import externalProcessEnvironment
from app.config.paths import HOME_CARD_ICON_DIR


DIRECT_APPLICATION_PRESET_ID = 0
ACTION_TYPES = ("program", "shell", "url", "path", "delay")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


class HomeCardError(ValueError):
    pass


def newId() -> str:
    return uuid.uuid4().hex


def _text(value, default="") -> str:
    return str(value).strip() if value is not None else default


def normalizeAction(value: dict | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    actionType = _text(value.get("type")).lower()
    if actionType not in ACTION_TYPES:
        return None
    action = {"id": _text(value.get("id")) or newId(), "type": actionType}
    if actionType == "program":
        action.update(
            {
                "target": _text(value.get("target")),
                "arguments": _text(value.get("arguments")),
                "working_dir": _text(value.get("working_dir")),
                "wait": bool(value.get("wait", False)),
            }
        )
    elif actionType == "shell":
        action.update(
            {
                "command": _text(value.get("command")),
                "working_dir": _text(value.get("working_dir")),
                "wait": bool(value.get("wait", False)),
                "show_console": bool(value.get("show_console", False)),
            }
        )
    elif actionType in {"url", "path"}:
        action["target"] = _text(value.get("target"))
    else:
        try:
            seconds = max(1, min(86400, int(value.get("seconds", 1))))
        except (TypeError, ValueError):
            seconds = 1
        action["seconds"] = seconds
    return action


def normalizeActions(value) -> list[dict]:
    """Valid actions of one Action Sequence, with action IDs made unique."""
    actions = [
        action
        for action in (
            normalizeAction(item)
            for item in (value if isinstance(value, list) else [])
        )
        if action is not None
    ]
    actionIds = set()
    for action in actions:
        if action["id"] in actionIds:
            action["id"] = newId()
        actionIds.add(action["id"])
    return actions


def normalizeCustomCards(value) -> list[dict]:
    result = []
    cardIds = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict):
            continue
        title = _text(raw.get("title"))
        actions = normalizeActions(raw.get("actions", []))
        if not title or not actions:
            continue
        icon = raw.get("icon") if isinstance(raw.get("icon"), dict) else {}
        if icon.get("type") == "file" and _text(icon.get("file")):
            normalizedIcon = {"type": "file", "file": Path(_text(icon["file"])).name}
        else:
            name = _text(icon.get("name"), "APPLICATION")
            normalizedIcon = {
                "type": "fluent",
                "name": name if name in FIF.__members__ else "APPLICATION",
            }
        cardId = _text(raw.get("id")) or newId()
        if cardId in cardIds:
            cardId = newId()
        cardIds.add(cardId)
        result.append(
            {
                "id": cardId,
                "title": title[:40],
                "description": _text(raw.get("description"))[:120],
                "icon": normalizedIcon,
                "actions": actions,
            }
        )
    return result


def normalizePinnedCards(value) -> list[dict]:
    result = []
    keys = set()
    for raw in value if isinstance(value, list) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("action"), dict):
            continue
        try:
            appId = int(raw.get("app_id"))
            presetId = int(raw.get("preset_id"))
        except (TypeError, ValueError):
            continue
        key = (appId, presetId)
        if appId <= 0 or presetId < DIRECT_APPLICATION_PRESET_ID or key in keys:
            continue
        keys.add(key)
        result.append(
            {
                "app_id": appId,
                "preset_id": presetId,
                "title": _text(raw.get("title")),
                "description": _text(raw.get("description")),
                "action": copy.deepcopy(raw["action"]),
                "install_dir": _text(raw.get("install_dir")),
                "icon_url": _text(raw.get("icon_url")),
                "icon_path": _text(raw.get("icon_path")),
            }
        )
    return result


def iconPath(icon: dict | None) -> Path | None:
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


def iconForData(icon: dict | None):
    if isinstance(icon, dict) and icon.get("type") == "file":
        path = iconPath(icon)
        if path and path.is_file():
            loaded = QIcon(str(path))
            if not loaded.isNull():
                return loaded
    name = icon.get("name", "APPLICATION") if isinstance(icon, dict) else "APPLICATION"
    return getattr(FIF, name, FIF.APPLICATION)


def saveIconImage(image: QImage) -> str:
    if image.isNull():
        raise HomeCardError("图标图片无效")
    try:
        HOME_CARD_ICON_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{newId()}.png"
        path = HOME_CARD_ICON_DIR / filename
        if not image.convertToFormat(QImage.Format.Format_ARGB32).save(str(path), "PNG"):
            raise HomeCardError("无法保存图标图片")
        return filename
    except OSError as error:
        raise HomeCardError(f"无法保存图标图片: {error}") from error


def removeCachedIcon(icon: dict | None) -> None:
    path = iconPath(icon)
    if path and path.is_file():
        try:
            path.unlink()
        except OSError:
            pass


def _imageFromPath(path: Path) -> list[QImage]:
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


def extractIconImages(path: str | Path) -> list[QImage]:
    source = Path(path)
    if not source.is_file():
        raise HomeCardError("图标文件不存在")
    try:
        images = _imageFromPath(source)
    except (OSError, ctypes.ArgumentError, ValueError) as error:
        raise HomeCardError(f"无法读取图标文件: {error}") from error
    if not images:
        raise HomeCardError("文件中没有可用图标")
    return images


def validateAction(action: dict) -> str:
    action = normalizeAction(action)
    if action is None:
        return "动作数据无效"
    actionType = action["type"]
    if actionType == "program":
        if not action["target"]:
            return "请输入程序或命令"
    elif actionType == "shell":
        if not action["command"]:
            return "请输入 Shell 命令"
    elif actionType == "url":
        target = action["target"]
        if not target:
            return "请输入网页地址"
        if "://" not in target:
            target = f"https://{target}"
        try:
            parsed = urlparse(target)
        except ValueError:
            return "网页地址无效"
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or any(
            char in target for char in "\r\n\x00"
        ):
            return "网页地址只支持 HTTP 或 HTTPS"
    elif actionType == "path" and not action["target"]:
        return "请输入本地文件或文件夹"
    return ""


def _waitProcess(
    process,
    cancel: threading.Event,
) -> str | None:
    while process.poll() is None:
        if cancel.wait(0.1):
            return None
    return f"进程退出码: {process.returncode}" if process.returncode else None


def executeAction(action: dict, cancel: threading.Event) -> str | None:
    action = normalizeAction(action)
    if action is None:
        return "动作数据无效"
    error = validateAction(action)
    if error:
        return error
    actionType = action["type"]
    if actionType == "delay":
        cancel.wait(action["seconds"])
        return None
    if actionType == "url":
        target = action["target"]
        target = target if "://" in target else f"https://{target}"
        return None if webbrowser.open(target, new=2) else "无法打开网页"
    if actionType == "path":
        target = os.path.expandvars(action["target"])
        try:
            if hasattr(os, "startfile"):
                os.startfile(target)
            else:
                webbrowser.open(Path(target).resolve().as_uri())
            return None
        except OSError as error:
            return str(error)

    workingDir = os.path.expandvars(action.get("working_dir", "")) or None
    try:
        if actionType == "program":
            target = os.path.expandvars(action["target"])
            arguments = QProcess.splitCommand(action["arguments"])
            process = subprocess.Popen(
                [target, *arguments],
                cwd=workingDir,
                env=externalProcessEnvironment(globals().get("__compiled__")),
            )
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
                cwd=workingDir,
                shell=True,
                creationflags=flags,
                env=externalProcessEnvironment(globals().get("__compiled__")),
            )
    except (OSError, ValueError) as error:
        return str(error)
    if action["wait"]:
        return _waitProcess(process, cancel)
    return None


class ActionSequenceWorker(QObject):
    finished = Signal(str, object)

    def __init__(self, cardId: str, getActions, parent=None):
        super().__init__(parent)
        self.cardId = cardId
        self.getActions = getActions
        self.cancelEvent = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self.cancelEvent.set()

    def wait(self, timeout=None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        executed = set()
        errors = []
        while not self.cancelEvent.is_set():
            try:
                actions = self.getActions(self.cardId)
            except Exception as error:
                errors.append(f"动作配置: {error}")
                break
            if actions is None:
                break
            try:
                action = next(
                    (
                        item
                        for item in actions
                        if isinstance(item, dict)
                        and item.get("id") not in executed
                    ),
                    None,
                )
            except Exception as error:
                errors.append(f"动作配置: {error}")
                break
            if action is None:
                break
            executed.add(action["id"])
            try:
                error = executeAction(copy.deepcopy(action), self.cancelEvent)
            except Exception as error:
                error = str(error)
            if error:
                errors.append(f"{action.get('type', '动作')}: {error}")
        try:
            self.finished.emit(self.cardId, errors)
        except RuntimeError:
            # HomePage may be deleted while the daemon thread is finishing.
            pass
