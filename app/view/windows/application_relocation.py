"""更改 Application Install Location 的界面流程，由 MainWindow 拥有。

设置页只发出想换到哪里；这里依次检查新位置、按需取得权限、确认，再在后台执行 Application
Relocation，进度显示在 Relocation Toast 上。规则都在 `app/common/install_location.py`，这里
只排先后、弹框和换线程。Application Store 页面不为此加载：它没加载时没有进行中的操作，
加载了就读同一份 `applicationsBlocked()`。
"""

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from PySide6.QtCore import QObject, Signal
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox
from shiboken6 import isValid

from app.common import install_location as location
from app.config.cfg import cfg
from app.config.paths import PROGRAM_DIR
from app.view.components.update_toast import RelocationToast


@dataclass
class _Request:
    target: Path
    reset: bool
    source: Path
    sourceAvailable: bool
    names: list = field(default_factory=list)


class ApplicationRelocation(QObject):
    _failed = Signal(str)
    _writableChecked = Signal(object, bool, bool)
    _permissionGranted = Signal(object, object, bool)
    _inspected = Signal(object, object)
    _progressed = Signal(object, object)
    _relocated = Signal(object, object)
    _cleaned = Signal(object)
    _recovered = Signal(bool)

    def __init__(self, window, applicationsBusy):
        super().__init__(window)
        self._window = window
        self._applicationsBusy = applicationsBusy
        self._toast = None
        self._cancelEvent = threading.Event()
        self._shuttingDown = False
        self._failed.connect(self._onFailed)
        self._writableChecked.connect(self._onWritableChecked)
        self._permissionGranted.connect(self._onPermissionGranted)
        self._inspected.connect(self._onInspected)
        self._progressed.connect(self._onProgressed)
        self._relocated.connect(self._onRelocated)
        self._cleaned.connect(self._onCleaned)
        self._recovered.connect(self._onRecovered)

    def request(self, target: str) -> None:
        """换到 target；空字符串表示「重置」回默认位置。"""
        if self._shuttingDown or location.relocationState() != location.IDLE:
            return
        reset = not target
        source = location.installLocation()
        newLocation = PROGRAM_DIR if reset else Path(target)
        if location.samePath(newLocation, source):
            return
        if not reset:
            problem = location.targetProblem(newLocation, source)
            if problem:
                self._error("无法使用这个文件夹", problem)
                return
        if self._applicationsBusy():
            self._warnApplicationsBusy()
            return
        sourceAvailable = location.installLocationAvailable()
        if not sourceAvailable and not self._confirm(
            "当前安装位置不可用",
            f"「{source}」现在无法访问，其中的应用不会被迁移。更改后，电教猫将不再识别它们。",
            "仍然更改",
        ):
            return
        request = _Request(newLocation, reset, source, sourceAvailable)
        location.setRelocationState(location.CHECKING)
        self._run(self._checkWritable, request)

    def recoverAtStartup(self) -> None:
        """上次的 Application Relocation 中途退出或断电时，按迁移记录收尾。"""
        journal = cfg.appRelocation.value
        if not journal:
            return
        committed = location.journalCommitted(journal)
        location.setRelocationState(
            location.CLEANING if committed else location.RELOCATING
        )
        self._run(self._recover, journal)

    def shutdown(self) -> None:
        # 不等搬到一半的文件：下次启动按迁移记录收尾。
        self._shuttingDown = True
        self._cancelEvent.set()
        toast = self._toast
        self._toast = None
        if toast is not None and isValid(toast):
            toast.close()

    def _run(self, function, *args) -> None:
        def run():
            try:
                function(*args)
            except Exception as error:
                logger.exception("更改应用安装位置失败")
                self._failed.emit(str(error))

        threading.Thread(target=run, daemon=True).start()

    def _onFailed(self, message):
        if self._shuttingDown:
            return
        location.setRelocationState(location.IDLE)
        self._error("无法更改应用安装位置", message)

    def _checkWritable(self, request):
        writable = location.isWritable(request.target)
        empty = writable or location.isEmptyFolder(request.target)
        self._writableChecked.emit(request, writable, empty)

    def _onWritableChecked(self, request, writable, empty):
        if self._shuttingDown:
            return
        if writable:
            self._run(self._inspect, request)
            return
        if location.elevationForbidden(request.target):
            self._finishChecking()
            self._error(
                "没有写入权限",
                f"电教猫没有写入「{request.target}」的权限。这是系统文件夹，电教猫不会为它"
                "取得权限，请换一个文件夹。",
            )
            return
        content = (
            f"电教猫没有写入「{request.target}」的权限。是否以管理员身份为本机所有用户取得"
            "这个文件夹的修改权限？取得后，普通权限的电教猫也能在这里安装和更新应用。"
        )
        if not empty:
            content += "\n\n该文件夹里已有的文件也会对本机所有用户开放修改。"
        if not self._confirm("没有写入权限", content, "取得权限"):
            self._finishChecking()
            return
        self._run(self._grant, request, int(self._window.winId()))

    def _grant(self, request, window):
        granted = location.grantUsersModify(request.target, window)
        writable = bool(granted) and location.isWritable(request.target)
        self._permissionGranted.emit(request, granted, writable)

    def _onPermissionGranted(self, request, granted, writable):
        if self._shuttingDown:
            return
        if granted is None:
            # 用户在 UAC 里点了「否」，等于取消。
            self._finishChecking()
            return
        if not writable:
            self._finishChecking()
            self._error(
                "仍无法写入该文件夹",
                "可能是只读磁盘，或被其他软件限制。已取消更改。",
            )
            return
        self._run(self._inspect, request)

    def _inspect(self, request):
        folders = (
            location.applicationFolders(request.source)
            if request.sourceAvailable
            else []
        )
        result = {
            "folders": folders,
            "conflicts": location.conflictingNames(folders, request.target),
            "sameVolume": True,
            "totalBytes": None,
            "running": [],
        }
        if folders and not result["conflicts"]:
            result["sameVolume"] = location.sameVolume(request.source, request.target)
            # 同一个盘只改名，不占额外空间；跨盘才在确认之前量大小、查空间，免得关掉
            # 程序复制到一半才发现装不下。
            if not result["sameVolume"]:
                result["totalBytes"] = sum(
                    location.folderSize(request.source / folder.name)
                    for folder in folders
                )
                result["freeBytes"] = location.freeSpace(request.target)
            result["running"] = location.runningApplications(request.source, folders)
        self._inspected.emit(request, result)

    def _onInspected(self, request, result):
        if self._shuttingDown:
            return
        folders = result["folders"]
        if not folders:
            location.commitInstallLocation(
                None if request.reset else request.target, rebase=False
            )
            self._finishChecking()
            InfoBar.success(
                "应用安装位置已更改",
                str(location.installLocation()),
                duration=3000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self._window,
            )
            return
        conflicts = result["conflicts"]
        if conflicts:
            self._finishChecking()
            self._error(
                "新位置已有同名文件夹",
                f"新位置已有同名文件夹：{'、'.join(conflicts)}。请换一个文件夹，或先移走这些文件夹。",
            )
            return
        total = result["totalBytes"]
        if total is not None and result["freeBytes"] < total:
            self._finishChecking()
            self._error(
                "磁盘空间不足",
                f"新位置所在磁盘空间不足：需要 {location.formatSize(total)}，"
                f"可用 {location.formatSize(result['freeBytes'])}。",
            )
            return
        size = f"（共 {location.formatSize(total)}）" if total is not None else ""
        content = f"即将把 {len(folders)} 个应用{size}迁移到「{request.target}」。"
        if result["running"]:
            content += "\n\n以下应用正在运行，开始后会被强制关闭，未保存的内容会丢失：\n"
            content += "\n".join(f"· {name}" for name in result["running"])
        if not self._confirm("迁移已安装的应用", content, "开始迁移"):
            self._finishChecking()
            return
        if self._applicationsBusy():
            self._finishChecking()
            self._warnApplicationsBusy()
            return
        self._start(request, [folder.name for folder in folders], result)

    def _start(self, request, names, result):
        token = uuid.uuid4().hex
        request.names = names
        cfg.set(
            cfg.appRelocation,
            location.relocationJournal(request.source, request.target, names, token),
        )
        location.setRelocationState(location.RELOCATING)
        total = result["totalBytes"]
        toast = self._ensureToast()
        if total is None:
            content = f"正在移动 {len(names)} 个应用…"
            widest = content
        else:
            size = location.formatSize(total)
            content = f"已复制 0 B / {size}"
            widest = f"已复制 {size} / {size}"
        toast.start("正在迁移应用", content, widest)
        self._run(self._relocate, request, names, token, total or 0)

    def _relocate(self, request, names, token, total):
        error = None
        try:
            location.relocate(
                request.source,
                request.target,
                names,
                token,
                total,
                progress=self._progressed.emit,
                cancelEvent=self._cancelEvent,
            )
        except location.RelocationError as relocationError:
            error = relocationError
        except Exception as unexpected:
            logger.exception("应用迁移失败")
            error = location.RelocationError(f"{unexpected}。", clean=False)
        self._relocated.emit(request, error)

    def _onProgressed(self, done, total):
        if self._toast is None or not total:
            return
        self._toast.setProgress(
            f"已复制 {location.formatSize(done)} / {location.formatSize(total)}",
            done * 100 / total,
        )

    def _onRelocated(self, request, error):
        if self._shuttingDown:
            return
        toast = self._ensureToast()
        if error is not None:
            toast.fail("应用迁移失败", f"{error}应用仍在原位置。")
            if error.clean:
                cfg.set(cfg.appRelocation, {})
            location.setRelocationState(location.IDLE)
            return
        location.commitInstallLocation(
            None if request.reset else request.target, rebase=True
        )
        toast.succeed(
            "应用迁移完成",
            f"已将 {len(request.names)} 个应用迁移到「{location.installLocation()}」。",
        )
        location.setRelocationState(location.CLEANING)
        self._run(self._clean, request)

    def _clean(self, request):
        self._cleaned.emit(
            location.removeOldFolders(request.source, request.target, request.names)
        )

    def _onCleaned(self, leftovers):
        if self._shuttingDown:
            return
        cfg.set(cfg.appRelocation, {})
        location.setRelocationState(location.IDLE)
        if leftovers:
            InfoBar.warning(
                "部分旧文件没有删掉",
                f"它们正被其他程序占用，可以稍后手动删除：{leftovers[0].parent}",
                duration=6000,
                position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self._window,
            )

    def _recover(self, journal):
        try:
            done = location.recoverRelocation(journal)
        except Exception:
            logger.exception("应用迁移收尾失败")
            done = False
        self._recovered.emit(done)

    def _onRecovered(self, done):
        if self._shuttingDown:
            return
        if done:
            cfg.set(cfg.appRelocation, {})
        location.setRelocationState(location.IDLE)

    def _finishChecking(self):
        location.setRelocationState(location.IDLE)

    def _ensureToast(self):
        toast = self._toast
        if toast is not None and isValid(toast):
            return toast
        toast = RelocationToast(self._window)
        toast.destroyed.connect(lambda _=None, current=toast: self._clearToast(current))
        self._toast = toast
        return toast

    def _clearToast(self, toast):
        if self._toast is toast:
            self._toast = None

    def _confirm(self, title, content, yesText):
        box = MessageBox(title, content, self._window)
        box.yesButton.setText(yesText)
        box.cancelButton.setText("取消")
        try:
            return bool(box.exec())
        finally:
            box.deleteLater()

    def _error(self, title, content):
        InfoBar.error(
            title,
            content,
            duration=5000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self._window,
        )

    def _warnApplicationsBusy(self):
        InfoBar.warning(
            "暂时不能更改",
            "有应用正在下载、安装、卸载或打开，请完成后再更改安装位置。",
            duration=4000,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=self._window,
        )
