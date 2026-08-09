import hashlib
import json
import re
import shutil
import stat
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices, QImage

from app.config.paths import APP_DATA_DIR, APP_DIR


CATALOG_API = "https://api.djcatpro.top/app-store/catalog"
MANIFEST_NAME = ".djcat-app.json"
PROGRAM_DIR = APP_DIR / "Program"
APP_STORE_TEMP_DIR = APP_DATA_DIR / "AppStoreTemp"
APP_STORE_CACHE_DIR = APP_DATA_DIR / "AppStoreCache"
INSTALL_DIR_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,64}")
TRANSACTION_DIR_PATTERN = re.compile(
    r"^\.(?P<install>[A-Za-z0-9._-]{1,64})\."
    r"(?P<kind>installing|backup|removing)-[0-9a-f]+$"
)


def _installDir(value: str) -> str:
    value = str(value).strip()
    if not INSTALL_DIR_PATTERN.fullmatch(value) or value in {".", ".."}:
        raise ValueError("安装目录名不安全")
    return value


def _zipPath(info: zipfile.ZipInfo) -> tuple[str, ...]:
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    mode = info.external_attr >> 16
    if (
        not name
        or path.is_absolute()
        or re.match(r"^[A-Za-z]:", name)
        or ".." in path.parts
        or any(":" in part for part in path.parts)
        or stat.S_ISLNK(mode)
    ):
        raise ValueError(f"ZIP 包含不安全路径：{info.filename}")
    return tuple(part for part in path.parts if part not in {"", "."})


