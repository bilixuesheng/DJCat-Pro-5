from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import QLibraryInfo

from app.platform import animation_timer


def test_qt_animation_timer_takes_both_intervals():
    assert animation_timer.UNLOCKED_TIMER_INTERVAL_MS == 1
    assert animation_timer.DEFAULT_TIMER_INTERVAL_MS == 16

    timer = animation_timer._QtAnimationTimer.create()

    try:
        timer.setInterval(animation_timer.UNLOCKED_TIMER_INTERVAL_MS)
    finally:
        timer.setInterval(animation_timer.DEFAULT_TIMER_INTERVAL_MS)


def _isolatedTimer():
    timer = animation_timer._QtAnimationTimer(None, lambda: 1, lambda *_: None)
    return (
        patch.object(animation_timer, "_animationTimer", None),
        patch.object(animation_timer, "_timerUnavailable", False),
        patch.object(animation_timer._QtAnimationTimer, "create", return_value=timer),
        patch.object(timer, "setInterval"),
    )


def test_super_frame_rate_switches_between_one_and_sixteen_ms():
    state, unavailable, create, interval = _isolatedTimer()
    with state, unavailable, create as created, interval as setInterval:
        animation_timer.setSuperFrameRateEnabled(True)
        animation_timer.setSuperFrameRateEnabled(False)
        animation_timer.setSuperFrameRateEnabled(True)

    created.assert_called_once_with()
    assert [call.args[0] for call in setInterval.call_args_list] == [1, 16, 1]


def test_super_frame_rate_off_from_startup_leaves_qt_alone():
    state, unavailable, create, interval = _isolatedTimer()
    with state, unavailable, create as created, interval as setInterval:
        animation_timer.setSuperFrameRateEnabled(False)

    created.assert_not_called()
    setInterval.assert_not_called()


def test_super_frame_rate_falls_back_once_when_qt_hides_the_timer():
    with (
        patch.object(animation_timer, "_animationTimer", None),
        patch.object(animation_timer, "_timerUnavailable", False),
        patch.object(
            animation_timer._QtAnimationTimer,
            "create",
            side_effect=RuntimeError("当前 QtCore 未导出 QUnifiedTimer"),
        ) as create,
        patch.object(animation_timer.logger, "warning") as warning,
    ):
        animation_timer.setSuperFrameRateEnabled(True)
        animation_timer.setSuperFrameRateEnabled(False)
        animation_timer.setSuperFrameRateEnabled(True)

    create.assert_called_once_with()
    warning.assert_called_once()


def test_qt_core_is_the_copy_already_in_the_process(tmp_path):
    # Nuitka puts Qt6Core beside djcat.exe, where QLibraryInfo never points.
    with patch.object(QLibraryInfo, "path", return_value=str(tmp_path)):
        timer = animation_timer._QtAnimationTimer.create()

    timer.setInterval(animation_timer.DEFAULT_TIMER_INTERVAL_MS)
