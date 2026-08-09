import ctypes
import json
import os
import subprocess
import sys
import uuid
from ctypes import wintypes
from pathlib import Path

from app.common.app_store import (
    APP_STORE_TEMP_DIR,
    PROGRAM_DIR,
    installPackage,
    uninstallApplication,
)
from app.config.paths import APP_DIR


def _inside(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def runMaintenanceJob(
    jobPath: Path,
    *,
    programDir: Path = PROGRAM_DIR,
    tempDir: Path = APP_STORE_TEMP_DIR,
) -> None:
    jobPath = Path(jobPath)
    tempDir = Path(tempDir)
    if jobPath.parent.resolve() != tempDir.resolve() or jobPath.suffix != ".json":
        raise ValueError("维护任务不在受管临时目录中")
    job = json.loads(jobPath.read_text(encoding="utf-8"))
    operation = job.get("operation")
    application = job.get("application")
    if not isinstance(application, dict):
        raise ValueError("维护任务缺少应用信息")
    if operation == "install":
        archive = Path(job.get("archive", ""))
        if not archive.is_file() or not _inside(archive, tempDir):
            raise ValueError("安装包不在受管临时目录中")
        installPackage(
            archive,
            application,
            programDir=programDir,
            tempDir=tempDir,
        )
    elif operation == "uninstall":
        uninstallApplication(application.get("install_dir", ""), programDir=programDir)
    else:
        raise ValueError("维护任务类型无效")


def createMaintenanceJob(
    operation: str,
    application: dict,
    archivePath: Path | None = None,
    *,
    tempDir: Path = APP_STORE_TEMP_DIR,
) -> Path:
    tempDir = Path(tempDir)
    tempDir.mkdir(parents=True, exist_ok=True)
    jobPath = tempDir / f"maintenance-{uuid.uuid4().hex}.json"
    job = {"operation": operation, "application": application}
    if archivePath is not None:
        archivePath = Path(archivePath)
        if not _inside(archivePath, tempDir):
            raise ValueError("安装包不在受管临时目录中")
        job["archive"] = str(archivePath.resolve())
    jobPath.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    return jobPath


def maintenanceMain(jobPath: Path) -> int:
    jobPath = Path(jobPath)
    resultPath = jobPath.with_suffix(".result.json")
    try:
        runMaintenanceJob(jobPath)
        result = {"success": True, "error": ""}
        exitCode = 0
    except Exception as error:
        result = {"success": False, "error": str(error)}
        exitCode = 1
    try:
        resultPath.write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
    return exitCode


class _ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", wintypes.LPVOID),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


def runElevatedJob(jobPath: Path) -> None:
    if os.name != "nt":
        raise OSError("管理员权限维护仅支持 Windows")
    executable = sys.executable
    arguments = ["--app-maintenance", str(Path(jobPath).resolve())]
    if not (getattr(sys, "frozen", False) or "__compiled__" in globals()):
        arguments.insert(0, str(APP_DIR / "djcat.py"))

    info = _ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = subprocess.list2cmdline(arguments)
    info.lpDirectory = str(APP_DIR)
    info.nShow = 0
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError()
    try:
        ctypes.windll.kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        exitCode = wintypes.DWORD()
        ctypes.windll.kernel32.GetExitCodeProcess(
            info.hProcess, ctypes.byref(exitCode)
        )
    finally:
        ctypes.windll.kernel32.CloseHandle(info.hProcess)

    resultPath = Path(jobPath).with_suffix(".result.json")
    try:
        result = json.loads(resultPath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        result = {"success": False, "error": "提权维护进程没有返回结果"}
    if exitCode.value or not result.get("success"):
        raise OSError(result.get("error") or "提权维护失败")


def performMaintenance(
    operation: str,
    application: dict,
    archivePath: Path | None = None,
    *,
    programDir: Path = PROGRAM_DIR,
    tempDir: Path = APP_STORE_TEMP_DIR,
) -> None:
    try:
        if operation == "install":
            installPackage(
                archivePath,
                application,
                programDir=programDir,
                tempDir=tempDir,
            )
        elif operation == "uninstall":
            uninstallApplication(
                application.get("install_dir", ""), programDir=programDir
            )
        else:
            raise ValueError("维护任务类型无效")
        return
    except PermissionError:
        if Path(programDir).resolve() != PROGRAM_DIR.resolve():
            raise

    jobPath = createMaintenanceJob(
        operation,
        application,
        archivePath,
        tempDir=tempDir,
    )
    resultPath = jobPath.with_suffix(".result.json")
    try:
        runElevatedJob(jobPath)
    finally:
        jobPath.unlink(missing_ok=True)
        resultPath.unlink(missing_ok=True)
