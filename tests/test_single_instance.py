from __future__ import annotations

import os
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Qt

from app.platform import application


REPO = Path(__file__).resolve().parents[1]


def test_raiseWindow_restores_minimized_window():
    window = MagicMock()
    window.windowState.return_value = Qt.WindowState.WindowMinimized

    with patch.object(application.sys, "platform", "linux"):
        application.raiseWindow(window)

    window.show.assert_called_once_with()
    window.setWindowState.assert_called_once_with(Qt.WindowState.WindowActive)
    window.raise_.assert_called_once_with()
    window.activateWindow.assert_called_once_with()


def test_raiseWindow_uses_windows_foreground_api():
    window = MagicMock()
    window.winId.return_value = 42
    window.windowState.return_value = Qt.WindowState.WindowMinimized
    win32api = MagicMock(GetCurrentThreadId=MagicMock(return_value=10))
    win32con = types.SimpleNamespace(
        SW_RESTORE=9,
        SWP_NOMOVE=1,
        SWP_NOSIZE=2,
        SWP_SHOWWINDOW=4,
        HWND_TOPMOST=-1,
        HWND_NOTOPMOST=-2,
    )
    win32gui = MagicMock(
        IsIconic=MagicMock(return_value=True),
        GetForegroundWindow=MagicMock(return_value=0),
    )
    win32process = MagicMock()

    with (
        patch.object(application.sys, "platform", "win32"),
        patch.dict(
            sys.modules,
            {
                "win32api": win32api,
                "win32con": win32con,
                "win32gui": win32gui,
                "win32process": win32process,
            },
        ),
    ):
        application.raiseWindow(window)

    win32gui.ShowWindow.assert_called_once_with(42, 9)
    win32gui.BringWindowToTop.assert_called_once_with(42)
    win32gui.SetForegroundWindow.assert_called_once_with(42)
    assert win32gui.SetWindowPos.call_count == 2


@pytest.mark.skipif(sys.platform != "win32", reason="Windows IPC only")
def test_second_instance_posts_wake_without_waiting_for_first():
    with (
        patch.object(application.win32gui, "FindWindow", return_value=42),
        patch.object(application.win32gui, "PostMessage") as post_message,
        patch.object(application.win32gui, "SendMessage") as send_message,
    ):
        application._sendToRunningWindows()

    post_message.assert_called_once_with(42, application.WM_USER_WAKE, 0, 0)
    send_message.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows IPC only")
def test_second_instance_wakes_first_and_lock_is_released(tmp_path: Path):
    key = f"DJCatPro5Test_{uuid.uuid4().hex}"
    script = """
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer

from app.platform.application import SingletonApplication

key = os.environ["DJCAT_TEST_SINGLETON_KEY"]
ready = Path(os.environ["DJCAT_TEST_READY"])
started = Path(os.environ["DJCAT_TEST_STARTED"])
activated = Path(os.environ["DJCAT_TEST_ACTIVATED"])
timeout = int(os.environ["DJCAT_TEST_TIMEOUT"])

app = SingletonApplication(sys.argv, key)
started.write_text("started", encoding="utf-8")

def on_activation():
    activated.write_text("activated", encoding="utf-8")
    QTimer.singleShot(0, app.quit)

app.activationRequested.connect(on_activation)
ready.write_text("ready", encoding="utf-8")
QTimer.singleShot(timeout, app.quit)
sys.exit(app.exec())
"""

    def make_env(ready: Path, started: Path, activated: Path, timeout: int):
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["DJCAT_TEST_SINGLETON_KEY"] = key
        env["DJCAT_TEST_READY"] = str(ready)
        env["DJCAT_TEST_STARTED"] = str(started)
        env["DJCAT_TEST_ACTIVATED"] = str(activated)
        env["DJCAT_TEST_TIMEOUT"] = str(timeout)
        return env

    def wait_for_file(path: Path, process: subprocess.Popen, timeout: float = 10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.exists():
                return
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        stdout, stderr = process.communicate(timeout=2)
        raise AssertionError(
            f"{path.name} was not written; exit={process.returncode}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )

    first_ready = tmp_path / "first-ready"
    first_started = tmp_path / "first-started"
    first_activated = tmp_path / "first-activated"
    first = subprocess.Popen(
        [sys.executable, "-c", script],
        cwd=REPO,
        env=make_env(first_ready, first_started, first_activated, 15000),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        wait_for_file(first_ready, first)

        second_started = tmp_path / "second-started"
        second = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO,
            env=make_env(
                tmp_path / "second-ready",
                second_started,
                tmp_path / "second-activated",
                15000,
            ),
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert second.returncode == 0, second.stderr
        assert not second_started.exists()
        wait_for_file(first_activated, first)
        stdout, stderr = first.communicate(timeout=5)
        assert first.returncode == 0, stderr
        assert not stdout

        third_ready = tmp_path / "third-ready"
        third = subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=REPO,
            env=make_env(
                third_ready,
                tmp_path / "third-started",
                tmp_path / "third-activated",
                1000,
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        wait_for_file(third_ready, third)
        third_stdout, third_stderr = third.communicate(timeout=5)
        assert third.returncode == 0, third_stderr
        assert not third_stdout
    finally:
        if first.poll() is None:
            first.terminate()
            first.wait(timeout=5)
