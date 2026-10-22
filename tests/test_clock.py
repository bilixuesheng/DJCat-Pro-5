from datetime import date, datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

from app.common import clock
from app.config.cfg import cfg
from tests.support import isolateCfg

FRIDAY = date(2026, 10, 23)
MONDAY = date(2026, 10, 26)
THURSDAY = date(2026, 10, 29)


class FakeSources:
    def __init__(self, system=1_000_000.0, counter=50.0):
        self.system = system
        self.counter = counter

    def clock(self):
        return clock.Clock(lambda: self.system, lambda: self.counter)


class CalibratedTimeTest(TestCase):
    def testIsSystemTimeUntilTheFirstSync(self):
        sources = FakeSources()
        calibrated = sources.clock()

        self.assertEqual(calibrated.epoch(), 1_000_000.0)
        sources.system += 3600
        self.assertEqual(calibrated.epoch(), 1_003_600.0)
        self.assertIsNone(calibrated.deviation())

    def testFollowsTheCounterAfterASyncEvenWhenWindowsClockIsChanged(self):
        sources = FakeSources()
        calibrated = sources.clock()
        # 服务器说此刻是 1_000_002.4：系统时钟慢了 2.4 秒。
        calibrated.synchronize(1_000_002.4, sources.counter)

        self.assertAlmostEqual(calibrated.deviation(), 2.4)
        sources.counter += 10
        sources.system += 10 + 3600
        self.assertAlmostEqual(calibrated.epoch(), 1_000_012.4)

    def testForgettingTheSyncGoesBackToSystemTime(self):
        sources = FakeSources()
        calibrated = sources.clock()
        calibrated.synchronize(1_000_002.4, sources.counter)

        calibrated.forget()

        self.assertEqual(calibrated.epoch(), 1_000_000.0)
        self.assertIsNone(calibrated.deviation())

    def testNowIsAwareLocalTime(self):
        calibrated = FakeSources(system=datetime(2026, 10, 23, 8, 0).timestamp()).clock()

        now = calibrated.now()

        self.assertIsNotNone(now.tzinfo)
        self.assertEqual((now.hour, now.minute, now.second), (8, 0, 0))


def at(day, hour=8, minute=0, second=0, microsecond=0):
    return datetime(day.year, day.month, day.day, hour, minute, second, microsecond).astimezone()


class TimeOffsetTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        cfg.set(cfg.timeOffsetEnabled, False, save=False)
        cfg.set(cfg.timeOffset, 0.0, save=False)
        cfg.set(cfg.timeOffsetDate, "", save=False)
        cfg.set(cfg.dailyDriftEnabled, False, save=False)
        cfg.set(cfg.dailyDrift, 0.0, save=False)
        cfg.set(cfg.timeOffsetExemptions, [], save=False)

    def useOffset(self, value, anchor=FRIDAY, drift=None):
        cfg.set(cfg.timeOffsetEnabled, True, save=False)
        cfg.set(cfg.timeOffset, value, save=False)
        cfg.set(cfg.timeOffsetDate, anchor.isoformat(), save=False)
        if drift is not None:
            cfg.set(cfg.dailyDriftEnabled, True, save=False)
            cfg.set(cfg.dailyDrift, drift, save=False)

    def testNoOffsetUntilTheSwitchIsOn(self):
        cfg.set(cfg.timeOffset, -3.0, save=False)

        self.assertEqual(clock.timeOffset(FRIDAY), 0)

        cfg.set(cfg.timeOffsetEnabled, True, save=False)
        self.assertEqual(clock.timeOffset(FRIDAY), -3.0)

    def testDailyDriftCountsCalendarDaysIncludingTheWeekend(self):
        self.useOffset(-3.0, drift=-0.5)

        self.assertEqual(clock.timeOffset(FRIDAY), -3.0)
        self.assertEqual(clock.timeOffset(MONDAY), -4.5)

    def testOffsetKeepsMillisecondsAndDailyDriftKeepsTenths(self):
        self.useOffset(-3.2154, drift=-0.54)

        self.assertEqual(cfg.timeOffset.value, -3.215)
        self.assertEqual(cfg.dailyDrift.value, -0.5)
        self.assertEqual(clock.timeOffset(MONDAY), -4.715)

    def testDayBeforeTheAnchorDoesNotDriftBackwards(self):
        self.useOffset(-3.0, drift=-0.5)

        self.assertEqual(clock.timeOffset(FRIDAY - timedelta(days=5)), -3.0)

    def testBellTimeIsCalibratedTimePlusTheOffset(self):
        self.useOffset(-3.2)

        self.assertEqual(
            clock.bellTime(at(FRIDAY, 8, 0, 3, 200_000)),
            at(FRIDAY, 8, 0, 0),
        )

    def testExemptKindsUseCalibratedTime(self):
        self.useOffset(-3.0)
        cfg.set(cfg.timeOffsetExemptions, ["shutdown"], save=False)
        calibrated = at(FRIDAY, 8, 0, 3)

        self.assertEqual(clock.scheduledTaskTime("broadcast", calibrated), at(FRIDAY))
        self.assertEqual(clock.scheduledTaskTime("home-card", calibrated), at(FRIDAY))
        self.assertEqual(clock.scheduledTaskTime("shutdown", calibrated), calibrated)


