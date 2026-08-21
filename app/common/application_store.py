"""Client-side application catalog, installation and cache primitives."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urljoin, urlparse
from weakref import WeakValueDictionary

import requests
from PySide6.QtGui import QImageReader

from app.common.application_version import (
    clientArchitecture,
    isUpdateAvailable,
    versionKey,
)
from app.common.process_environment import externalProcessEnvironment
from app.common.update_download import isHttpsResponseChain
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
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8192
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_CHUNK_SIZE = 64 * 1024
ZIP_CHUNK_SIZE = 1024 * 1024
CACHE_MAX_AGE = 7 * 24 * 60 * 60
CACHE_SWEEP_INTERVAL = CACHE_MAX_AGE
ARCHITECTURES = ("x86_64", "arm64")
MANIFEST_NAME = ".djcat-app.json"
_SAFE_INSTALL_DIR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,63}$")
_INSTALL_ARTIFACT = re.compile(
    r"^\.(?P<install>.+)\.(?P<kind>staging|backup|uninstall)-[a-f0-9]{32}$"
)
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


def _runningExecutablesUnder(directory: Path) -> list[Path]:
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        processIds = (wintypes.DWORD * 4096)()
        bytesNeeded = wintypes.DWORD()
        if not ctypes.windll.psapi.EnumProcesses(
            processIds, ctypes.sizeof(processIds), ctypes.byref(bytesNeeded)
        ):
            return []
        root = directory.resolve(strict=False)
        running = []
        count = bytesNeeded.value // ctypes.sizeof(wintypes.DWORD)
        for processId in processIds[:count]:
            if not processId or processId == os.getpid():
                continue
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, processId)
            if not handle:
                continue
            try:
                length = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(length.value)
                if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buffer, ctypes.byref(length)
                ):
                    continue
                executable = Path(buffer.value).resolve(strict=False)
                try:
                    executable.relative_to(root)
                except ValueError:
                    continue
                running.append(executable)
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return running
    except (AttributeError, OSError, ValueError):
        return []


def _manifestRevision(value) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def _validSha256(value) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "").strip().lower()))


def _presetList(value) -> list[dict]:
    return (
        [preset for preset in value if isinstance(preset, dict)]
        if isinstance(value, list)
        else []
    )


def _httpsUrl(value: str) -> str:
    value = (value or "").strip()
    try:
        parsed = urlparse(value)
    except ValueError as error:
        raise ApplicationStoreError("应用链接无效") from error
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or any(char in value for char in "\r\n\x00")
    ):
        raise ApplicationStoreError("应用链接必须使用 HTTPS")
    return parsed.geturl()


def _safeInstallDir(value: str) -> str:
    value = str(value or "").strip()
    baseName = value.rstrip(" .").split(".", 1)[0].upper()
    if (
        not _SAFE_INSTALL_DIR.fullmatch(value)
        or value.endswith((".", " "))
        or baseName in _RESERVED_NAMES
    ):
        raise ApplicationStoreError("应用安装目录无效")
    return value


def _hasControlCharacters(value) -> bool:
    if isinstance(value, str):
        return any(ord(char) < 32 or ord(char) == 127 for char in value)
    if isinstance(value, dict):
        return any(
            _hasControlCharacters(key) or _hasControlCharacters(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_hasControlCharacters(item) for item in value)
    return False


def _programTargetParts(value: str) -> tuple[str, ...]:
    parts = tuple(value.replace("\\", "/").split("/"))
    if (
        not value.lower().endswith(".exe")
        or not parts
        or value.startswith(("/", "\\"))
        or ":" in value
        or any(
            part in {"", ".", ".."}
            or any(char in '<>"|?*' for char in part)
            or part.endswith((".", " "))
            or part.rstrip(" .").split(".", 1)[0].upper() in _RESERVED_NAMES
            for part in parts
        )
    ):
        raise ApplicationStoreError("程序动作路径无效")
    return parts


def _underRoot(path: Path, root: Path) -> Path:
    root = root.resolve()
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise ApplicationStoreError("路径超出应用安装目录") from error
    return path


def _externalProcessEnvironment() -> dict[str, str]:
    return externalProcessEnvironment(globals().get("__compiled__"))


def _activateProcessWindow(process, stopEvent=None, onFailure=None):
    pid = getattr(process, "pid", None)
    if os.name != "nt" or type(pid) is not int or pid <= 0:
        return None
    stopEvent = stopEvent or threading.Event()

    def activate():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        processArgs = getattr(process, "args", ())
        if isinstance(processArgs, (str, os.PathLike)):
            processArgs = (processArgs,)
        try:
            executableName = Path(processArgs[0]).name.casefold()
        except (IndexError, TypeError, ValueError):
            executableName = ""

        def sameExecutable(ownerPid):
            if not executableName:
                return False
            handle = ctypes.windll.kernel32.OpenProcess(
                0x1000,
                False,
                ownerPid,
            )
            if not handle:
                return False
            try:
                length = wintypes.DWORD(32768)
                buffer = ctypes.create_unicode_buffer(length.value)
                if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle,
                    0,
                    buffer,
                    ctypes.byref(length),
                ):
                    return False
                return Path(buffer.value).name.casefold() == executableName
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)

        def wakeGhostIpc(allowFallback):
            try:
                window = user32.FindWindowW("GhostDownloaderIPC", None)
                if not window:
                    return False
                ownerPid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(window, ctypes.byref(ownerPid))
                if not (
                    ownerPid.value == pid
                    or (allowFallback and sameExecutable(ownerPid.value))
                ):
                    return False
                return bool(user32.PostMessageW(window, 1025, 0, 0))
            except (AttributeError, OSError, TypeError, ValueError):
                return False

        try:
            user32.AllowSetForegroundWindow(pid)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
        deadline = time.monotonic() + 8
        exitedAt = None
        ipcWoken = False
        while not stopEvent.is_set() and time.monotonic() < deadline:
            found = []
            allowExistingInstance = exitedAt is not None

            if not ipcWoken and wakeGhostIpc(allowExistingInstance):
                ipcWoken = True

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def visit(
                window,
                _,
                matches=found,
                allowFallback=allowExistingInstance,
            ):
                ownerPid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(window, ctypes.byref(ownerPid))
                if (
                    (
                        ownerPid.value == pid
                        or (allowFallback and sameExecutable(ownerPid.value))
                    )
                    and user32.IsWindowVisible(window)
                    and user32.GetWindow(window, 4) == 0
                    and user32.GetWindowTextLengthW(window) > 0
                ):
                    matches.append(window)
                    return False
                return True

            user32.EnumWindows(visit, 0)
            if found:
                user32.ShowWindow(found[0], 9)
                user32.BringWindowToTop(found[0])
                user32.SetForegroundWindow(found[0])
                return
            exitCode = process.poll()
            if exitCode is not None:
                exitedAt = exitedAt or time.monotonic()
                if time.monotonic() - exitedAt >= 2:
                    break
            stopEvent.wait(0.1)

        if stopEvent.is_set() or onFailure is None:
            return
        exitCode = process.poll()
        if exitCode is None:
            message = "程序已在后台运行，但未找到可显示窗口，请检查系统托盘"
        elif exitCode != 0:
            message = "程序启动后立即退出，可能已有实例正在运行"
        else:
            return
        try:
            onFailure(message)
        except RuntimeError:
            pass

    worker = threading.Thread(target=activate, daemon=True)
    worker.start()
    return worker


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
    if any(len(parts) == 1 and not info.is_dir() for info, parts in entries):
        return entries
    return [(info, parts[1:]) for info, parts in entries]


def validateZip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            _archiveEntries(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise UnsafeArchiveError("下载文件不是有效的 ZIP 安装包") from error


def _extractZip(path: Path, destination: Path, cancelEvent=None) -> None:
    with zipfile.ZipFile(path) as archive:
        entries = _stripTopFolder(_archiveEntries(archive))
        for info, parts in entries:
            if cancelEvent is not None and cancelEvent.is_set():
                raise ApplicationStoreError("安装已取消")
            if not parts:
                continue
            target = _underRoot(destination.joinpath(*parts), destination)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                while True:
                    if cancelEvent is not None and cancelEvent.is_set():
                        raise ApplicationStoreError("安装已取消")
                    chunk = source.read(ZIP_CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)


class ImageCache:
    def __init__(self, directory: Path = APP_STORE_CACHE_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.marker = self.directory / ".last-sweep"
        self._pathLocks = WeakValueDictionary()
        self._pathLocksLock = threading.Lock()
        self._generation = 0
        self.sweepIfDue()

    def pathFor(self, url: str) -> Path:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".ico"}:
            suffix = ".img"
        return self.directory / f"{hashlib.sha256(url.encode()).hexdigest()}{suffix}"

    def get(self, url: str, session=requests) -> Path:
        url = _httpsUrl(url)
        path = self.pathFor(url)
        with self._pathLocksLock:
            generation = self._generation
            lock = self._pathLocks.setdefault(path, threading.Lock())
        with lock:
            return self._download(url, path, session, generation)

    def _download(self, url: str, path: Path, session, generation: int) -> Path:
        with self._pathLocksLock:
            if generation != self._generation:
                raise ApplicationStoreError("图片缓存已清理")
        if path.is_file():
            if self._isValidImage(path):
                with self._pathLocksLock:
                    if generation != self._generation:
                        raise ApplicationStoreError("图片缓存已清理")
                    try:
                        os.utime(path, None)
                    except FileNotFoundError:
                        pass
                    else:
                        return path
            with self._pathLocksLock:
                if generation != self._generation:
                    raise ApplicationStoreError("图片缓存已清理")
                path.unlink(missing_ok=True)
        temporary = path.with_suffix(
            f"{path.suffix}.{uuid.uuid4().hex}.part"
        )
        response = session.get(url, timeout=(10, 30), stream=True)
        try:
            response.raise_for_status()
            if not isHttpsResponseChain(response, url):
                raise ApplicationStoreError("图片链接必须保持 HTTPS")
            contentLength = str(getattr(response, "headers", {}).get("Content-Length", ""))
            if contentLength.isdigit() and int(contentLength) > MAX_IMAGE_BYTES:
                raise ApplicationStoreError("图片超过 20MB，未写入缓存")

            size = 0
            try:
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(chunk_size=IMAGE_CHUNK_SIZE):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > MAX_IMAGE_BYTES:
                            raise ApplicationStoreError("图片超过 20MB，未写入缓存")
                        output.write(chunk)
                formatHint = b"ico" if path.suffix == ".ico" else b""
                if not self._isValidImage(temporary, formatHint):
                    raise ApplicationStoreError("下载内容不是有效图片")
                with self._pathLocksLock:
                    if generation != self._generation:
                        raise ApplicationStoreError("图片缓存已清理")
                    temporary.replace(path)
                return path
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        finally:
            response.close()

    @staticmethod
    def _isValidImage(path: Path, formatHint: bytes = b"") -> bool:
        reader = QImageReader(str(path), formatHint)
        size = reader.size()
        if (
            not reader.canRead()
            or not size.isValid()
            or size.width() > MAX_IMAGE_DIMENSION
            or size.height() > MAX_IMAGE_DIMENSION
            or size.width() * size.height() > MAX_IMAGE_PIXELS
        ):
            return False
        image = reader.read()
        return (
            not image.isNull()
            and image.width() <= MAX_IMAGE_DIMENSION
            and image.height() <= MAX_IMAGE_DIMENSION
            and image.width() * image.height() <= MAX_IMAGE_PIXELS
        )

    def sweepIfDue(self, now: float | None = None) -> None:
        now = now or time.time()
        try:
            due = now - self.marker.stat().st_mtime >= CACHE_SWEEP_INTERVAL
        except FileNotFoundError:
            due = True
        if not due:
            return
        cutoff = now - CACHE_MAX_AGE
        with self._pathLocksLock:
            self._generation += 1
            for path in self._files():
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except FileNotFoundError:
                    pass
            self.marker.touch()

    def clear(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        with self._pathLocksLock:
            self._generation += 1
            for path in self._files():
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            self.marker.touch()

    def size(self) -> int:
        total = 0
        with self._pathLocksLock:
            for path in self._files():
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    pass
        return total

    def _files(self):
        return (
            path
            for path in self.directory.rglob("*")
            if path != self.marker and (path.is_file() or path.is_symlink())
        )


appStoreImageCache = ImageCache()
_packageOperationLock = threading.Lock()
_activePackageOperations = 0


def beginAppStorePackageOperation() -> None:
    global _activePackageOperations
    with _packageOperationLock:
        _activePackageOperations += 1


def endAppStorePackageOperation() -> None:
    global _activePackageOperations
    with _packageOperationLock:
        _activePackageOperations = max(0, _activePackageOperations - 1)


def clearAppStoreCache() -> None:
    with _packageOperationLock:
        if _activePackageOperations:
            raise ApplicationStoreError(
                "有应用正在下载或安装，请完成后再清理缓存"
            )
        appStoreImageCache.clear()


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
        onLaunchFailure=None,
    ):
        self.apiBaseUrl = (apiBaseUrl or os.environ.get("DJCATAI_API_BASE_URL", "https://api.djcatpro.top")).rstrip("/") + "/"
        self.programDir = Path(programDir).resolve()
        self.programDir.mkdir(parents=True, exist_ok=True)
        self.cache = cache or appStoreImageCache
        self.architecture = clientArchitecture()
        self.downloadSlots = DownloadSlots()
        self._launchedProcesses = {}
        self._activationStop = threading.Event()
        self._activationThreads = {}
        self._onLaunchFailure = onLaunchFailure
        self._installedLock = threading.RLock()
        self._installedCache = None
        self._installedStamp = None
        self._installedCopies = {}
        self._cleanupThread = None
        self._recoverInstallArtifacts()

    def shutdown(self) -> None:
        self._activationStop.set()
        deadline = time.monotonic() + 1
        for worker in set(self._activationThreads.values()):
            worker.join(max(0, deadline - time.monotonic()))
        self._activationThreads.clear()
        self._onLaunchFailure = None
        if self._cleanupThread is not None:
            self._cleanupThread.join(max(0, deadline - time.monotonic()))

    def _recoverInstallArtifacts(self) -> None:
        cleanup = []
        artifacts = []
        try:
            for path in self.programDir.iterdir():
                match = _INSTALL_ARTIFACT.fullmatch(path.name)
                if not match or not path.is_dir():
                    continue
                try:
                    modified = path.stat().st_mtime_ns
                except OSError:
                    modified = 0
                artifacts.append((modified, path, match))
        except OSError:
            return

        for _modified, path, match in sorted(
            artifacts, key=lambda item: item[0], reverse=True
        ):
            installDir = match.group("install")
            try:
                installDir = _safeInstallDir(installDir)
                target = _underRoot(self.programDir / installDir, self.programDir)
            except ApplicationStoreError:
                continue
            if match.group("kind") == "backup" and not target.exists():
                try:
                    path.replace(target)
                    continue
                except OSError:
                    pass
            cleanup.append(path)

        if cleanup:
            self._cleanupThread = threading.Thread(
                target=self._cleanupArtifacts,
                args=(tuple(cleanup),),
                daemon=True,
            )
            self._cleanupThread.start()

    @staticmethod
    def _cleanupArtifacts(paths) -> None:
        for path in paths:
            shutil.rmtree(path, ignore_errors=True)

    def _applicationRunning(self, target: Path) -> bool:
        running = False
        for launchKey, processes in tuple(self._launchedProcesses.items()):
            if launchKey[0] != target:
                continue
            active = [process for process in processes if process.poll() is None]
            if active:
                self._launchedProcesses[launchKey] = active
                running = True
            else:
                self._launchedProcesses.pop(launchKey, None)
        return running or bool(_runningExecutablesUnder(target))

    def _activateProcess(self, process) -> None:
        if self._activationStop.is_set():
            return
        for stalePid, staleWorker in tuple(self._activationThreads.items()):
            if not staleWorker.is_alive():
                self._activationThreads.pop(stalePid, None)
        pid = getattr(process, "pid", None)
        worker = self._activationThreads.get(pid)
        if worker is not None and worker.is_alive():
            return
        worker = _activateProcessWindow(
            process,
            self._activationStop,
            self._onLaunchFailure,
        )
        if worker is not None:
            self._activationThreads[pid] = worker

    def fetchCatalog(self, session=requests) -> dict:
        url = _httpsUrl(urljoin(self.apiBaseUrl, CATALOG_PATH.lstrip("/")))
        response = session.get(url, timeout=(10, 30))
        try:
            response.raise_for_status()
            if not isHttpsResponseChain(response, url):
                raise ApplicationStoreError("应用目录链接必须保持 HTTPS")
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("apps"), list):
                raise ApplicationStoreError("应用目录格式无效")
            return payload
        finally:
            response.close()

    def imagePath(self, url: str, session=requests) -> Path:
        return self.cache.get(url, session)

    def downloadPath(self, app: dict) -> Path:
        appId = int(app["id"])
        return APP_STORE_DOWNLOAD_DIR / f"{appId}-{self.architecture}.zip"

    def downloadUrl(self, app: dict) -> str:
        return urljoin(
            self.apiBaseUrl,
            f"app-store/apps/{int(app['id'])}/download"
            f"?arch={self.architecture}&token={uuid.uuid4().hex}",
        )

    def installZip(self, app: dict, zipPath: Path, cancelEvent=None) -> InstalledApplication:
        if cancelEvent is not None and cancelEvent.is_set():
            raise ApplicationStoreError("安装已取消")
        validateZip(zipPath)
        if cancelEvent is not None and cancelEvent.is_set():
            raise ApplicationStoreError("安装已取消")
        installDir = _safeInstallDir(app.get("install_dir"))
        target = _underRoot(self.programDir / installDir, self.programDir)
        try:
            appId = int(app["id"])
        except (KeyError, TypeError, ValueError) as error:
            raise ApplicationStoreError("应用编号无效") from error
        local = self.installed().get(appId)
        if local is not None and local.installDir != installDir:
            raise ApplicationStoreError(
                "应用安装目录已变更，请先在旧目录完成迁移"
            )
        staging = self.programDir / f".{installDir}.staging-{uuid.uuid4().hex}"
        backup = None
        staging.mkdir(parents=True, exist_ok=False)
        try:
            _extractZip(Path(zipPath), staging, cancelEvent)
            if cancelEvent is not None and cancelEvent.is_set():
                raise ApplicationStoreError("安装已取消")
            manifest = {
                "id": appId,
                "name": str(app.get("name", "")),
                "developer": str(app.get("developer", "")),
                "description": str(app.get("description", "")),
                "version": str(app.get("version", "")),
                "install_dir": installDir,
                "icon_url": str(app.get("icon_url", "")),
                "announcement": str(app.get("announcement", "")),
                "manifest_revision": _manifestRevision(
                    app.get("manifest_revision", 1)
                ),
                "open_action": app.get("open_action"),
                "presets": app.get("presets", []),
                "installed_architecture": self.architecture,
            }
            (staging / MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            with self._installedLock:
                if target.exists():
                    _assertNoLinks(target)
                    if not target.is_dir():
                        raise ApplicationStoreError("应用安装目录不是文件夹")
                    try:
                        owner = int(
                            json.loads(
                                (target / MANIFEST_NAME).read_text(encoding="utf-8")
                            )["id"]
                        )
                    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                        raise ApplicationStoreError(
                            "应用安装目录已被其他文件占用"
                        ) from None
                    if owner != appId:
                        raise ApplicationStoreError(
                            "应用安装目录已被其他软件占用"
                        )
                    if self._applicationRunning(target):
                        raise ApplicationStoreError(
                            "软件仍在运行，请完全退出后再更新"
                        )
                    backup = self.programDir / f".{installDir}.backup-{uuid.uuid4().hex}"
                    target.replace(backup)
                staging.replace(target)
                self._installedCache = None
                self._installedStamp = None
                self._installedCopies = {}
            if backup:
                shutil.rmtree(backup, ignore_errors=True)
                backup = None
        except Exception:
            with self._installedLock:
                if backup and not target.exists() and backup.exists():
                    backup.replace(target)
                self._installedCache = None
                self._installedStamp = None
                self._installedCopies = {}
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return InstalledApplication(
            manifest["id"], manifest["name"], manifest["version"], installDir, target, manifest
        )

    def installed(self) -> dict[int, InstalledApplication]:
        with self._installedLock:
            try:
                stamp = self.programDir.stat().st_mtime_ns
            except OSError:
                stamp = None
            if self._installedCache is not None and stamp == self._installedStamp:
                return dict(self._installedCache)

            result = {}
            copies = {}
            endStamp = stamp
            for _attempt in range(2):
                try:
                    startStamp = self.programDir.stat().st_mtime_ns
                except OSError:
                    startStamp = None
                result = {}
                copies = {}
                if self.programDir.exists():
                    directories = sorted(
                        self.programDir.iterdir(),
                        key=lambda path: path.name.casefold(),
                    )
                    for directory in directories:
                        isJunction = getattr(
                            directory, "is_junction", lambda: False
                        )()
                        if (
                            directory.name.startswith(".")
                            or not directory.is_dir()
                            or directory.is_symlink()
                            or isJunction
                        ):
                            continue
                        manifestPath = directory / MANIFEST_NAME
                        try:
                            installDir = _safeInstallDir(directory.name)
                            manifest = json.loads(
                                manifestPath.read_text(encoding="utf-8")
                            )
                            appId = int(manifest["id"])
                        except (
                            ApplicationStoreError,
                            OSError,
                            ValueError,
                            TypeError,
                            json.JSONDecodeError,
                            KeyError,
                        ):
                            continue
                        candidate = InstalledApplication(
                            appId,
                            str(manifest.get("name", "")),
                            str(manifest.get("version", "")),
                            installDir,
                            directory,
                            manifest,
                        )
                        copies.setdefault(appId, []).append(candidate)
                        previous = result.get(appId)
                        if previous is not None and versionKey(
                            candidate.version
                        ) <= versionKey(previous.version):
                            continue
                        result[appId] = candidate
                try:
                    endStamp = self.programDir.stat().st_mtime_ns
                except OSError:
                    endStamp = None
                if startStamp == endStamp:
                    break
            self._installedCache = result
            self._installedStamp = endStamp
            self._installedCopies = copies
            return dict(result)

    def uninstall(self, appOrInstallDir: dict | InstalledApplication | str) -> None:
        appId = None
        if isinstance(appOrInstallDir, InstalledApplication):
            installDir = appOrInstallDir.installDir
            appId = appOrInstallDir.appId
        elif isinstance(appOrInstallDir, dict):
            local = None
            try:
                appId = int(appOrInstallDir.get("id"))
                local = self.installed().get(appId)
            except (TypeError, ValueError):
                pass
            installDir = local.installDir if local else appOrInstallDir.get("install_dir")
        else:
            installDir = appOrInstallDir
        installDir = _safeInstallDir(installDir)
        target = _underRoot(self.programDir / installDir, self.programDir)
        tombstones = []
        with self._installedLock:
            self.installed()
            targets = [
                installed.path
                for installed in self._installedCopies.get(appId, ())
            ]
            if not targets:
                targets = [target]
            if any(
                path.exists() and self._applicationRunning(path)
                for path in targets
            ):
                raise ApplicationStoreError(
                    "软件仍在运行，请完全退出后再卸载"
                )
            try:
                for path in targets:
                    if not path.exists():
                        continue
                    tombstone = self.programDir / (
                        f".{path.name}.uninstall-{uuid.uuid4().hex}"
                    )
                    path.replace(tombstone)
                    tombstones.append((path, tombstone))
            except OSError as error:
                for original, tombstone in reversed(tombstones):
                    if tombstone.exists() and not original.exists():
                        try:
                            tombstone.replace(original)
                        except OSError:
                            pass
                raise ApplicationStoreError(
                    "软件仍在运行或文件被占用，请完全退出后重试"
                ) from error
            finally:
                self._installedCache = None
                self._installedStamp = None
                self._installedCopies = {}
        for _original, tombstone in tombstones:
            try:
                shutil.rmtree(tombstone)
            except OSError:
                # The visible installation is already removed atomically. A later
                # startup retries hidden artifact cleanup after file locks are gone.
                pass

    def mergeInstalled(self, apps: Iterable[dict]) -> list[dict]:
        installed = self.installed()
        result = []
        for app in apps:
            if not isinstance(app, dict):
                continue
            try:
                appId = int(app["id"])
            except (KeyError, TypeError, ValueError):
                continue
            item = dict(app)
            local = installed.pop(appId, None)
            item["presets"] = _presetList(item.get("presets"))
            packages = item.get("packages")
            if not isinstance(packages, dict):
                packages = {}
            else:
                packages = {
                    architecture: package
                    for architecture, package in packages.items()
                    if isinstance(package, dict)
                }
            item["packages"] = packages
            item["catalog_available"] = True
            item["installed"] = local is not None
            item["installed_version"] = local.version if local else ""
            item["installed_open_action"] = (
                local.metadata.get("open_action") if local else None
            )
            item["installed_presets"] = (
                _presetList(local.metadata.get("presets")) if local else []
            )
            item["installed_manifest_revision"] = (
                _manifestRevision(local.metadata.get("manifest_revision", 1))
                if local
                else 0
            )
            package = packages.get(self.architecture)
            item["architecture_supported"] = bool(
                package and package.get("enabled")
            )
            item["update_available"] = bool(
                local
                and item["architecture_supported"]
                and (
                    isUpdateAvailable(local.version, str(item.get("version", "")))
                    or _manifestRevision(item.get("manifest_revision", 1))
                        > item["installed_manifest_revision"]
                )
            )
            result.append(item)
        for local in installed.values():
            metadata = local.metadata
            presets = _presetList(metadata.get("presets"))
            result.append(
                {
                    "id": local.appId,
                    "name": local.name,
                    "developer": str(metadata.get("developer", "")),
                    "description": str(metadata.get("description", "")),
                    "version": local.version,
                    "install_dir": local.installDir,
                    "icon_url": str(metadata.get("icon_url", "")),
                    "announcement": str(metadata.get("announcement", "")),
                    "manifest_revision": _manifestRevision(
                        metadata.get("manifest_revision", 1)
                    ),
                    "open_action": metadata.get("open_action"),
                    "installed_open_action": metadata.get("open_action"),
                    "presets": presets,
                    "packages": {},
                    "recommended": False,
                    "recommended_order": None,
                    "catalog_available": False,
                    "installed": True,
                    "installed_version": local.version,
                    "installed_presets": presets,
                    "installed_manifest_revision": _manifestRevision(
                        metadata.get("manifest_revision", 1)
                    ),
                    "architecture_supported": True,
                    "update_available": False,
                }
            )
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
        if not isinstance(action, dict):
            raise ApplicationStoreError("该应用没有可执行的打开动作")
        actionType = str(action.get("type", "")).lower()
        target = str(action.get("target", "")).strip()
        arguments = action.get("arguments") or action.get("action_arguments") or {}
        if _hasControlCharacters(target) or _hasControlCharacters(arguments):
            raise ApplicationStoreError("动作参数无效")
        if actionType == "program":
            targetParts = _programTargetParts(target)
            programPath = _underRoot(installPath.joinpath(*targetParts), installPath)
            args = arguments.get("args", []) if isinstance(arguments, dict) else []
            if not isinstance(args, list) or any(
                not isinstance(value, str) or _hasControlCharacters(value)
                for value in args
            ):
                raise ApplicationStoreError("程序参数无效")
            with self._installedLock:
                if not programPath.is_file() or programPath.is_symlink():
                    raise ApplicationStoreError("程序文件不存在")
                launchKey = (installPath, programPath, tuple(args))
                processes = self._launchedProcesses.setdefault(launchKey, [])
                processes[:] = [
                    process for process in processes if process.poll() is None
                ]
                if processes:
                    process = processes[-1]
                    self._activateProcess(process)
                    return process
                process = subprocess.Popen(
                    [str(programPath), *args],
                    cwd=installPath,
                    env=_externalProcessEnvironment(),
                )
                processes.append(process)
            self._activateProcess(process)
            return process
        if actionType == "url":
            return webbrowser.open(_httpsUrl(target))
        if actionType == "uri":
            try:
                parsed = urlparse(target)
            except ValueError as error:
                raise ApplicationStoreError("系统协议动作无效") from error
            if (
                len(parsed.scheme) < 2
                or parsed.scheme.lower() in _DANGEROUS_SCHEMES
                or any(char in target for char in "\r\n\x00")
            ):
                raise ApplicationStoreError("系统协议动作被拒绝")
            if hasattr(os, "startfile"):
                os.startfile(target)
                return True
            return webbrowser.open(target)
        raise ApplicationStoreError("未知的打开动作")


def downloadWorker(app: dict, store: ApplicationStore):
    """Create the shared Ghost-style worker with ZIP validation."""
    from app.common.update_download import UpdateDownloadWorker

    package = (app.get("packages") or {}).get(store.architecture) or {}
    expectedSha256 = str(package.get("sha256", "")).strip().lower()
    if not _validSha256(expectedSha256):
        expectedSha256 = ""
    target = store.downloadPath(app)
    target.parent.mkdir(parents=True, exist_ok=True)
    return UpdateDownloadWorker(
        store.downloadUrl(app),
        target,
        validator=validateZip,
        requireHttps=True,
        maxBytes=MAX_ZIP_COMPRESSED,
        expectedSha256=expectedSha256 or None,
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
    "beginAppStorePackageOperation",
    "clearAppStoreCache",
    "downloadWorker",
    "endAppStorePackageOperation",
    "isUpdateAvailable",
    "appStoreImageCache",
    "validateZip",
    "versionKey",
]
