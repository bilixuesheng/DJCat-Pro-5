"""Which days count as DeepSeek off-peak when holiday exemption is on.

The rule follows the official Chinese working calendar, not the day of the week:
statutory holidays are off-peak for the whole break (including weekdays borrowed
for it), and make-up working days (调休补班) are peak even on a weekend. Every
other day falls back to Monday-Friday peak, Saturday-Sunday off-peak.
"""

import json
from contextlib import closing
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests

from server import ai_markdown
from tests import test_ai_admin

# 2026 年国务院放假安排里的几天（来自 holiday-cn 数据）。
CALENDAR_2026 = {
    "2026-02-14": False,  # 周六，春节调休补班
    "2026-02-18": True,  # 周三，春节
    "2026-04-06": True,  # 周一，清明
    "2026-10-05": True,  # 周一，国庆
    "2026-10-10": False,  # 周六，国庆调休补班
}


def _at(day, hour=10):
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").replace(
        tzinfo=ai_markdown.TIMEZONE
    )


class OffPeakCalendarTest(TestCase):
    setUp = test_ai_admin.AIAdminTest.setUp

    def _seed(self, days, holidayExempt=True):
        ai_markdown._connect().close()
        with closing(ai_markdown._connect()) as database:
            database.execute(
                "INSERT INTO settings(key, value) VALUES ('holiday_calendar', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (json.dumps({"refreshed": ai_markdown._today(), "days": days}),),
            )
            database.execute(
                "INSERT INTO settings(key, value) VALUES ('holiday_exempt', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("1" if holidayExempt else "0",),
            )
            database.commit()

    def _cost(self, day, hour=10):
        # 日历已是今天刷新的，不该再去联网；真要联网就让它失败以暴露出来。
        with patch.object(
            ai_markdown.requests, "get", side_effect=AssertionError("no network")
        ):
            return ai_markdown._quotaCost(_at(day, hour), peakEnabled=True)

    def testAMakeUpWorkingSaturdayIsPeak(self):
        self._seed(CALENDAR_2026)
        self.assertEqual(self._cost("2026-02-14"), 2)
        self.assertEqual(self._cost("2026-10-10"), 2)

    def testWeekdaysInsideAHolidayBreakAreOffPeak(self):
        # nager.at 每个节日只给一天：春节只有 02-17、国庆只有 10-01、清明没有。
        self._seed(CALENDAR_2026)
        for day in ("2026-02-18", "2026-04-06", "2026-10-05"):
            with self.subTest(day=day):
                self.assertEqual(self._cost(day), 1)

    def testOrdinaryDaysFollowTheWeekdayRule(self):
        self._seed(CALENDAR_2026)
        self.assertEqual(self._cost("2026-03-07"), 1)  # 普通周六
        self.assertEqual(self._cost("2026-03-11"), 2)  # 普通周三

    def testOffPeakHoursAreNeverDoubled(self):
        self._seed(CALENDAR_2026)
        self.assertEqual(self._cost("2026-02-14", hour=20), 1)

    def testTheExemptionSwitchStillGovernsTheCalendar(self):
        self._seed(CALENDAR_2026, holidayExempt=False)
        self.assertEqual(self._cost("2026-02-18"), 2)
        self.assertEqual(self._cost("2026-03-07"), 2)


class OffPeakCalendarRefreshTest(TestCase):
    setUp = test_ai_admin.AIAdminTest.setUp

    def _response(self, days):
        response = MagicMock(ok=True)
        response.json.return_value = {
            "year": 2026,
            "days": [
                {"name": "节日", "date": day, "isOffDay": off}
                for day, off in days.items()
            ],
        }
        return response

    def testRefreshReadsBothHolidaysAndMakeUpWorkdays(self):
        ai_markdown._connect().close()
        missing = MagicMock(ok=False, status_code=404)
        with patch.object(
            ai_markdown.requests,
            "get",
            side_effect=[self._response(CALENDAR_2026), missing],
        ) as fetch:
            ai_markdown._refreshHolidayCache()

        calendar = ai_markdown._offPeakCalendar()
        self.assertIs(calendar["2026-02-18"], True)
        self.assertIs(calendar["2026-02-14"], False)
        self.assertIn("NateScarlet/holiday-cn", fetch.call_args_list[0].args[0])

    def testAFailedFetchIsNotRetriedWithinTheSameDay(self):
        ai_markdown._connect().close()
        with patch.object(
            ai_markdown.requests,
            "get",
            side_effect=requests.ConnectionError("unreachable"),
        ) as fetch:
            ai_markdown._refreshHolidayCache()
            firstAttempt = fetch.call_count
            ai_markdown._refreshHolidayCache()
            ai_markdown._refreshHolidayCache()

        # 拉不到时也要记下今天已经试过，否则峰时每个整理请求和每次仪表盘轮询
        # 都会再等一轮超时。
        self.assertGreater(firstAttempt, 0)
        self.assertEqual(fetch.call_count, firstAttempt)

    def testAYearThatFailsToLoadKeepsWhatWasKnownForIt(self):
        ai_markdown._connect().close()
        with closing(ai_markdown._connect()) as database:
            database.execute(
                "INSERT INTO settings(key, value) VALUES ('holiday_calendar', ?)",
                (
                    json.dumps(
                        {
                            "refreshed": "2000-01-01",
                            "days": {"2026-10-05": True, "2027-02-06": True},
                        }
                    ),
                ),
            )
            database.commit()

        # 今年那份拉到了（不含 10-05 的旧值也应被新数据取代），明年那份失败。
        fresh = {"2026-02-14": False}
        with patch.object(
            ai_markdown.requests,
            "get",
            side_effect=[self._response(fresh), requests.ConnectionError("x")],
        ), patch.object(ai_markdown, "_today", return_value="2026-09-23"), patch.object(
            ai_markdown, "datetime", wraps=datetime
        ) as clock:
            clock.now.return_value = datetime(2026, 9, 23, tzinfo=ai_markdown.TIMEZONE)
            ai_markdown._refreshHolidayCache()

        calendar = ai_markdown._offPeakCalendar()
        self.assertIs(calendar["2026-02-14"], False)
        self.assertNotIn("2026-10-05", calendar)
        self.assertIs(calendar["2027-02-06"], True)