class TimeOffsetRulesTest(TestCase):
    """改规则时的冻结与重新起算，经 cfg 的改动触发，与设置页怎么改无关。"""

    def setUp(self):
        isolateCfg(self)
        clock.bindTimeOffset()
        self.today = FRIDAY
        patcher = patch.object(clock, "calibratedNow", lambda: at(self.today))
        patcher.start()
        self.addCleanup(patcher.stop)
        cfg.set(cfg.timeOffsetEnabled, True, save=False)
        cfg.set(cfg.dailyDriftEnabled, True, save=False)
        cfg.set(cfg.dailyDrift, -0.5, save=False)
        cfg.set(cfg.timeOffset, -3.0, save=False)
        cfg.set(cfg.timeOffsetDate, FRIDAY.isoformat(), save=False)

    def testEditingTheOffsetStartsCountingFromToday(self):
        self.today = MONDAY
        self.assertEqual(clock.offsetValue(MONDAY), -4.5)

        cfg.set(cfg.timeOffset, -2.0, save=False)

        self.assertEqual(cfg.timeOffsetDate.value, MONDAY.isoformat())
        self.assertEqual(clock.timeOffset(THURSDAY), -3.5)

    def testTurningDailyDriftOffFreezesTheValueReachedSoFar(self):
        self.today = MONDAY
        cfg.set(cfg.dailyDriftEnabled, False, save=False)

        self.assertEqual(clock.timeOffset(THURSDAY), -4.5)

        self.today = THURSDAY
        cfg.set(cfg.dailyDriftEnabled, True, save=False)
        self.assertEqual(clock.timeOffset(THURSDAY), -4.5)
        self.assertEqual(clock.timeOffset(THURSDAY + timedelta(days=1)), -5.0)

    def testTurningTheOffsetOffFreezesItTooAndOffDaysDoNotCount(self):
        self.today = MONDAY
        cfg.set(cfg.timeOffsetEnabled, False, save=False)

        self.assertEqual(clock.timeOffset(THURSDAY), 0)
        self.assertEqual(clock.offsetValue(THURSDAY), -4.5)

        self.today = THURSDAY
        cfg.set(cfg.timeOffsetEnabled, True, save=False)
        self.assertEqual(clock.timeOffset(THURSDAY), -4.5)

    def testChangingTheDailyAmountDoesNotRewriteThePast(self):
        self.today = MONDAY
        cfg.set(cfg.dailyDrift, 1.0, save=False)

        self.assertEqual(clock.timeOffset(MONDAY), -4.5)
        self.assertEqual(clock.timeOffset(THURSDAY), -1.5)
