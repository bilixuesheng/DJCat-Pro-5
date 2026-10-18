"""Application Install Location 与 Application Relocation 的规则，不涉及界面。

位置存在 `cfg.appInstallLocation`：空值是默认的 `<App Data Directory>\\Program`，随 Storage
Migration 一起搬；自定义位置存绝对路径，Storage Migration 不碰它。Application Relocation
全有或全无：先把全部应用搬到新位置（同一个盘直接改名，跨盘先复制进临时文件夹再改名），
全部到位后才由界面线程改配置，最后删旧文件。开始前 `cfg.appRelocation` 记下旧位置、新位置
和要搬的文件夹；配置里的位置已经是新位置就算提交了，中途退出或断电时下次启动按这一点收尾
到其中一边。理由见 `docs/adr/0010-application-install-location.md`。
"""

import errno
import json
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from app.config.cfg import cfg
from app.config.paths import APP_DATA_DIR, APP_DIR, PROGRAM_DIR, rebasePaths
from app.platform.processes import processesUnder, terminateProcessesUnder
from app.signal_bus import signalBus

MANIFEST_NAME = ".djcat-app.json"
# BUILTIN\Users：用 SID 而不是组名，组名随系统语言变。
USERS_SID = "S-1-5-32-545"
COPY_CHUNK = 1024 * 1024
PROGRESS_INTERVAL = 0.1

IDLE = ""
CHECKING = "checking"
RELOCATING = "relocating"
CLEANING = "cleaning"

_state = IDLE


class RelocationError(Exception):
    """Application Relocation 失败。clean 为假时新位置可能还留着没删掉的半成品。"""

    def __init__(self, message: str, clean: bool = True):
        super().__init__(message)
        self.clean = clean


class RelocationCanceled(Exception):
    pass


@dataclass(frozen=True)
class ApplicationFolder:
    name: str
    title: str


def installLocation() -> Path:
    value = cfg.appInstallLocation.value
    if isinstance(value, str) and value.strip():
        return Path(value)
    return PROGRAM_DIR


def isDefaultInstallLocation() -> bool:
    value = cfg.appInstallLocation.value
    return not (isinstance(value, str) and value.strip())


def installLocationAvailable(location: Path | None = None) -> bool:
    """默认位置随时可以建出来；自定义位置不重建，文件夹不在就是不可用。"""
    if location is None:
        if isDefaultInstallLocation():
            return True
        location = installLocation()
    if _key(location) == _key(PROGRAM_DIR):
        return True
    return Path(location).is_dir()


def relocationState() -> str:
    return _state


def setRelocationState(state: str) -> None:
    global _state
    if state == _state:
        return
    _state = state
    signalBus.installLocationStateChanged.emit(state)


def applicationsBlocked() -> bool:
    """Application Relocation 搬动文件期间，不能安装、更新、卸载或打开任何 Application。"""
    return _state == RELOCATING


def _key(path) -> str:
    return os.path.normcase(str(Path(path).resolve(strict=False)))


def samePath(first, second) -> bool:
    return _key(first) == _key(second)


def _within(path, parent) -> bool:
    child = _key(path)
    root = _key(parent).rstrip(os.sep)
    return child == root or child.startswith(root + os.sep)


def _isNetworkPath(path: Path) -> bool:
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    if os.name != "nt":
        return False
    try:
        import ctypes

        driveRemote = 4
        return ctypes.windll.kernel32.GetDriveTypeW(Path(path).anchor) == driveRemote
    except (AttributeError, OSError):
        return False


def targetProblem(target: Path, current: Path) -> str | None:
    """新位置不能用的原因；能用时返回 None。默认位置只经「重置」回去，不走这里。"""
    target = Path(target)
    if _isNetworkPath(target):
        return "不支持网络位置。"
    resolved = target.resolve(strict=False)
    if resolved == Path(resolved.anchor):
        return "不能直接选择磁盘根目录，请在其中新建一个文件夹。"
    # Client Update 会把整个程序目录换掉，清理 Cache 会清空 AppStoreCache。
    if _within(target, APP_DIR) or _within(target, APP_DATA_DIR):
        return "不能选择电教猫的程序目录或数据目录。"
    if _within(target, current) or _within(current, target):
        return "不能选择当前位置，或当前位置里面、外面的文件夹。"
    return None