def extractPackage(archivePath: Path, destination: Path) -> None:
    archivePath = Path(archivePath)
    destination = Path(destination)
    try:
        archive = zipfile.ZipFile(archivePath)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("下载文件不是有效的 ZIP 包") from error

    with archive:
        entries = [(info, _zipPath(info)) for info in archive.infolist()]
        fileParts = [parts for info, parts in entries if not info.is_dir()]
        if not fileParts:
            raise ValueError("ZIP 包中没有可安装文件")
        firstParts = {parts[0].casefold() for parts in fileParts if len(parts) > 1}
        stripTopLevel = (
            len(firstParts) == 1 and all(len(parts) > 1 for parts in fileParts)
        )

        normalized = set()
        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        for info, parts in entries:
            relativeParts = parts[1:] if stripTopLevel else parts
            if not relativeParts:
                continue
            relative = Path(*relativeParts)
            key = str(relative).replace("\\", "/").casefold()
            if key in normalized:
                raise ValueError(f"ZIP 包含冲突路径：{relative}")
            normalized.add(key)
            target = (destination / relative).resolve()
            if target != root and root not in target.parents:
                raise ValueError(f"ZIP 包含不安全路径：{info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _containsLink(directory: Path) -> bool:
    if not directory.exists():
        return False
    isJunction = getattr(directory, "is_junction", lambda: False)
    if directory.is_symlink() or isJunction():
        return True
    for path in directory.rglob("*"):
        isJunction = getattr(path, "is_junction", lambda: False)
        if path.is_symlink() or isJunction():
            return True
    return False


def recoverInterruptedInstalls(programDir: Path = PROGRAM_DIR) -> None:
    programDir = Path(programDir)
    if not programDir.is_dir():
        return
    transactions = {}
    for directory in programDir.iterdir():
        match = TRANSACTION_DIR_PATTERN.fullmatch(directory.name)
        if not match or not directory.is_dir() or _containsLink(directory):
            continue
        installDir = _installDir(match.group("install"))
        transactions.setdefault(
            installDir, {"backup": [], "installing": [], "removing": []}
        )[match.group("kind")].append(directory)

    for installDir, paths in transactions.items():
        target = programDir / installDir
        recoverable = sorted(
            paths["backup"], key=lambda path: path.stat().st_mtime_ns, reverse=True
        )
        recoverable += sorted(
            paths["removing"], key=lambda path: path.stat().st_mtime_ns, reverse=True
        )
        if not target.exists() and recoverable:
            recoverable.pop(0).rename(target)
        if target.is_dir():
            for path in recoverable + paths["installing"]:
                shutil.rmtree(path, ignore_errors=True)


def _writeManifest(directory: Path, application: dict) -> None:
    manifest = {
        key: application[key]
        for key in (
            "id",
            "name",
            "developer",
            "description",
            "version",
            "icon_url",
            "install_dir",
            "open_action",
            "components",
        )
        if key in application
    }
    manifest["install_dir"] = _installDir(application["install_dir"])
    temporary = directory / f"{MANIFEST_NAME}.tmp"
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(directory / MANIFEST_NAME)


def installPackage(
    archivePath: Path,
    application: dict,
    *,
    programDir: Path = PROGRAM_DIR,
    tempDir: Path = APP_STORE_TEMP_DIR,
) -> Path:
    installDir = _installDir(application.get("install_dir", ""))
    programDir = Path(programDir)
    tempDir = Path(tempDir)
    programDir.mkdir(parents=True, exist_ok=True)
    tempDir.mkdir(parents=True, exist_ok=True)
    recoverInterruptedInstalls(programDir)
    target = programDir / installDir
    if target.exists() and _containsLink(target):
        raise ValueError("现有安装目录包含链接，无法安全更新")

    staging = Path(tempfile.mkdtemp(prefix="extract-", dir=tempDir))
    token = uuid.uuid4().hex
    candidate = programDir / f".{installDir}.installing-{token}"
    backup = programDir / f".{installDir}.backup-{token}"
    targetMoved = False
    try:
        extractPackage(archivePath, staging)
        if target.exists():
            shutil.copytree(target, candidate)
        else:
            candidate.mkdir()
        shutil.copytree(staging, candidate, dirs_exist_ok=True)
        _writeManifest(candidate, application)

        if target.exists():
            target.rename(backup)
            targetMoved = True
        candidate.rename(target)
        targetMoved = False
    except Exception:
        if targetMoved and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(candidate, ignore_errors=True)

    shutil.rmtree(backup, ignore_errors=True)
    return target


def installedApplications(programDir: Path = PROGRAM_DIR) -> list[dict]:
    programDir = Path(programDir)
    if not programDir.is_dir():
        return []
    try:
        recoverInterruptedInstalls(programDir)
    except OSError:
        pass
    applications = []
    for directory in programDir.iterdir():
        manifestPath = directory / MANIFEST_NAME
        if not directory.is_dir() or not manifestPath.is_file():
            continue
        try:
            application = json.loads(manifestPath.read_text(encoding="utf-8"))
            if (
                int(application["id"]) < 1
                or _installDir(application["install_dir"]) != directory.name
            ):
                continue
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            continue
        applications.append(application)
    return sorted(applications, key=lambda app: (app.get("name", "").casefold(), app["id"]))


def uninstallApplication(
    installDir: str, *, programDir: Path = PROGRAM_DIR
) -> None:
    installDir = _installDir(installDir)
    programDir = Path(programDir)
    target = programDir / installDir
    if not (target / MANIFEST_NAME).is_file():
        raise ValueError("未找到受电教猫管理的安装目录")
    quarantine = programDir / f".{installDir}.removing-{uuid.uuid4().hex}"
    target.rename(quarantine)
    try:
        shutil.rmtree(quarantine)
    except Exception:
        if quarantine.exists() and not target.exists():
            quarantine.rename(target)
        raise


def fetchCatalog() -> dict | None:
    try:
        response = requests.get(CATALOG_API, timeout=(5, 15))
        response.raise_for_status()
        catalog = response.json()
        if not isinstance(catalog.get("apps"), list) or not isinstance(
            catalog.get("ads"), list
        ):
            return None
        return catalog
    except (requests.RequestException, TypeError, ValueError, AttributeError):
        return None


def downloadPackage(
    url: str,
    *,
    tempDir: Path = APP_STORE_TEMP_DIR,
    progress=None,
    cancelEvent: threading.Event | None = None,
) -> Path:
    url = _httpsUrl(url)
    tempDir = Path(tempDir)
    tempDir.mkdir(parents=True, exist_ok=True)
    target = tempDir / f"package-{uuid.uuid4().hex}.zip"
    partial = target.with_suffix(".zip.part")
    try:
        with requests.get(url, stream=True, timeout=(10, 30)) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            with partial.open("wb") as output:
                for chunk in response.iter_content(64 * 1024):
                    if cancelEvent is not None and cancelEvent.is_set():
                        raise InterruptedError("下载已取消")
                    if not chunk:
                        continue
                    output.write(chunk)
                    downloaded += len(chunk)
                    if progress is not None:
                        progress(downloaded, total)
        if not zipfile.is_zipfile(partial):
            raise ValueError("下载文件不是有效的 ZIP 包")
        partial.replace(target)
        return target
    except Exception:
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise


def _httpsUrl(value: str) -> str:
    parsed = urlparse(str(value).strip())
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("网址动作不是有效的 HTTPS 地址")
    return parsed.geturl()


def resolveProgramAction(application: dict, action: dict) -> tuple[Path, list[str], Path]:
    installDir = _installDir(application.get("install_dir", ""))
    relative = str(action.get("target", "")).replace("\\", "/")
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(":" in part for part in path.parts)
        or path.suffix.lower() != ".exe"
    ):
        raise ValueError("程序动作路径不安全")
    root = (PROGRAM_DIR / installDir).resolve()
    executable = (root / Path(*path.parts)).resolve()
    if root not in executable.parents or not executable.is_file():
        raise ValueError("程序文件不存在")
    arguments = action.get("arguments", [])
    if not isinstance(arguments, list) or not all(
        isinstance(argument, str) for argument in arguments
    ):
        raise ValueError("程序参数无效")
    return executable, arguments, root


