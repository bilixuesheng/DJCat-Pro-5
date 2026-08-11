"""Client-side application catalog, installation and cache primitives."""

import json
import os
import platform
import re
import shutil
import subprocess
import time
import uuid
import webbrowser
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests

from app.config.paths import (
    APP_STORE_CACHE_DIR,
    APP_STORE_DOWNLOAD_DIR,
    PROGRAM_DIR,
)


CATALOG_PATH = "/app-store/catalog"
MAX_ZIP_COMPRESSED = 2 * 1024 * 1024 * 1024
MAX_ZIP_EXPANDED = 8 * 1024 * 1024 * 1024
MAX_ZIP_FILES = 50_000
MAX_ZIP_RATIO = 200
CACHE_MAX_AGE = 7 * 24 * 60 * 60
CACHE_SWEEP_INTERVAL = CACHE_MAX_AGE
ARCHITECTURES = ("x86_64", "arm64")
MANIFEST_NAME = ".djcat-app.json"
_SAFE_INSTALL_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_DANGEROUS_SCHEMES = {
    "cmd",
    "data",
    "file",
    "ftp",
    "http",
    "https",
    "javascript",
    "ms-settings",
    "powershell",
    "shell",
    "vbscript",
}


class ApplicationStoreError(Exception):
    pass


class UnsafeArchiveError(ApplicationStoreError):
    pass


class DownloadLimitError(ApplicationStoreError):
    pass


@dataclass(frozen=True)
class InstalledApplication:
    appId: int
    name: str
    version: str
    installDir: str
    path: Path
    metadata: dict


def clientArchitecture() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else "x86_64"


def versionKey(value: str) -> tuple:
    parts = re.findall(r"\d+|[a-z]+", str(value or "").lower())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def isUpdateAvailable(installedVersion: str, catalogVersion: str) -> bool:
    if not installedVersion or not catalogVersion:
        return False
    return versionKey(catalogVersion) > versionKey(installedVersion)


