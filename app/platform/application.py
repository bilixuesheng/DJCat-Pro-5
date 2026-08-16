from __future__ import annotations

import sys
import time
from signal import SIGINT, signal

from PySide6.QtCore import QSharedMemory, Qt, Signal
from PySide6.QtWidgets import QApplication
from loguru import logger


SINGLE_INSTANCE_KEY = "DJCatPro5"


class SingletonApplication(QApplication):
    activationRequested = Signal()

    def __init__(self, argv: list[str], key: str = SINGLE_INSTANCE_KEY):
        super().__init__(argv)
        self._key = key
        self._memory: QSharedMemory | None = None

        if sys.platform == "win32":
            self._lockSingleInstance()

        try:
            signal(SIGINT, self._onInterrupt)
        except Exception as error:
            logger.warning("注册 SIGINT 处理器失败: {}", error)

        if sys.platform == "win32":
            self._registerIpcReceiver()

    def exec(self) -> int:
        try:
            return super().exec()
        finally:
            self._unlockSingleInstance()

    def quit(self) -> None:
        self._unlockSingleInstance()
        super().quit()

    def _lockSingleInstance(self) -> None:
        try:
            cleanup = QSharedMemory(self._key)
            if cleanup.attach():
                cleanup.detach()
        except Exception:
            pass

        self._memory = QSharedMemory(self._key)
        if self._memory.attach():
            _sendToRunningWindows()
            raise SystemExit(0)

        if self._memory.create(1):
            return

        try:
            self._memory.attach()
            self._memory.detach()
            if not self._memory.create(1):
                raise RuntimeError(self._memory.errorString())
        except Exception as error:
            logger.opt(exception=error).error("创建单实例共享内存失败")
            raise

    def _unlockSingleInstance(self) -> None:
        if self._memory is not None and self._memory.isAttached():
            try:
                self._memory.detach()
            except Exception as error:
                logger.warning("释放单实例共享内存失败: {}", error)

    def _onInterrupt(self, _signum, _frame) -> None:
        logger.error("KeyboardInterrupt, quitting")
        self.quit()

    def _registerIpcReceiver(self) -> None:
        self._ipcHwnd = _createIpcWindow()


def raiseWindow(window) -> None:
    window.show()
    window.setWindowState(
        (window.windowState() & ~Qt.WindowState.WindowMinimized)
        | Qt.WindowState.WindowActive
    )
    window.raise_()
    window.activateWindow()

    if sys.platform != "win32":
        return

    try:
        import win32api
        import win32con
        import win32gui
        import win32process

        hwnd = int(window.winId())
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

        foregroundHwnd = win32gui.GetForegroundWindow()
        foregroundThreadId = (
            win32process.GetWindowThreadProcessId(foregroundHwnd)[0]
            if foregroundHwnd
            else 0
        )
        currentThreadId = win32api.GetCurrentThreadId()
        attached = False
        try:
            if foregroundThreadId and foregroundThreadId != currentThreadId:
                win32process.AttachThreadInput(
                    currentThreadId, foregroundThreadId, True
                )
                attached = True
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags
            )
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags
            )
        finally:
            if attached:
                win32process.AttachThreadInput(
                    currentThreadId, foregroundThreadId, False
                )
    except Exception as error:
        logger.opt(exception=error).warning("唤起主窗口失败")


if sys.platform == "win32":
    import win32api
    import win32gui

    IPC_CLASS_NAME = "DJCatPro5IPC"
    WM_USER_WAKE = 1025

    def _onIpcWake(_hWnd, _msg, _wParam, _lParam):
        application = QApplication.instance()
        if isinstance(application, SingletonApplication):
            application.activationRequested.emit()
        return 0

    _IPC_MESSAGE_MAP = {WM_USER_WAKE: _onIpcWake}

    def _createIpcWindow() -> int:
        hInstance = win32api.GetModuleHandle(None)
        windowClass = win32gui.WNDCLASS()
        windowClass.lpfnWndProc = _IPC_MESSAGE_MAP
        windowClass.hInstance = hInstance
        windowClass.lpszClassName = IPC_CLASS_NAME
        try:
            win32gui.RegisterClass(windowClass)
        except win32gui.error:
            pass
        return win32gui.CreateWindow(
            IPC_CLASS_NAME,
            IPC_CLASS_NAME,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            hInstance,
            None,
        )

    def _sendToRunningWindows() -> None:
        hWnd = 0
        for _ in range(20):
            hWnd = win32gui.FindWindow(IPC_CLASS_NAME, None)
            if hWnd:
                break
            time.sleep(0.05)

        if not hWnd:
            logger.warning("未找到正在运行实例的 IPC 窗口")
            return

        win32gui.PostMessage(hWnd, WM_USER_WAKE, 0, 0)