def elevationForbidden(path: Path) -> bool:
    """这些系统文件夹不为普通用户取得修改权限，否则等于放开整片系统目录。"""
    if os.name != "nt":
        return False
    environment = os.environ
    windows = environment.get("SystemRoot") or environment.get("windir")
    if windows and _within(path, windows):
        return True
    roots = [
        environment.get(name)
        for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData")
    ]
    public = environment.get("PUBLIC")
    if public:
        roots.append(str(Path(public).parent))
    return any(root and _key(path) == _key(root) for root in roots)


def isWritable(path: Path) -> bool:
    """在 path 里建、改名、删一个临时文件夹和文件，全成功才算能写。"""
    path = Path(path)
    probe = path / f".djcat-write-test-{os.getpid()}-{time.monotonic_ns()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.mkdir()
        (probe / "probe").write_bytes(b"")
        renamed = probe.with_name(f"{probe.name}-renamed")
        probe.rename(renamed)
        probe = renamed
        return True
    except OSError:
        return False
    finally:
        _removeTree(probe)


def isEmptyFolder(path: Path) -> bool:
    try:
        return not any(Path(path).iterdir())
    except FileNotFoundError:
        return True
    except OSError:
        return False


def grantUsersModify(path: Path, window: int | None = None) -> bool | None:
    """以管理员身份运行 icacls，给 Users 组授"修改"权限并继承到下面所有内容。

    返回 True 表示授权成功，False 表示失败，None 表示用户在 UAC 里点了「否」。标准用户
    在 UAC 里输入的是管理员账号，提权出来的进程以那个管理员的身份运行，所以授给 Users 组，
    而不是提权进程眼中的"当前用户"。
    """
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    seeMaskNoCloseProcess = 0x00000040
    seeMaskNoConsole = 0x00008000
    errorCancelled = 1223
    infinite = 0xFFFFFFFF
    systemRoot = os.environ.get("SystemRoot") or r"C:\Windows"
    # 结尾的反斜杠会把后面的引号转义掉；磁盘根目录本来就不能选。
    target = str(Path(path)).rstrip("\\/")
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(ShellExecuteInfo)
    info.fMask = seeMaskNoCloseProcess | seeMaskNoConsole
    info.hwnd = window or None
    info.lpVerb = "runas"
    info.lpFile = str(Path(systemRoot) / "System32" / "icacls.exe")
    info.lpParameters = f'"{target}" /grant *{USERS_SID}:(OI)(CI)M /Q'
    info.nShow = 0

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = (ctypes.POINTER(ShellExecuteInfo),)
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    ole32 = ctypes.windll.ole32
    # ShellExecuteEx 可能经由 COM 处理，在后台线程里调用前先初始化。
    initialized = ole32.CoInitializeEx(None, 0x2 | 0x4) >= 0
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            if ctypes.get_last_error() == errorCancelled:
                return None
            return False
        if not info.hProcess:
            return False
        try:
            kernel32.WaitForSingleObject(info.hProcess, infinite)
            exitCode = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exitCode)):
                return False
            return exitCode.value == 0
        finally:
            kernel32.CloseHandle(info.hProcess)
    finally:
        if initialized:
            ole32.CoUninitialize()


