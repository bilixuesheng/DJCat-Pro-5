from __future__ import annotations

from unittest.mock import patch

from loguru import logger

from app.platform import memory

MB = 1024 * 1024


def _captured():
    messages = []
    handle = logger.add(lambda message: messages.append(message.record), level="INFO")
    return messages, handle


def test_trim_logs_the_working_set_before_and_after_and_what_stays_committed():
    messages, handle = _captured()
    calls = []
    counters = iter([(312 * MB + 5, 270 * MB), (48 * MB, 260 * MB + 9)])
    try:
        with (
            patch.object(memory.os, "name", "nt"),
            patch.object(
                memory,
                "_memoryCounters",
                side_effect=lambda: calls.append("measure") or next(counters),
            ),
            patch.object(memory, "_emptyWorkingSet", side_effect=lambda: calls.append("empty")),
        ):
            memory.trimWorkingSet()
    finally:
        logger.remove(handle)

    assert calls == ["measure", "empty", "measure"]
    assert [record["message"] for record in messages] == [
        "修剪内存：工作集 312→48 MB，private 260 MB"
    ]


def test_a_failed_trim_is_logged_and_swallowed():
    messages, handle = _captured()
    try:
        with (
            patch.object(memory.os, "name", "nt"),
            patch.object(memory, "_memoryCounters", return_value=(1, 1)),
            patch.object(memory, "_emptyWorkingSet", side_effect=OSError("拒绝访问")),
        ):
            memory.trimWorkingSet()
    finally:
        logger.remove(handle)

    assert [record["message"] for record in messages] == ["修剪内存失败"]


def test_nothing_happens_outside_windows():
    with (
        patch.object(memory.os, "name", "posix"),
        patch.object(memory, "_memoryCounters") as counters,
        patch.object(memory, "_emptyWorkingSet") as empty,
    ):
        memory.trimWorkingSet()

    counters.assert_not_called()
    empty.assert_not_called()
