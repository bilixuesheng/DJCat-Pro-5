import sys
from pathlib import Path, PureWindowsPath
from unittest import TestCase
from unittest.mock import patch

import requests

from app.common import error_report
from server import error_reports

BOOM = "def boom(path):\n    raise FileNotFoundError(path)\nboom(PATH)\n"


def _raiseIn(filename, path="missing.png"):
    try:
        exec(compile(BOOM, filename, "exec"), {"PATH": path})
    except FileNotFoundError:
        return sys.exc_info()
    raise AssertionError("BOOM did not raise")


class ErrorReportBuildTest(TestCase):
    def testFramesAreRelativeToTheProgramDirectory(self):
        with patch.object(error_report, "APP_DIR", Path("/opt/DJCat")):
            excInfo = _raiseIn("/opt/DJCat/app/view/pages/home_page.py")
            report = error_report.buildReport(*excInfo, "a" * 64)

        self.assertEqual(
            report["frames"][-1],
            {"file": "app/view/pages/home_page.py", "function": "boom", "line": 2},
        )
        self.assertEqual(report["exception_type"], "FileNotFoundError")
        self.assertIn('File "app/view/pages/home_page.py", line 2, in boom', report["traceback"])
        self.assertNotIn("/opt/DJCat", report["traceback"])

    def testLibraryAndStandardLibraryFramesDropTheirInstallLocation(self):
        self.assertEqual(
            error_report.frameFile(
                "C:\\Users\\student\\DJCat\\Lib\\site-packages\\qfluentwidgets\\common\\icon.py"
            ),
            "qfluentwidgets/common/icon.py",
        )
        self.assertEqual(error_report.frameFile("C:\\Python312\\Lib\\threading.py"), "threading.py")
        self.assertEqual(error_report.frameFile("/usr/lib/python3.12/threading.py"), "threading.py")
        self.assertEqual(error_report.frameFile("<frozen runpy>"), "<frozen runpy>")

    def testTheUserNameNeverLeavesTheMachine(self):
        with (
            patch.object(error_report, "APP_DIR", Path("/opt/DJCat")),
            patch.object(error_report.os.path, "expanduser", return_value="/home/student"),
        ):
            excInfo = _raiseIn(
                "/home/student/scripts/tool.py", "/home/student/Pictures/banner.png"
            )
            report = error_report.buildReport(*excInfo, "a" * 64)

        self.assertEqual(report["message"], "~/Pictures/banner.png")
        self.assertNotIn("student", report["traceback"])

    def testWindowsPathsAreScrubbedHoweverTheyAreSpelled(self):
        message = (
            "[Errno 2] No such file or directory: 'C:\\\\Users\\\\student\\\\a.png'; "
            "Qt: C:/Users/student/b.png; log: C:\\Users\\student\\c.log; "
            "program: 'C:\\\\DJCat\\\\DJCatPro\\\\UserConfig.json'"
        )
        with (
            patch.object(error_report, "APP_DIR", PureWindowsPath("C:/DJCat")),
            patch.object(
                error_report.os.path, "expanduser", return_value="C:\\Users\\student"
            ),
        ):
            scrubbed = error_report._scrubPaths(message)

        self.assertNotIn("student", scrubbed)
        self.assertNotIn("DJCat\\", scrubbed)
        self.assertIn("'~\\\\a.png'", scrubbed)
        self.assertIn("~/b.png", scrubbed)
        self.assertIn("'DJCatPro\\\\UserConfig.json'", scrubbed)

    def testAShorterUserNameDoesNotEatALongerOne(self):
        with patch.object(error_report.os.path, "expanduser", return_value="C:\\Users\\stu"):
            self.assertEqual(
                error_report._scrubPaths("C:\\Users\\student\\a.png"),
                "C:\\Users\\student\\a.png",
            )

    def testDeepTracebacksFitTheServerLimits(self):
        def recurse(depth):
            if depth == 0:
                raise ValueError("deep")
            recurse(depth - 1)

        try:
            recurse(200)
        except ValueError:
            report = error_report.buildReport(*sys.exc_info(), "a" * 64)

        self.assertEqual(len(report["frames"]), error_report.MAX_FRAMES)
        self.assertEqual(report["frames"][-1]["function"], "recurse")
        self.assertLessEqual(len(report["traceback"]), error_report.MAX_TRACEBACK_LENGTH)
        self.assertTrue(report["traceback"].endswith("ValueError: deep"))
        self.assertEqual(error_report.MAX_FRAMES, error_reports.MAX_FRAMES)
        self.assertEqual(
            error_report.MAX_TRACEBACK_LENGTH, error_reports.MAX_TRACEBACK_LENGTH
        )

    def testTheServerGroupsTheSameErrorFromDifferentInstallLocations(self):
        signatures = set()
        for appDir, picture in (
            ("/opt/DJCat", "/opt/DJCat/DJCatPro/banner.png"),
            ("/srv/school/DJCat Pro", "/srv/school/DJCat Pro/DJCatPro/banner.png"),
        ):
            with patch.object(error_report, "APP_DIR", Path(appDir)):
                excInfo = _raiseIn(f"{appDir}/app/view/pages/home_page.py", picture)
                report = error_reports.parseReport(
                    error_report.buildReport(*excInfo, "a" * 64)
                )
            signatures.add(
                error_reports.errorSignature(
                    report["exception_type"], report["message"], report["frames"]
                )
            )

        self.assertEqual(len(signatures), 1)