def executeAction(application: dict, action: dict) -> None:
    actionType = action.get("type")
    if actionType == "url":
        if not QDesktopServices.openUrl(QUrl(_httpsUrl(action.get("target", "")))):
            raise OSError("无法打开网址")
        return
    if actionType != "program":
        raise ValueError("不支持的动作类型")
    executable, arguments, workingDirectory = resolveProgramAction(application, action)
    result = QProcess.startDetached(str(executable), arguments, str(workingDirectory))
    started = result[0] if isinstance(result, tuple) else bool(result)
    if not started:
        raise OSError("无法启动程序")


def cachedImagePath(url: str, cacheDir: Path = APP_STORE_CACHE_DIR) -> Path:
    url = _httpsUrl(url)
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        suffix = ".img"
    return Path(cacheDir) / f"{hashlib.sha256(url.encode()).hexdigest()}{suffix}"


def fetchCachedImage(url: str, cacheDir: Path = APP_STORE_CACHE_DIR) -> Path | None:
    try:
        target = cachedImagePath(url, cacheDir)
    except ValueError:
        return None
    if target.is_file() and not QImage(str(target)).isNull():
        return target
    try:
        response = requests.get(url, timeout=(5, 20))
        response.raise_for_status()
        image = QImage.fromData(response.content)
        if image.isNull():
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(f"{target.suffix}.tmp")
        temporary.write_bytes(response.content)
        temporary.replace(target)
        return target
    except (OSError, requests.RequestException):
        return None


def clearImageCache(cacheDir: Path = APP_STORE_CACHE_DIR) -> int:
    cacheDir = Path(cacheDir)
    if not cacheDir.exists():
        return 0
    size = 0
    for path in cacheDir.rglob("*"):
        try:
            if path.is_file():
                size += path.stat().st_size
        except OSError:
            continue
    shutil.rmtree(cacheDir)
    return size
