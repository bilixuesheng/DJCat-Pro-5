import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from server import ai_markdown, error_reports

API = "https://api.djcatpro.top"
ADMIN = "https://dash.djcatpro.top"


def _report(**overrides):
    report = {
        "machine_id": "a" * 64,
        "client_version": "5.2.0-kb261009",
        "os": "Windows 10 (10.0.19045)",
        "exception_type": "AttributeError",
        "message": "'NoneType' object has no attribute 'setText'",
        "frames": [
            {"file": "djcat.py", "function": "main", "line": 120},
            {"file": "app/view/pages/home_page.py", "function": "_onTimeout", "line": 88},
        ],
        "traceback": (
            "Traceback (most recent call last):\n"
            '  File "app/view/pages/home_page.py", line 88, in _onTimeout\n'
            "AttributeError: 'NoneType' object has no attribute 'setText'"
        ),
    }
    report.update(overrides)
    return report


class ErrorSignatureTest(TestCase):
    def testTimesAddressesPathsAndCountsDoNotSplitAGroup(self):
        frames = _report()["frames"]
        first = error_reports.errorSignature(
            "RuntimeError",
            "2026-10-09 08:01:02 Internal C++ object (PySide6.QtWidgets.QLabel at "
            "0x000001F2A3B4C5D0) already deleted; 3 timers left; "
            "path C:\\Users\\student\\AppData\\Local\\DJCatPro\\Log\\a.log",
            frames,
        )
        second = error_reports.errorSignature(
            "RuntimeError",
            "2026-10-10 17:45:59 Internal C++ object (PySide6.QtWidgets.QLabel at "
            "0x7ff00012ab00) already deleted; 12 timers left; "
            "path D:\\DJCat\\DJCatPro\\Log\\b.log",
            frames,
        )

        self.assertEqual(first, second)

    def testLineNumbersAndInstallLocationsDoNotSplitAGroup(self):
        here = [
            {"file": "app/view/pages/home_page.py", "function": "_onTimeout", "line": 88},
            {"file": "C:\\Python312\\Lib\\threading.py", "function": "run", "line": 1010},
            {
                "file": "C:\\venv\\Lib\\site-packages\\qfluentwidgets\\common\\icon.py",
                "function": "paint",
                "line": 40,
            },
        ]
        there = [
            {"file": "app\\view\\pages\\home_page.py", "function": "_onTimeout", "line": 95},
            {"file": "/usr/lib/python3.12/threading.py", "function": "run", "line": 1012},
            {
                "file": "D:/DJCat/site-packages/qfluentwidgets/common/icon.py",
                "function": "paint",
                "line": 41,
            },
        ]

        self.assertEqual(
            error_reports.errorSignature("KeyError", "'key'", here),
            error_reports.errorSignature("KeyError", "'key'", there),
        )

    def testDifferentCodePathsOrMessagesAreDifferentGroups(self):
        frames = _report()["frames"]
        signature = error_reports.errorSignature("AttributeError", "no attribute 'a'", frames)

        self.assertNotEqual(
            signature,
            error_reports.errorSignature("AttributeError", "no attribute 'b'", frames),
        )
        self.assertNotEqual(
            signature,
            error_reports.errorSignature("TypeError", "no attribute 'a'", frames),
        )
        self.assertNotEqual(
            signature,
            error_reports.errorSignature(
                "AttributeError",
                "no attribute 'a'",
                frames[:-1] + [dict(frames[-1], function="_onClicked")],
            ),
        )


