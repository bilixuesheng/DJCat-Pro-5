import os
from pathlib import Path


def externalProcessEnvironment(compiled=None) -> dict[str, str]:
    environment = os.environ.copy()
    if compiled is None:
        return environment
    binaryDir = Path(compiled.containing_dir)
    binaryKey = os.path.normcase(os.path.abspath(binaryDir))

    for name in (
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "QML2_IMPORT_PATH",
        "QML_IMPORT_PATH",
        "QT_PLUGIN_PATH",
        "QT_QPA_PLATFORM_PLUGIN_PATH",
    ):
        value = environment.get(name)
        if not value:
            continue
        entries = []
        for entry in value.split(os.pathsep):
            if not entry:
                entries.append(entry)
                continue
            candidate = os.path.normcase(
                os.path.abspath(os.path.expandvars(entry.strip('"')))
            )
            try:
                bundled = os.path.commonpath((binaryKey, candidate)) == binaryKey
            except ValueError:
                bundled = False
            if not bundled:
                entries.append(entry)
        if entries:
            environment[name] = os.pathsep.join(entries)
        else:
            environment.pop(name, None)
    return environment


def programWorkingDirectory(target: str, workingDir: str) -> str | None:
    """启动程序时的工作目录：没填时用程序所在的文件夹，与快捷方式"起始位置"的默认一样；
    只写程序名的跟着电教猫。为什么不能落在程序目录里见 djcat.py 的 main()。"""
    if workingDir:
        return workingDir
    path = Path(target)
    return str(path.parent) if path.is_absolute() else None
