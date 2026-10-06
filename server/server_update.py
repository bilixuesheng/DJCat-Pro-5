"""Server Update：管理员在 Admin Console 中把服务端换成 main 上更新的 Server Version。

为什么由服务端自己下载、替换并 SIGHUP，而不是 CI 部署，见
docs/adr/0006-server-self-update.md。
"""

import io
import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import requests
from flask import Blueprint, jsonify, make_response, render_template, request, url_for

try:
    import fcntl
except ImportError:  # Windows：只在本地开发和测试时出现
    fcntl = None
    import msvcrt

try:
    from .version import SERVER_COMMIT, SERVER_VERSION
except ImportError:
    from version import SERVER_COMMIT, SERVER_VERSION

REPOSITORY = "bilixuesheng/DJCat-Pro-5"
_API = f"https://api.github.com/repos/{REPOSITORY}"
_VERSION_PATTERN = re.compile(r'^SERVER_VERSION\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.MULTILINE)
_COMMIT = r"[0-9a-f]{40}"
_COMMIT_PATTERN = re.compile(rf'^SERVER_COMMIT\s*=\s*"({_COMMIT})"', re.MULTILINE)
_CODELOAD = f"https://codeload.github.com/{REPOSITORY}/tar.gz"
# 宝塔与运行环境放在项目目录里的东西：包里即使出现同名路径也不写入。
_PROTECTED = {".venv", "data", "gunicorn_conf.py", "uwsgi.ini", "server.zip", "__pycache__"}
_FETCH_TIMEOUT = (10, 60)
_TRIAL_IMPORT_TIMEOUT = 60
_DATABASE_BACKUPS = 3
_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024


class ServerUpdateError(Exception):
    """一次 Server Update 停在了哪一步，以及原因。"""

    def __init__(self, step, detail):
        super().__init__(f"{step}失败：{detail}")
        self.step = step
        self.detail = detail


@dataclass(frozen=True)
class ServerUpdateCheck:
    version: str
    commit: str
    titles: list


@dataclass(frozen=True)
class ServerUpdateResult:
    version: str
    commit: str
    # SIGHUP 只换 worker，gunicorn 主进程本身要到宝塔面板重启才会换成新版本。
    gunicornChanged: bool = False


def _fetch(url, accept=None):
    headers = {"Accept": accept} if accept else {}
    try:
        with requests.get(url, headers=headers, timeout=_FETCH_TIMEOUT, stream=True) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > _MAX_DOWNLOAD_BYTES:
                    raise ServerUpdateError("下载", "文件超过 64 MB")
            return bytes(data)
    except requests.RequestException as error:
        raise ServerUpdateError("下载", f"{url}：{error}") from error


def _run(step, command, timeout=None, **options):
    """跑一个子进程；失败或超时就让这次 Server Update 停在 step，带上输出的末尾。"""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **options,
        )
    except subprocess.TimeoutExpired as error:
        raise ServerUpdateError(step, f"{timeout} 秒内没有完成") from error
    if completed.returncode != 0:
        raise ServerUpdateError(step, _outputTail(completed.stdout + completed.stderr))


def _runPip(requirements):
    """以运行服务的用户把依赖装进当前虚拟环境。"""
    # 不设超时：被杀到一半的 pip 会留下装了一半的 .venv；pip 自己有网络超时和重试上限。
    _run(
        "依赖",
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements)],
    )


def _gunicornRequirement(text):
    return sorted(
        line.strip()
        for line in text.splitlines()
        if re.match(r"\s*gunicorn\b", line, re.IGNORECASE)
    )


def _workerRestarter():
    """在 gunicorn 下返回一个给主进程发 SIGHUP 的函数，否则返回 None。

    SIGHUP 让主进程起新 worker 重新导入代码、再平滑停掉旧的；前提是没开 preload_app。
    """
    master = os.getppid()
    try:
        commandLine = Path(f"/proc/{master}/cmdline").read_bytes()
    except OSError:
        return None
    if b"gunicorn" not in commandLine:
        return None
    try:
        # 主进程以 root 运行、worker 降为 www 时没有权限发信号，那就请管理员手动重启。
        os.kill(master, 0)
    except OSError:
        return None
    return lambda: os.kill(master, signal.SIGHUP)


def _isCommit(text):
    return re.fullmatch(_COMMIT, text) is not None


