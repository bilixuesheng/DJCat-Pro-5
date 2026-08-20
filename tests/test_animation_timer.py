from __future__ import annotations

from unittest.mock import patch

import pytest

from app.platform import animation_timer


def test_unlock_qt_animations_uses_minimum_nonzero_interval():
    assert animation_timer.UNLOCKED_TIMER_INTERVAL_MS == 1

    timer = animation_timer._QtAnimationTimer.create()

    try:
        timer.setInterval(animation_timer.UNLOCKED_TIMER_INTERVAL_MS)
    finally:
        timer.setInterval(16)


def test_unlock_qt_animations_is_idempotent():
    timer = animation_timer._QtAnimationTimer(None, lambda: 1, lambda *_: None)

    with (
        patch.object(animation_timer, "_animationTimer", None),
        patch.object(
            animation_timer._QtAnimationTimer,
            "create",
            return_value=timer,
        ) as create,
        patch.object(timer, "setInterval") as setInterval,
    ):
        animation_timer.unlockQtAnimations()
        animation_timer.unlockQtAnimations()

    create.assert_called_once_with()
    setInterval.assert_called_once_with(
        animation_timer.UNLOCKED_TIMER_INTERVAL_MS
    )


def test_qt_core_loader_stays_inside_pyside_runtime(tmp_path):
    qtRoot = tmp_path / "runtime"
    qtRoot.mkdir()
    (tmp_path / "libQt6Core.so.6").touch()

    with (
        patch.object(animation_timer.sys, "platform", "linux"),
        patch.object(
            animation_timer.QLibraryInfo,
            "path",
            return_value=str(qtRoot),
        ),
        pytest.raises(RuntimeError, match="找不到 Qt6Core"),
    ):
        animation_timer._QtAnimationTimer._loadQtCore()