class ErrorReportServerTest(TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDir.cleanup)
        patches = (
            patch.object(
                ai_markdown, "DATABASE_PATH", Path(self.tempDir.name) / "usage.sqlite3"
            ),
            patch.dict(
                os.environ,
                {
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                    "DJCATAI_ADMIN_HOST": "dash.djcatpro.top",
                    "DJCATAI_ADMIN_USERNAME": "admin",
                    "DJCATAI_ADMIN_PASSWORD_HASH": generate_password_hash("secret"),
                },
            ),
        )
        for active in patches:
            active.start()
            self.addCleanup(active.stop)
        ai_markdown.app.config.update(
            TESTING=True, SECRET_KEY="test-session-secret", SESSION_COOKIE_SECURE=True
        )
        self.client = ai_markdown.app.test_client()

    def _submit(self, report=None, **overrides):
        return self.client.post(
            "/error-reports", base_url=API, json=report or _report(**overrides)
        )

    def _rows(self, query, *args):
        with error_reports._open(ai_markdown._connect) as database:
            return [tuple(row) for row in database.execute(query, args)]

    def _csrf(self, response):
        return re.search(rb'name="csrf_token" value="([^"]+)"', response.data).group(1).decode()

    def _login(self):
        login = self.client.get("/admin/login", base_url=ADMIN)
        self.client.post(
            "/admin/login",
            base_url=ADMIN,
            data={"csrf_token": self._csrf(login), "username": "admin", "password": "secret"},
        )

    def testTheSameErrorFromOneMachineIsOneRowCountingEachTime(self):
        for _ in range(3):
            self.assertEqual(self._submit().status_code, 200)

        self.assertEqual(self._rows("SELECT COUNT(*) FROM error_groups"), [(1,)])
        self.assertEqual(
            self._rows("SELECT count FROM error_occurrences"), [(3,)]
        )

    def testEachMachineAndDayGetsItsOwnRowInTheSameGroup(self):
        self._submit()
        self._submit(machine_id="b" * 64)
        tomorrow = datetime.now(error_reports.TIMEZONE) + timedelta(days=1)
        report = error_reports.parseReport(_report())
        machine = ai_markdown._machineId("a" * 64)
        error_reports.recordReport(ai_markdown._connect, machine, report, now=tomorrow)

        self.assertEqual(self._rows("SELECT COUNT(*) FROM error_groups"), [(1,)])
        self.assertEqual(self._rows("SELECT COUNT(*) FROM error_occurrences"), [(3,)])

    def testReportsAreStoredUnderTheMachineIdentityNotTheRawId(self):
        self._submit()

        stored = self._rows("SELECT machine_id FROM error_occurrences")[0][0]
        self.assertEqual(stored, ai_markdown._machineId("a" * 64))
        self.assertNotEqual(stored, "a" * 64)

    def testInvalidReportsAreRejected(self):
        self.assertEqual(self._submit(machine_id="not-hex").status_code, 400)
        self.assertEqual(self._submit(exception_type="").status_code, 400)
        self.assertEqual(self._submit(frames="app.py").status_code, 400)
        self.assertEqual(
            self._submit(frames=[{"file": "a.py", "function": "f", "line": "1"}]).status_code,
            400,
        )
        self.assertEqual(
            self.client.post("/error-reports", base_url=API, data="nope").status_code, 400
        )
        self.assertEqual(self._rows("SELECT COUNT(*) FROM error_groups"), [(0,)])

    def testLongTracebacksKeepTheEndWhereTheExceptionIs(self):
        traceback = "x" * 50_000 + "\nValueError: the end"
        self._submit(traceback=traceback)

        stored = self._rows("SELECT traceback FROM error_groups")[0][0]
        self.assertEqual(len(stored), error_reports.MAX_TRACEBACK_LENGTH)
        self.assertTrue(stored.endswith("ValueError: the end"))

    def testAMachineIsCappedPerDay(self):
        with patch.object(error_reports, "MACHINE_DAILY_LIMIT", 2):
            self.assertEqual(self._submit().status_code, 200)
            self.assertEqual(self._submit(exception_type="KeyError").status_code, 200)
            self.assertEqual(self._submit().status_code, 429)
            self.assertEqual(self._submit(machine_id="b" * 64).status_code, 200)

        self.assertEqual(
            self._rows("SELECT SUM(count) FROM error_occurrences"), [(3,)]
        )

    def testNewGroupsAreCappedPerDayButKnownGroupsStillCount(self):
        with patch.object(error_reports, "NEW_SIGNATURES_DAILY_LIMIT", 1):
            self.assertEqual(self._submit().status_code, 200)
            self.assertEqual(self._submit(exception_type="KeyError").status_code, 429)
            self.assertEqual(self._submit(machine_id="b" * 64).status_code, 200)

    def testOldOccurrencesExpireOnTheNextReportAndTakeEmptyGroupsWithThem(self):
        machine = ai_markdown._machineId("a" * 64)
        longAgo = datetime.now(error_reports.TIMEZONE) - timedelta(
            days=error_reports.RETENTION_DAYS + 1
        )
        error_reports.recordReport(
            ai_markdown._connect,
            machine,
            error_reports.parseReport(_report(exception_type="OldError")),
            now=longAgo,
        )

        self._submit()

        self.assertEqual(
            self._rows("SELECT exception_type FROM error_groups"), [("AttributeError",)]
        )

    def testReportsOnlyArriveOnTheApiHost(self):
        self.assertEqual(
            self.client.post("/error-reports", base_url=ADMIN, json=_report()).status_code,
            404,
        )

    def testAdminListsGroupsAndShowsWhichMachinesHitThem(self):
        self._submit()
        self._submit(machine_id="b" * 64)
        self._login()

        listing = self.client.get("/admin/error-reports/", base_url=ADMIN)
        text = listing.get_data(as_text=True)
        self.assertEqual(listing.status_code, 200)
        self.assertIn("AttributeError", text)
        self.assertIn("<code>app/view/pages/home_page.py:88</code><br><small>_onTimeout</small>", text)
        self.assertIn("客户端报错", text)

        groupId = self._rows("SELECT id FROM error_groups")[0][0]
        detail = self.client.get(f"/admin/error-reports/{groupId}", base_url=ADMIN)
        text = detail.get_data(as_text=True)
        self.assertEqual(detail.status_code, 200)
        self.assertIn("2 次 · 2 台电脑", text)
        self.assertIn("DJ-000001", text)
        self.assertIn("DJ-000002", text)
        self.assertIn("Traceback (most recent call last)", text)

    def testAdminPagesRequireLogin(self):
        response = self.client.get("/admin/error-reports/", base_url=ADMIN)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login", response.headers["Location"])

    def testDeletingAGroupRemovesItsOccurrences(self):
        self._submit()
        self._login()
        listing = self.client.get("/admin/error-reports/", base_url=ADMIN)
        groupId = self._rows("SELECT id FROM error_groups")[0][0]

        response = self.client.post(
            f"/admin/error-reports/{groupId}/delete",
            base_url=ADMIN,
            data={"csrf_token": self._csrf(listing)},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("redirect", response.get_json())
        self.assertEqual(self._rows("SELECT COUNT(*) FROM error_groups"), [(0,)])
        self.assertEqual(self._rows("SELECT COUNT(*) FROM error_occurrences"), [(0,)])

    def testDeletingFromTheDetailPageGoesBackToTheList(self):
        self._submit()
        self._login()
        groupId = self._rows("SELECT id FROM error_groups")[0][0]
        detail = self.client.get(f"/admin/error-reports/{groupId}", base_url=ADMIN)

        response = self.client.post(
            f"/admin/error-reports/{groupId}/delete",
            base_url=ADMIN,
            data={"csrf_token": self._csrf(detail), "from": "detail"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertTrue(response.get_json()["redirect"].endswith("/admin/error-reports/"))
