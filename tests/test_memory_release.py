import time
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent
from PySide6.QtGui import QHideEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.config.cfg import cfg
from app.view.components.window_background import WindowBackground
from app.view.windows import memory_release
from app.view.windows.memory_release import MemoryRelease
from tests.support import isolateCfg

RELEASE_MS = 200
RETRY_MS = 60
STARTUP_MS = 60
SETTLE_MS = 1500


def _waitUntil(condition):
    # 机器一忙，定时器会晚到；等得到就行，不卡着点。
    deadline = time.monotonic() + SETTLE_MS / 1000
    while not condition() and time.monotonic() < deadline:
        QTest.qWait(10)


class _Pages:
    """Stands in for MainWindow._unloadIdlePages(): answers False while a page must wait."""

    def __init__(self, answers=(True,)):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class MemoryReleaseTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        for name, value in (
            ("RELEASE_AFTER_HIDDEN_MS", RELEASE_MS),
            ("RETRY_RELEASE_MS", RETRY_MS),
            ("TRIM_AFTER_SILENT_STARTUP_MS", STARTUP_MS),
        ):
            patcher = patch.object(memory_release, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        trim = patch.object(memory_release, "trimWorkingSet")
        self.trim = trim.start()
        self.addCleanup(trim.stop)

    def _window(self, shown=True):
        window = QWidget()
        self.addCleanup(self._close, window)
        if shown:
            window.show()
            self.app.processEvents()
        return window

    def _close(self, widget):
        widget.hide()
        widget.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _release(self, window, pages, isSilent=False):
        release = MemoryRelease(window, pages, isSilent)
        self.addCleanup(release.stop)
        return release

    def testTenMinutesInTheTrayUnloadsThePagesThenTrimsOnce(self):
        window = self._window()
        pages = _Pages()
        self._release(window, pages)

        window.hide()
        _waitUntil(lambda: self.trim.called)
        QTest.qWait(RETRY_MS * 3)

        self.assertEqual(pages.calls, 1)
        self.trim.assert_called_once_with()

    def testShowingTheWindowAgainCancelsTheRelease(self):
        window = self._window()
        pages = _Pages()
        release = self._release(window, pages)

        window.hide()
        self.assertTrue(release._releaseTimer.isActive())
        window.show()
        QTest.qWait(RELEASE_MS + RETRY_MS)

        self.assertFalse(release._releaseTimer.isActive())
        self.assertEqual(pages.calls, 0)
        self.trim.assert_not_called()

    def testMinimizingIsNotHiding(self):
        window = self._window()
        pages = _Pages()
        release = self._release(window, pages)

        # 最小化时 Qt 发一个系统来的 Hide，窗口却没有藏起来。
        QApplication.sendEvent(window, QHideEvent())

        self.assertFalse(window.isHidden())
        self.assertFalse(release._releaseTimer.isActive())

    def testHidingAgainStartsTheTenMinutesOver(self):
        window = self._window()
        pages = _Pages()
        release = self._release(window, pages)

        window.hide()
        QTest.qWait(RELEASE_MS // 2)
        window.show()
        window.hide()

        self.assertGreater(release._releaseTimer.remainingTime(), RELEASE_MS * 3 // 4)

    def testAPageThatMustWaitIsTriedEveryMinuteAndTheTrimWaitsForIt(self):
        window = self._window()
        pages = _Pages(answers=(False, False, True))
        self._release(window, pages)

        window.hide()
        _waitUntil(lambda: pages.calls == 1)
        self.trim.assert_not_called()

        _waitUntil(lambda: self.trim.called)
        QTest.qWait(RETRY_MS * 3)
        self.assertEqual(pages.calls, 3)
        self.trim.assert_called_once_with()

    def testAPageBuiltWhileHiddenIsUnloadedTenMinutesLater(self):
        window = self._window()
        pages = _Pages()
        release = self._release(window, pages)
        window.hide()
        _waitUntil(lambda: pages.calls == 1)

        # 从托盘点了 Application Home Card，应用市场在主窗口藏着时建了起来。
        release.onPageLoaded()

        _waitUntil(lambda: pages.calls == 2)
        self.assertEqual(pages.calls, 2)

    def testAPageBuiltWhileTheWindowIsShownChangesNothing(self):
        window = self._window()
        pages = _Pages()
        release = self._release(window, pages)

        release.onPageLoaded()
        QTest.qWait(RELEASE_MS * 2)

        self.assertEqual(pages.calls, 0)

    def testADisplayWindowOnScreenSkipsTheTrimButNotTheUnload(self):
        window = self._window()
        pages = _Pages()
        self._release(window, pages)
        display = QWidget()
        WindowBackground(
            cfg.broadcastBackgroundMode,
            cfg.broadcastBackgroundColor,
            cfg.broadcastBackgroundImagePath,
            cfg.broadcastBackgroundScaleMode,
            parent=display,
        )
        self.addCleanup(self._close, display)
        display.show()

        window.hide()
        _waitUntil(lambda: pages.calls == 1)
        QTest.qWait(RETRY_MS)

        self.assertEqual(pages.calls, 1)
        self.trim.assert_not_called()

    def testSilentStartupTrimsOnceAfterAMinute(self):
        window = self._window(shown=False)
        pages = _Pages()
        unloadsBeforeEachTrim = []
        self.trim.side_effect = lambda: unloadsBeforeEachTrim.append(pages.calls)
        self._release(window, pages, isSilent=True)

        _waitUntil(lambda: self.trim.called)

        # 静默启动时主窗口本来就藏着，十分钟那次随后也会来；第一次修剪是启动后那次，还没卸过页面。
        self.assertEqual(unloadsBeforeEachTrim[0], 0)

    def testSilentStartupTrimIsDroppedOnceTheWindowIsShown(self):
        window = self._window(shown=False)
        pages = _Pages()
        self._release(window, pages, isSilent=True)

        window.show()
        QTest.qWait(STARTUP_MS * 2)

        self.trim.assert_not_called()

    def testEagerPageLoadingNeitherUnloadsNorTrims(self):
        cfg.set(cfg.eagerPageLoading, True)
        window = self._window(shown=False)
        pages = _Pages()
        self._release(window, pages, isSilent=True)

        QTest.qWait(RELEASE_MS + STARTUP_MS + RETRY_MS)

        self.assertEqual(pages.calls, 0)
        self.trim.assert_not_called()

    def testStopEndsEverything(self):
        window = self._window(shown=False)
        pages = _Pages()
        release = self._release(window, pages, isSilent=True)

        release.stop()
        window.show()
        window.hide()
        QTest.qWait(RELEASE_MS + STARTUP_MS + RETRY_MS)

        self.assertEqual(pages.calls, 0)
        self.trim.assert_not_called()