class ErrorReportSendTest(TestCase):
    def setUp(self):
        error_report._sentKeys.clear()
        self.addCleanup(error_report._sentKeys.clear)
        self.sent = []
        patches = (
            patch.object(error_report, "isPackaged", return_value=True),
            patch.object(error_report, "_send", side_effect=self.sent.append),
            patch("app.common.ai_markdown.machineId", return_value="a" * 64),
            patch.object(
                error_report.threading,
                "Thread",
                side_effect=lambda target, args, **_: type(
                    "Thread", (), {"start": lambda self: target(*args)}
                )(),
            ),
        )
        for active in patches:
            active.start()
            self.addCleanup(active.stop)

    def testOneErrorIsSentOncePerRun(self):
        excInfo = _raiseIn("/opt/DJCat/app/a.py")

        self.assertTrue(error_report.reportError(*excInfo))
        self.assertFalse(error_report.reportError(*excInfo))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]["machine_id"], "a" * 64)

    def testADifferentPlaceIsSentToo(self):
        error_report.reportError(*_raiseIn("/opt/DJCat/app/a.py"))
        error_report.reportError(*_raiseIn("/opt/DJCat/app/b.py"))

        self.assertEqual(len(self.sent), 2)

    def testARunSendsAtMostAFewReports(self):
        for index in range(error_report.MAX_REPORTS_PER_SESSION + 5):
            error_report.reportError(*_raiseIn(f"/opt/DJCat/app/module{index}.py"))

        self.assertEqual(len(self.sent), error_report.MAX_REPORTS_PER_SESSION)

    def testQuittingIsNotAnError(self):
        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            self.assertFalse(error_report.reportError(*sys.exc_info()))
        self.assertEqual(self.sent, [])

    def testSourceRunsAndTestsNeverReport(self):
        with patch.object(error_report, "isPackaged", wraps=lambda: False):
            self.assertFalse(error_report.reportError(*_raiseIn("/opt/DJCat/app/a.py")))
        self.assertEqual(self.sent, [])
        self.assertFalse(
            getattr(sys, "frozen", False) or "__compiled__" in vars(error_report)
        )


class ErrorReportTransportTest(TestCase):
    def testPostsWithoutFollowingRedirects(self):
        with patch.object(error_report.requests, "post") as post:
            post.return_value.status_code = 200
            error_report._send({"exception_type": "ValueError"})

        post.assert_called_once()
        self.assertEqual(post.call_args.args, (error_report.ERROR_REPORT_API,))
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        post.return_value.close.assert_called_once()

    def testNetworkFailuresAreSwallowed(self):
        with patch.object(
            error_report.requests, "post", side_effect=requests.ConnectionError("offline")
        ):
            error_report._send({"exception_type": "ValueError"})
