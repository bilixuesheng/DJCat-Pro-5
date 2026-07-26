import sys

from PySide6.QtCore import QCoreApplication


def setRunAtLogin(enabled: bool) -> None:
    if sys.platform != "win32":
        return

    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_WRITE,
    ) as key:
        if enabled:
            exePath = QCoreApplication.applicationFilePath().replace("/", "\\")
            winreg.SetValueEx(
                key,
                "DJCatPro5",
                0,
                winreg.REG_SZ,
                f'"{exePath}" --silence',
            )
        else:
            try:
                winreg.DeleteValue(key, "DJCatPro5")
            except FileNotFoundError:
                pass