def _runningCommit():
    return SERVER_COMMIT if _isCommit(SERVER_COMMIT) else ""


def _under(root, relative):
    return root.joinpath(*PurePosixPath(relative).parts)


def _copyDatabase(source, target):
    """用 SQLite 的 backup API 复制，正在写入的数据库也能得到一致的副本。"""
    with closing(sqlite3.connect(source)) as database, closing(sqlite3.connect(target)) as copy:
        database.backup(copy)


def _parseVersion(text):
    """从 version.py 的文本读出 (版本号, 提交)；读文本而不执行，远端代码在试导入前不运行。"""
    version = _VERSION_PATTERN.search(text)
    if version is None:
        return None, ""
    commit = _COMMIT_PATTERN.search(text)
    return ".".join(version.groups()), commit.group(1) if commit else ""


def _versionKey(version):
    return tuple(int(part) for part in version.split("."))


def _outputTail(output, limit=800):
    output = output.strip()
    return output if len(output) <= limit else "…" + output[-limit:]


def _extractServer(data, destination):
    """把 GitHub 压缩包里 server/ 下的普通文件写进 destination，返回相对路径列表。"""
    files = []
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive:
                parts = PurePosixPath(member.name).parts
                if len(parts) < 3 or parts[1] != "server":
                    continue
                relative = PurePosixPath(*parts[2:])
                if member.isdir():
                    continue
                if not member.isfile() or ".." in relative.parts or relative.is_absolute():
                    raise ServerUpdateError("下载", f"压缩包里有不安全的条目：{member.name}")
                if relative.parts[0] in _PROTECTED:
                    continue
                target = _under(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, open(target, "wb") as output:
                    shutil.copyfileobj(source, output)
                files.append(relative.as_posix())
    except (tarfile.TarError, OSError, EOFError) as error:
        raise ServerUpdateError("下载", f"压缩包无法解开：{error}") from error
    if "version.py" not in files:
        raise ServerUpdateError("下载", "压缩包里没有 server/version.py")
    return sorted(files)


def _readJson(path):
    """读不到或已损坏都当没有：清单没了就按第一次更新处理，一个文件都不删。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def _writeJson(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _copyFile(source, target):
    """先写到旁边的临时文件再 os.replace，正在运行的 worker 不会读到写了一半的文件。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".server-update")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class ServerUpdater:
    def __init__(self, projectDir, databasePath, *, fetch=_fetch, runPip=_runPip):
        self.projectDir = projectDir
        self.databasePath = databasePath
        self.fetch = fetch
        self.runPip = runPip

    def installedVersion(self):
        """磁盘上的服务端版本，替换后、重启前它就已经是新版本。"""
        try:
            text = (self.projectDir / "version.py").read_text(encoding="utf-8")
        except OSError:
            return None, ""
        return _parseVersion(text)

    def previousVersion(self):
        """可回滚到的上一版本 (版本号, 提交)；没有时为 None。"""
        previous = self._previous()
        return None if previous is None else (previous["version"], previous["commit"])

    def check(self):
        """main 上的 Server Version 比已安装的高时返回它，否则返回 None。"""
        commit = self.fetch(f"{_API}/commits/main", "application/vnd.github.sha")
        commit = commit.decode("ascii", "replace").strip()
        if not _isCommit(commit):
            raise ServerUpdateError("检查", "GitHub 返回的提交号无效")
        version = self._versionAt(commit)
        if not self._isNewer(version):
            return None
        _, installedCommit = self.installedVersion()
        return ServerUpdateCheck(version, commit, self._titlesSince(commit, installedCommit))

    def apply(self, version, commit):
        """装上管理员确认过的那个提交：它必须在 main 上，并带着更高的 Server Version。"""
        try:
            with self._lock("更新"):
                self._confirmRelease(version, commit)
                data = self.fetch(f"{_CODELOAD}/{commit}")
                with tempfile.TemporaryDirectory(dir=self._stateDir()) as work:
                    package = Path(work) / "package"
                    files = _extractServer(data, package)
                    gunicornChanged = self._installRequirements(package)
                    self._trialImport(package, Path(work) / "trial.sqlite3")
                    self._backupDatabase()
                    self._install(package, files)
                # 按换上的 version.py 报版本：页面拿它和新 worker 导入的版本比对，两边读的是同一个文件。
                installedVersion, installedCommit = self.installedVersion()
        except OSError as error:
            raise ServerUpdateError("更新", str(error)) from error
        return ServerUpdateResult(installedVersion, installedCommit, gunicornChanged)

    def rollback(self):
        """把当前版本和上一版本对调；数据库和依赖保持不动。"""
        try:
            with self._lock("回滚"):
                previous = self._previous()
                if previous is None:
                    raise ServerUpdateError("回滚", "没有可回滚的上一版本")
                self._install(self._stateDir() / "previous" / "files", previous["files"])
        except OSError as error:
            raise ServerUpdateError("回滚", str(error)) from error
        return ServerUpdateResult(previous["version"], previous["commit"])

    def _versionAt(self, commit):
        text = self.fetch(
            f"{_API}/contents/server/version.py?ref={commit}",
            "application/vnd.github.raw",
        ).decode("utf-8", "replace")
        version, _ = _parseVersion(text)
        if version is None:
            raise ServerUpdateError("检查", "server/version.py 里没有服务端版本号")
        return version

    def _isNewer(self, version):
        installedVersion, _ = self.installedVersion()
        return installedVersion is None or _versionKey(version) > _versionKey(installedVersion)

    def _confirmRelease(self, version, commit):
        # GitHub 按提交号也能取到同一 fork 网络里别人的提交，只认 main 上的，
        # 否则拿到后台密码的人就能装任意代码。
        if not _isCommit(commit):
            raise ServerUpdateError("检查", "提交号无效，请重新检查更新")
        try:
            status = json.loads(self.fetch(f"{_API}/compare/main...{commit}"))["status"]
        except (ValueError, KeyError, TypeError) as error:
            raise ServerUpdateError("检查", "GitHub 返回的比较结果无效") from error
        if status not in ("identical", "behind"):
            raise ServerUpdateError("检查", "这个提交不在 main 上")
        if self._versionAt(commit) != version:
            raise ServerUpdateError("检查", f"这个提交的服务端版本不是 {version}，请重新检查更新")
        if not self._isNewer(version):
            raise ServerUpdateError("检查", f"{version} 不比已安装的版本新")

    def _titlesSince(self, commit, installedCommit):
        """两个版本之间改过 server/ 的提交标题，不含合并提交。

        已安装的提交常常只改了客户端，不会出现在 server/ 的提交列表里，
        所以截到它之前最近一个改过 server/ 的提交为止。
        """
        if not installedCommit:
            return []
        try:
            newest = self.fetch(f"{_API}/commits?sha={installedCommit}&path=server&per_page=1")
        except ServerUpdateError:
            return []
        try:
            stop = next(iter(json.loads(newest)), {}).get("sha")
            history = json.loads(
                self.fetch(f"{_API}/commits?sha={commit}&path=server&per_page=100")
            )
            titles = []
            for entry in history:
                if entry["sha"] == stop:
                    break
                if len(entry.get("parents", ())) > 1:
                    continue
                titles.append(entry["commit"]["message"].split("\n", 1)[0])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise ServerUpdateError("检查", "GitHub 返回的提交列表无效") from error
        return titles

    @contextmanager
    def _lock(self, step):
        """两个 worker、两个标签页同时点时，后来的一个直接失败而不是排队。"""
        stateDir = self._stateDir()
        with open(stateDir / "lock", "a+b") as handle:
            handle.seek(0)
            try:
                if fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ServerUpdateError(step, "已有更新在进行，请稍后再试") from error
            try:
                # 进程中途被杀留下的工作目录；没能复原时留下的 snapshot-* 是旧文件，不删。
                for leftover in stateDir.glob("tmp*"):
                    shutil.rmtree(leftover, ignore_errors=True)
                yield
            finally:
                if fcntl is None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _installRequirements(self, package):
        """依赖有变化时先装好；返回 gunicorn 本身的要求是否变了。"""
        newRequirements = package / "requirements.txt"
        try:
            new = newRequirements.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False
        try:
            current = (self.projectDir / "requirements.txt").read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        if new == current:
            return False
        self.runPip(newRequirements)
        return _gunicornRequirement(new) != _gunicornRequirement(current)

    def _trialImport(self, package, trialDatabase):
        """在子进程里导入新代码。导入时就会迁移表结构，所以连的是数据库副本。"""
        liveDatabase = self.databasePath()
        if liveDatabase.exists():
            try:
                _copyDatabase(liveDatabase, trialDatabase)
            except sqlite3.Error as error:
                raise ServerUpdateError("试导入", f"没能复制数据库：{error}") from error
        environment = dict(
            os.environ,
            DJCATAI_DATABASE_PATH=str(trialDatabase),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONIOENCODING="utf-8",
        )
        _run(
            "试导入",
            [sys.executable, "-c", "import ai_markdown"],
            _TRIAL_IMPORT_TIMEOUT,
            cwd=package,
            env=environment,
        )

    def _stateDir(self):
        stateDir = self.databasePath().parent / "server-update"
        stateDir.mkdir(parents=True, exist_ok=True)
        return stateDir

    def _previous(self):
        """上一版本的记录；记录和被换下的文件放在同一个目录里，一次改名就换好。"""
        previous = self._stateDir() / "previous"
        record = _readJson(previous / "record.json")
        if record is None or not (previous / "files").is_dir():
            return None
        return record

    def _backupDatabase(self):
        liveDatabase = self.databasePath()
        if not liveDatabase.exists():
            return
        stateDir = self._stateDir()
        version, _ = self.installedVersion()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = stateDir / f"database-{stamp}-{version or 'unknown'}.sqlite3"
        try:
            _copyDatabase(liveDatabase, backup)
        except sqlite3.Error as error:
            backup.unlink(missing_ok=True)
            raise ServerUpdateError("备份", str(error)) from error
        for old in sorted(stateDir.glob("database-*.sqlite3"))[:-_DATABASE_BACKUPS]:
            old.unlink(missing_ok=True)

    def _install(self, sourceDir, files):
        """把 sourceDir 里的 files 换进项目目录，被换下的版本成为上一版本。"""
        stateDir = self._stateDir()
        installedVersion, installedCommit = self.installedVersion()
        installedFiles = _readJson(stateDir / "manifest.json")
        if installedFiles is None:
            # 从没更新过：只知道这次会覆盖哪些文件，不在包里的旧文件一个都不删。
            installedFiles = files
        kept = [relative for relative in installedFiles if _under(self.projectDir, relative).is_file()]
        snapshot = Path(tempfile.mkdtemp(prefix="snapshot-", dir=stateDir))
        oldFiles = snapshot / "files"
        try:
            oldFiles.mkdir()
            for relative in kept:
                _copyFile(_under(self.projectDir, relative), _under(oldFiles, relative))
            _writeJson(
                snapshot / "record.json",
                {"version": installedVersion, "commit": installedCommit, "files": kept},
            )
        except OSError as error:
            shutil.rmtree(snapshot, ignore_errors=True)
            raise ServerUpdateError("替换", f"没能先存下当前版本：{error}") from error

        created = []
        try:
            self._replace(sourceDir, files, set(installedFiles) - set(files), created)
        except OSError as error:
            unrestored = self._restore(oldFiles, kept, created)
            if unrestored:
                raise ServerUpdateError(
                    "替换",
                    f"{error}；{'、'.join(unrestored)} 没能复原，旧文件留在 {oldFiles}",
                ) from error
            shutil.rmtree(snapshot, ignore_errors=True)
            raise ServerUpdateError("替换", str(error)) from error

        try:
            _writeJson(stateDir / "manifest.json", files)
            self._keepAsPrevious(snapshot)
        except OSError as error:
            raise ServerUpdateError(
                "替换",
                f"文件已经换好，但没能记下上一版本（旧文件留在 {oldFiles}）：{error}；"
                "请到宝塔面板重启项目",
            ) from error

    def _replace(self, sourceDir, files, removed, created):
        """逐个原子替换；新出现的文件记进 created，出错时交给 _restore 收拾。"""
        for relative in files:
            target = _under(self.projectDir, relative)
            if not target.exists():
                created.append(target)
            _copyFile(_under(sourceDir, relative), target)
        for relative in removed:
            _under(self.projectDir, relative).unlink(missing_ok=True)

    def _restore(self, oldFiles, kept, created):
        """删掉新加的文件、放回旧文件；返回没能放回的旧文件。"""
        for target in created:
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        unrestored = []
        for relative in kept:
            try:
                _copyFile(_under(oldFiles, relative), _under(self.projectDir, relative))
            except OSError:
                unrestored.append(relative)
        return unrestored

    def _keepAsPrevious(self, snapshot):
        stateDir = snapshot.parent
        previous = stateDir / "previous"
        retired = None
        if previous.exists():
            retired = stateDir / f"tmp-retired-{os.getpid()}-{time.monotonic_ns()}"
            os.replace(previous, retired)
        try:
            os.replace(snapshot, previous)
        except OSError:
            if retired is not None:
                os.replace(retired, previous)
            raise
        if retired is not None:
            shutil.rmtree(retired, ignore_errors=True)