def _isLink(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def applicationFolders(location: Path) -> list[ApplicationFolder]:
    """location 下带清单、能被应用市场识别的安装目录。"""
    try:
        directories = sorted(
            Path(location).iterdir(), key=lambda path: path.name.casefold()
        )
    except OSError:
        return []
    folders = []
    for directory in directories:
        if directory.name.startswith(".") or _isLink(directory) or not directory.is_dir():
            continue
        try:
            manifest = json.loads(
                (directory / MANIFEST_NAME).read_text(encoding="utf-8")
            )
            int(manifest["id"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            continue
        folders.append(
            ApplicationFolder(directory.name, str(manifest.get("name") or directory.name))
        )
    return folders


def conflictingNames(folders, target: Path) -> list[str]:
    target = Path(target)
    return [
        folder.name
        for folder in folders
        if os.path.lexists(target / folder.name)
    ]


def sameVolume(first: Path, second: Path) -> bool:
    try:
        return os.stat(first).st_dev == os.stat(second).st_dev
    except OSError:
        return False


def folderSize(path: Path) -> int:
    total = 0
    stack = [Path(path)]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def freeSpace(path: Path) -> int:
    return shutil.disk_usage(path).free


def runningApplications(location: Path, folders) -> list[str]:
    """正在运行的 Application 名称：进程的可执行文件位于哪个安装目录，就算哪个应用。"""
    root = Path(location).resolve(strict=False)
    titles = {os.path.normcase(folder.name): folder.title for folder in folders}
    running = []
    for _pid, executable in processesUnder(root):
        try:
            name = executable.relative_to(root).parts[0]
        except (ValueError, IndexError):
            continue
        title = titles.get(os.path.normcase(name))
        if title and title not in running:
            running.append(title)
    return running


def formatSize(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            break
        value /= 1024
    return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"


def _clearReadOnly(function, path, _error):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _removeTree(path: Path) -> bool:
    """删掉 path；只读文件先去掉只读属性。返回删完以后它是否已经不在了。"""
    path = Path(path)
    if not os.path.lexists(path):
        return True
    try:
        if path.is_dir() and not _isLink(path):
            shutil.rmtree(path, onexc=_clearReadOnly)
        else:
            path.unlink()
    except OSError:
        pass
    return not os.path.lexists(path)


def _describe(error: OSError) -> str:
    if error.errno == errno.ENOSPC or getattr(error, "winerror", None) in (39, 112):
        return "新位置所在磁盘空间不足。"
    if isinstance(error, PermissionError) or getattr(error, "winerror", None) in (5, 32, 33):
        name = error.filename or ""
        return f"有文件正被其他程序占用：{name}。" if name else "有文件正被其他程序占用。"
    return f"{error.strerror or error}。"


def _stagingName(name: str, token: str) -> str:
    return f".{name}.relocating-{token}"


class _Copier:
    def __init__(self, total, progress, cancelEvent):
        self.done = 0
        self.total = total
        self.progress = progress
        self.cancelEvent = cancelEvent
        self._reportedAt = 0.0

    def report(self, force=False):
        if self.progress is None:
            return
        now = time.monotonic()
        if force or now - self._reportedAt >= PROGRESS_INTERVAL:
            self._reportedAt = now
            self.progress(self.done, self.total)

    def checkCanceled(self):
        if self.cancelEvent is not None and self.cancelEvent.is_set():
            raise RelocationCanceled()

    def copyTree(self, source: Path, target: Path):
        target.mkdir()
        for entry in os.scandir(source):
            self.checkCanceled()
            path = Path(entry.path)
            if entry.is_symlink() or _isLink(path):
                raise RelocationError(f"应用文件夹里有链接，无法迁移：{path}。")
            if entry.is_dir():
                self.copyTree(path, target / entry.name)
            else:
                self.copyFile(path, target / entry.name)
        shutil.copystat(source, target)

    def copyFile(self, source: Path, target: Path):
        with open(source, "rb") as reader, open(target, "xb") as writer:
            while True:
                self.checkCanceled()
                chunk = reader.read(COPY_CHUNK)
                if not chunk:
                    break
                writer.write(chunk)
                self.done += len(chunk)
                self.report()
        shutil.copystat(source, target)


def closeRunningApplications(location: Path) -> None:
    """强制结束可执行文件位于 location 下的进程；结束不了就抛出 RelocationError。"""
    remaining = terminateProcessesUnder(Path(location))
    if remaining:
        raise RelocationError(
            f"有程序无法关闭：{remaining[0].name}。请手动退出后重试。"
        )


def relocate(
    source: Path,
    target: Path,
    names,
    token: str,
    totalBytes: int = 0,
    progress=None,
    cancelEvent=None,
) -> None:
    """把 source 下的 names 搬到 target 下，全有或全无。

    progress(done, total) 只在跨盘复制时调用；同一个盘直接改名，没有可报的进度。失败时
    先撤回已经搬过去的部分，再抛出 RelocationError。
    """
    source = Path(source)
    target = Path(target)
    names = list(names)
    closeRunningApplications(source)
    if sameVolume(source, target):
        _renameAll(source, target, names, cancelEvent)
        return
    copier = _Copier(totalBytes, progress, cancelEvent)
    staged = []
    placed = []
    try:
        for name in names:
            copier.checkCanceled()
            staging = target / _stagingName(name, token)
            staged.append(staging)
            copier.copyTree(source / name, staging)
        copier.report(force=True)
        for name, staging in zip(names, staged):
            staging.rename(target / name)
            placed.append(target / name)
    except (OSError, RelocationError, RelocationCanceled) as error:
        clean = all([_removeTree(path) for path in staged + placed])
        if isinstance(error, RelocationError):
            raise RelocationError(str(error), clean) from error
        if isinstance(error, RelocationCanceled):
            raise RelocationError("迁移被中断。", clean) from error
        raise RelocationError(_describe(error), clean) from error


def _renameAll(source: Path, target: Path, names, cancelEvent) -> None:
    moved = []
    try:
        for name in names:
            if cancelEvent is not None and cancelEvent.is_set():
                raise RelocationCanceled()
            destination = target / name
            # POSIX 上改名可以覆盖空文件夹；同名冲突在开始前查过，这里再挡一次。
            if os.path.lexists(destination):
                raise FileExistsError(errno.EEXIST, "新位置已有同名文件夹", str(destination))
            (source / name).rename(destination)
            moved.append(name)
    except (OSError, RelocationCanceled) as error:
        clean = True
        for name in reversed(moved):
            try:
                (target / name).rename(source / name)
            except OSError:
                clean = False
        message = "迁移被中断。" if isinstance(error, RelocationCanceled) else _describe(error)
        raise RelocationError(message, clean) from error


def removeOldFolders(source: Path, target: Path, names) -> list[Path]:
    """删掉旧位置里已经搬到 target 的安装目录，返回删不掉的那些。"""
    leftovers = []
    for name in names:
        folder = Path(source) / name
        # 新位置里没有这一份就不删旧的，宁可留着也不能把唯一的一份删掉。
        if not (Path(target) / name).is_dir():
            continue
        if not _removeTree(folder):
            leftovers.append(folder)
    return leftovers


def relocationJournal(source: Path, target: Path, names, token: str) -> dict:
    return {
        "source": str(source),
        "target": str(target),
        "folders": list(names),
        "token": token,
    }


def _journalParts(journal):
    if not isinstance(journal, dict):
        return None
    source = journal.get("source")
    target = journal.get("target")
    names = journal.get("folders")
    token = journal.get("token")
    if not (
        isinstance(source, str)
        and source
        and isinstance(target, str)
        and target
        and isinstance(token, str)
        and isinstance(names, list)
        and all(isinstance(name, str) and name and "/" not in name and "\\" not in name for name in names)
    ):
        return None
    return Path(source), Path(target), names, token


def journalCommitted(journal) -> bool:
    parts = _journalParts(journal)
    return parts is not None and samePath(installLocation(), parts[1])


def recoverRelocation(journal) -> bool:
    """把上次中断的 Application Relocation 收尾到其中一边；返回 True 表示可以删掉记录。

    配置里的位置已经是新位置，就算提交了：删掉旧位置里剩下的。否则退回旧位置：同一个盘
    改过名的改回去，跨盘复制的半成品删掉。旧位置暂时不可用（U 盘没插）时留着记录下次再试。
    """
    parts = _journalParts(journal)
    if parts is None:
        return True
    source, target, names, token = parts
    if samePath(installLocation(), target):
        if not source.is_dir():
            return True
        return not removeOldFolders(source, target, names)
    if not source.is_dir():
        return False
    if not target.is_dir():
        return all((source / name).exists() for name in names)
    done = True
    for name in names:
        done = _removeTree(target / _stagingName(name, token)) and done
        original = source / name
        moved = target / name
        if original.exists():
            # 开始前查过新位置没有同名文件夹，这时在那里的只可能是这次复制过去的。
            done = _removeTree(moved) and done
        elif moved.exists():
            try:
                moved.rename(original)
            except OSError:
                done = False
    return done


def _configItems():
    from qfluentwidgets import ConfigItem

    for name in dir(type(cfg)):
        item = getattr(type(cfg), name)
        if isinstance(item, ConfigItem):
            yield item


def commitInstallLocation(target: Path | None, rebase: bool) -> None:
    """把 Application Install Location 改成 target（None 为默认位置），一次存盘。

    rebase 为真时（应用确实搬过去了），配置里落在旧位置下的绝对路径一并改到新位置，规则与
    Storage Migration 相同；迁移记录和位置本身不在改写之列。只能在界面线程里调用。
    """
    source = installLocation()
    location = PROGRAM_DIR if target is None else Path(target)
    if rebase:
        for item in _configItems():
            if item is cfg.appInstallLocation or item is cfg.appRelocation:
                continue
            value = item.value
            rebased = rebasePaths(value, source, location)
            if rebased != value:
                cfg.set(item, rebased, save=False)
    cfg.set(cfg.appInstallLocation, "" if target is None else str(target), save=False)
    cfg.save()
