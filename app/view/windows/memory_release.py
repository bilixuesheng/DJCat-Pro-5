"""Give memory back while the main window sits in the tray.

Ten minutes after the main window was hidden, MainWindow unloads the Settings page and
the Application Store (they are built again when next needed), Python collects its
garbage and Windows trims the working set. A page that cannot go yet (an Application
Store operation, a dialog's nested event loop) is tried again every minute, and the trim
waits for the last of them. A page built while the window is hidden, as an Application
Home Card clicked in the Tray Menu builds the Application Store, starts the ten minutes
over. A Display Window on screen keeps repainting and would page everything straight
back in, so the trim is skipped then; the pages still go. After a silent startup the
working set is trimmed once after a minute, unless the window was shown meanwhile.
With 停用页面懒加载 on nothing is unloaded or trimmed.
"""

import gc

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.config.cfg import cfg
from app.platform.memory import trimWorkingSet

RELEASE_AFTER_HIDDEN_MS = 10 * 60 * 1000
RETRY_RELEASE_MS = 60 * 1000
TRIM_AFTER_SILENT_STARTUP_MS = 60 * 1000


def _displayWindowShown() -> bool:
    # 投送、考试倒计时和全屏时钟都铺着 WindowBackground；到这里才导入，启动时不多加载它。
    from app.view.components.window_background import WindowBackground

    return any(
        widget.isVisible() and widget.findChild(WindowBackground) is not None
        for widget in QApplication.topLevelWidgets()
    )


class MemoryRelease(QObject):
    def __init__(self, window, unloadPages, isSilent=False):
        """``unloadPages()`` unloads what it can and returns False while a page has to wait."""
        super().__init__(window)
        self._window = window
        self._unloadPages = unloadPages
        self._releaseTimer = QTimer(self, singleShot=True, interval=RELEASE_AFTER_HIDDEN_MS)
        self._releaseTimer.timeout.connect(self._release)
        self._retryTimer = QTimer(self, singleShot=True, interval=RETRY_RELEASE_MS)
        self._retryTimer.timeout.connect(self._release)
        self._startupTimer = QTimer(
            self, singleShot=True, interval=TRIM_AFTER_SILENT_STARTUP_MS
        )
        self._startupTimer.timeout.connect(self._trimAfterSilentStartup)
        window.installEventFilter(self)
        if window.isHidden():
            self._releaseTimer.start()
        if isSilent:
            self._startupTimer.start()

    def onPageLoaded(self) -> None:
        if self._window.isHidden():
            self._restart()

    def stop(self) -> None:
        self._window.removeEventFilter(self)
        self._stopTimers()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window:
            if event.type() == QEvent.Type.Show:
                self._stopTimers()
            # 最小化也会收到 Hide，但窗口没有藏起来：Windows 那时自己会修剪，用户也指望一点就回来。
            elif event.type() == QEvent.Type.Hide and self._window.isHidden():
                self._restart()
        return False

    def _stopTimers(self) -> None:
        for timer in (self._releaseTimer, self._retryTimer, self._startupTimer):
            timer.stop()

    def _restart(self) -> None:
        self._retryTimer.stop()
        self._releaseTimer.start()

    def _isIdle(self) -> bool:
        return not cfg.eagerPageLoading.value and self._window.isHidden()

    def _release(self) -> None:
        if not self._isIdle():
            return
        if not self._unloadPages():
            self._retryTimer.start()
            return
        self._trim()

    def _trimAfterSilentStartup(self) -> None:
        if self._isIdle():
            self._trim()

    def _trim(self) -> None:
        gc.collect()
        if not _displayWindowShown():
            trimWorkingSet()