def registerServerUpdate(
    app,
    *,
    databasePath,
    loginRequired,
    csrfToken,
    checkCsrf,
    adminResponse,
):
    """Register the Server Update page and the running version shown in the sidebar."""

    app.extensions["server_update"] = {
        "updater": ServerUpdater(Path(__file__).resolve().parent, databasePath),
        "restarter": _workerRestarter,
    }
    blueprint = Blueprint("server_update", __name__, url_prefix="/admin/server-update")

    def extension(name):
        return app.extensions["server_update"][name]

    @app.context_processor
    def runningVersion():
        return {"server_version": SERVER_VERSION, "server_commit": _runningCommit()}

    def changeThenRestart(change, verb):
        """更新或回滚成功后先回应页面，回应发完再 SIGHUP；页面等新 worker 报出新版本再刷新。"""
        checkCsrf()
        try:
            result = change()
        except ServerUpdateError as error:
            return adminResponse(str(error), "error", "server_update.page", 400)
        message = f"{verb} {result.version}"
        restart = extension("restarter")()
        if restart is None:
            return adminResponse(
                f"{message}，但服务不是由 gunicorn 运行，请手动重启",
                "info",
                "server_update.page",
                navigate=True,
            )
        if result.gunicornChanged:
            message += "；gunicorn 本身也有更新，请再到宝塔面板重启一次项目"
        response = make_response(
            adminResponse(
                message,
                "success",
                "server_update.page",
                navigate=True,
                data={
                    "awaitVersion": {
                        "url": url_for("server_update.running"),
                        "version": result.version,
                        "commit": result.commit,
                    }
                },
            )
        )
        response.call_on_close(restart)
        return response

    @blueprint.get("/")
    @loginRequired
    def page():
        updater = extension("updater")
        return render_template(
            "admin_server_update.html",
            csrf_token=csrfToken(),
            current_page="server_update",
            installed=updater.installedVersion(),
            previous=updater.previousVersion(),
            repository=REPOSITORY,
        )

    @blueprint.get("/running")
    @loginRequired
    def running():
        return jsonify(version=SERVER_VERSION, commit=_runningCommit())

    @blueprint.post("/check")
    @loginRequired
    def check():
        checkCsrf()
        try:
            result = extension("updater").check()
        except ServerUpdateError as error:
            return adminResponse(
                f"检查更新失败：{error.detail}", "error", "server_update.page", 502
            )
        html = render_template(
            "_server_update_check.html", check=result, csrf_token=csrfToken()
        )
        message = f"发现新版本 {result.version}" if result else "已是最新版本"
        return adminResponse(
            message,
            "success" if result else "info",
            "server_update.page",
            data={"replace": {"server-update-check": html}},
        )

    @blueprint.post("/apply")
    @loginRequired
    def apply():
        version = request.form.get("version", "")
        commit = request.form.get("commit", "")
        return changeThenRestart(lambda: extension("updater").apply(version, commit), "已更新到")

    @blueprint.post("/rollback")
    @loginRequired
    def rollback():
        return changeThenRestart(lambda: extension("updater").rollback(), "已回滚到")

    app.register_blueprint(blueprint)


if __name__ == "__main__":
    # 后台打不开时在终端回滚：以运行服务的用户执行，之后到宝塔面板重启项目。
    if sys.argv[1:] != ["rollback"]:
        raise SystemExit("用法：python server_update.py rollback")
    database = Path(os.environ.get("DJCATAI_DATABASE_PATH", "ai_markdown_usage.sqlite3"))
    try:
        result = ServerUpdater(Path(__file__).resolve().parent, lambda: database.resolve()).rollback()
    except ServerUpdateError as error:
        raise SystemExit(str(error)) from error
    print(f"已回滚到 {result.version}，请到宝塔面板重启项目")