def _httpsUrl(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ApplicationStoreError("应用链接必须使用 HTTPS")
    return parsed.geturl()


def _safeInstallDir(value: str) -> str:
    value = str(value or "").strip()
    if not _SAFE_INSTALL_DIR.fullmatch(value):
        raise ApplicationStoreError("应用安装目录无效")
    return value


def _underRoot(path: Path, root: Path) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ApplicationStoreError("路径超出应用安装目录") from error
    return path


def _assertNoLinks(root: Path) -> None:
    isJunction = getattr(root, "is_junction", lambda: False)()
    if root.is_symlink() or isJunction:
        raise ApplicationStoreError("现有安装目录包含链接，已停止覆盖安装")
    if not root.exists():
        return
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            path = Path(directory) / name
            isJunction = getattr(path, "is_junction", lambda: False)()
            if path.is_symlink() or isJunction:
                raise ApplicationStoreError("现有安装目录包含链接，已停止覆盖安装")


def _safeZipName(name: str) -> tuple[str, ...]:
    name = name.replace("\\", "/")
    if not name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise UnsafeArchiveError("压缩包包含绝对路径")
    parts = tuple(part for part in PurePosixPath(name).parts if part not in {""})
    if not parts or any(part in {".", ".."} for part in parts):
        raise UnsafeArchiveError("压缩包包含越界路径")
    for part in parts:
        if ":" in part or any(
            ord(char) < 32 or char in '<>"|?*' for char in part
        ):
            raise UnsafeArchiveError("压缩包包含 Windows 非法文件名")
        baseName = part.rstrip(" .").split(".", 1)[0].upper()
        if baseName in _RESERVED_NAMES or part.endswith((".", " ")):
            raise UnsafeArchiveError("压缩包包含保留文件名")
    return parts


def _isSymlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _archiveEntries(archive: zipfile.ZipFile) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_FILES:
        raise UnsafeArchiveError("压缩包文件数量过多")
    compressed = sum(max(0, info.compress_size) for info in infos)
    expanded = sum(max(0, info.file_size) for info in infos)
    if compressed > MAX_ZIP_COMPRESSED or expanded > MAX_ZIP_EXPANDED:
        raise UnsafeArchiveError("压缩包大小超过安全限制")
    if compressed and expanded > compressed * MAX_ZIP_RATIO:
        raise UnsafeArchiveError("压缩包压缩比例异常")
    entries = []
    seen = set()
    for info in infos:
        if _isSymlink(info):
            raise UnsafeArchiveError("压缩包不允许包含符号链接")
        parts = _safeZipName(info.filename)
        key = "/".join(parts).casefold()
        if key in seen:
            raise UnsafeArchiveError("压缩包包含大小写冲突的重复路径")
        seen.add(key)
        entries.append((info, parts))
    return entries


def _stripTopFolder(entries: Iterable[tuple[zipfile.ZipInfo, tuple[str, ...]]]):
    entries = list(entries)
    firstParts = {parts[0] for info, parts in entries if not info.is_dir() and parts}
    if len(firstParts) != 1:
        return entries
    top = next(iter(firstParts))
    if any(len(parts) == 1 and not info.is_dir() for info, parts in entries):
        return entries
    return [(info, parts[1:]) for info, parts in entries]


def validateZip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            _archiveEntries(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise UnsafeArchiveError("下载文件不是有效的 ZIP 安装包") from error


def _extractZip(path: Path, destination: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = _stripTopFolder(_archiveEntries(archive))
        for info, parts in entries:
            if not parts:
                continue
            target = _underRoot(destination.joinpath(*parts), destination)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


class ImageCache:
    def __init__(self, directory: Path = APP_STORE_CACHE_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.marker = self.directory / ".last-sweep"
        self.sweepIfDue()

    def pathFor(self, url: str) -> Path:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}:
            suffix = ".img"
        import hashlib

        return self.directory / f"{hashlib.sha256(url.encode()).hexdigest()}{suffix}"

    def get(self, url: str, session=requests) -> Path:
        url = _httpsUrl(url)
        path = self.pathFor(url)
        if path.is_file():
            path.touch()
            return path
        response = session.get(url, timeout=(10, 30))
        response.raise_for_status()
        if urlparse(str(getattr(response, "url", url))).scheme.lower() != "https":
            raise ApplicationStoreError("图片链接必须保持 HTTPS")
        if len(response.content) > 20 * 1024 * 1024:
            raise ApplicationStoreError("图片超过 20MB，未写入缓存")
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(response.content)
        temporary.replace(path)
        return path

    def sweepIfDue(self, now: float | None = None) -> None:
        now = now or time.time()
        try:
            due = now - self.marker.stat().st_mtime >= CACHE_SWEEP_INTERVAL
        except FileNotFoundError:
            due = True
        if not due:
            return
        cutoff = now - CACHE_MAX_AGE
        for path in self.directory.iterdir():
            if path == self.marker or path.is_dir():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                pass
        self.marker.touch()

    def clear(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.iterdir():
            if path.is_file() and path != self.marker:
                path.unlink()
        self.marker.touch()


class DownloadSlots:
    """Small shared limiter used by every marketplace download action."""

    def __init__(self, maximum: int = 3):
        self.maximum = maximum
        self.active = 0

    def acquire(self) -> None:
        if self.active >= self.maximum:
            raise DownloadLimitError("同时最多下载 3 个应用")
        self.active += 1

    def release(self) -> None:
        self.active = max(0, self.active - 1)


class ApplicationStore:
    def __init__(
        self,
        apiBaseUrl: str | None = None,
        programDir: Path = PROGRAM_DIR,
        cache: ImageCache | None = None,
    ):
        self.apiBaseUrl = (apiBaseUrl or os.environ.get("DJCATAI_API_BASE_URL", "https://api.djcatpro.top")).rstrip("/") + "/"
        self.programDir = Path(programDir)
        self.programDir.mkdir(parents=True, exist_ok=True)
        self.cache = cache or ImageCache()
        self.architecture = clientArchitecture()
        self.downloadSlots = DownloadSlots()

    def fetchCatalog(self, session=requests) -> dict:
        response = session.get(urljoin(self.apiBaseUrl, CATALOG_PATH.lstrip("/")), timeout=(10, 30))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("apps"), list):
            raise ApplicationStoreError("应用目录格式无效")
        return payload

    def imagePath(self, url: str, session=requests) -> Path:
        return self.cache.get(url, session)

    def downloadPath(self, app: dict) -> Path:
        appId = int(app["id"])
        return APP_STORE_DOWNLOAD_DIR / f"{appId}-{self.architecture}.zip"

    def downloadUrl(self, app: dict) -> str:
        return urljoin(
            self.apiBaseUrl,
            f"app-store/apps/{int(app['id'])}/download?arch={self.architecture}",
        )

    def installZip(self, app: dict, zipPath: Path) -> InstalledApplication:
        validateZip(zipPath)
        installDir = _safeInstallDir(app.get("install_dir"))
        target = _underRoot(self.programDir / installDir, self.programDir)
        staging = self.programDir / f".{installDir}.staging-{uuid.uuid4().hex}"
        backup = None
        staging.mkdir(parents=True, exist_ok=False)
        try:
            _extractZip(Path(zipPath), staging)
            _assertNoLinks(target)
            if target.exists() and not target.is_dir():
                raise ApplicationStoreError("应用安装目录不是文件夹")
            manifest = {
                "id": int(app["id"]),
                "name": str(app.get("name", "")),
                "version": str(app.get("version", "")),
                "install_dir": installDir,
                "icon_url": str(app.get("icon_url", "")),
                "open_action": app.get("open_action"),
                "presets": app.get("presets", []),
                "installed_architecture": self.architecture,
            }
            (staging / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if target.exists():
                backup = self.programDir / f".{installDir}.backup-{uuid.uuid4().hex}"
                target.replace(backup)
            staging.replace(target)
            if backup:
                shutil.rmtree(backup, ignore_errors=True)
                backup = None
        except Exception:
            if backup and not target.exists() and backup.exists():
                backup.replace(target)
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return InstalledApplication(
            manifest["id"], manifest["name"], manifest["version"], installDir, target, manifest
        )

    def installed(self) -> dict[int, InstalledApplication]:
        result = {}
        if not self.programDir.exists():
            return result
        for directory in self.programDir.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            manifestPath = directory / MANIFEST_NAME
            try:
                manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
                appId = int(manifest["id"])
            except (OSError, ValueError, TypeError, json.JSONDecodeError, KeyError):
                continue
            result[appId] = InstalledApplication(
                appId,
                str(manifest.get("name", "")),
                str(manifest.get("version", "")),
                str(manifest.get("install_dir", directory.name)),
                directory,
                manifest,
            )
        return result

    def uninstall(self, appOrInstallDir: dict | InstalledApplication | str) -> None:
        if isinstance(appOrInstallDir, InstalledApplication):
            installDir = appOrInstallDir.installDir
        elif isinstance(appOrInstallDir, dict):
            local = None
            try:
                local = self.installed().get(int(appOrInstallDir.get("id")))
            except (TypeError, ValueError):
                pass
            installDir = local.installDir if local else appOrInstallDir.get("install_dir")
        else:
            installDir = appOrInstallDir
        installDir = _safeInstallDir(installDir)
        target = _underRoot(self.programDir / installDir, self.programDir)
        if target.exists():
            shutil.rmtree(target)

    def mergeInstalled(self, apps: Iterable[dict]) -> list[dict]:
        installed = self.installed()
        result = []
        for app in apps:
            item = dict(app)
            local = installed.get(int(app["id"]))
            item["installed"] = local is not None
            item["installed_version"] = local.version if local else ""
            item["architecture_supported"] = self.architecture in {
                architecture
                for architecture, package in (app.get("packages") or {}).items()
                if package.get("enabled")
            }
            item["update_available"] = bool(
                local
                and item["architecture_supported"]
                and isUpdateAvailable(local.version, str(app.get("version", "")))
            )
            result.append(item)
        return result

    def executeAction(self, application: dict | InstalledApplication, action: dict | None = None):
        if isinstance(application, InstalledApplication):
            metadata = application.metadata
            installPath = application.path
        else:
            metadata = application
            installDir = _safeInstallDir(application.get("install_dir"))
            installPath = _underRoot(self.programDir / installDir, self.programDir)
        action = action or metadata.get("open_action")
        if not action:
            raise ApplicationStoreError("该应用没有可执行的打开动作")
        actionType = str(action.get("type", "")).lower()
        target = str(action.get("target", "")).strip()
        arguments = action.get("arguments") or action.get("action_arguments") or {}
        if actionType == "program":
            targetParts = PurePosixPath(target.replace("\\", "/")).parts
            if (
                not target.lower().endswith(".exe")
                or not targetParts
                or target.startswith(("/", "\\"))
                or ":" in target
                or any(part in {".", ".."} for part in targetParts)
            ):
                raise ApplicationStoreError("程序动作路径无效")
            programPath = _underRoot(installPath.joinpath(*targetParts), installPath)
            if not programPath.is_file() or programPath.is_symlink():
                raise ApplicationStoreError("程序文件不存在")
            args = arguments.get("args", []) if isinstance(arguments, dict) else []
            if not isinstance(args, list) or any(not isinstance(value, str) for value in args):
                raise ApplicationStoreError("程序参数无效")
            return subprocess.Popen([str(programPath), *args], cwd=installPath)
        if actionType == "url":
            return webbrowser.open(_httpsUrl(target))
        if actionType == "uri":
            parsed = urlparse(target)
            if not parsed.scheme or parsed.scheme.lower() in _DANGEROUS_SCHEMES or any(char in target for char in "\r\n\x00"):
                raise ApplicationStoreError("系统协议动作被拒绝")
            if hasattr(os, "startfile"):
                os.startfile(target)
                return True
            return webbrowser.open(target)
        raise ApplicationStoreError("未知的打开动作")


def downloadWorker(app: dict, store: ApplicationStore):
    """Create the shared Ghost-style worker with ZIP validation."""
    from app.common.update_download import UpdateDownloadWorker

    target = store.downloadPath(app)
    target.parent.mkdir(parents=True, exist_ok=True)
    return UpdateDownloadWorker(
        store.downloadUrl(app),
        target,
        validator=validateZip,
        requireHttps=True,
    )


__all__ = [
    "ApplicationStore",
    "ApplicationStoreError",
    "DownloadLimitError",
    "DownloadSlots",
    "ImageCache",
    "InstalledApplication",
    "UnsafeArchiveError",
    "clientArchitecture",
    "downloadWorker",
    "isUpdateAvailable",
    "validateZip",
    "versionKey",
]
