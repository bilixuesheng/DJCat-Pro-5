from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.platform import processes


class ProcessesTest(TestCase):
    def testTerminatesEveryProcessUnderTheDirectoryAndReportsSurvivors(self):
        directory = Path("C:/Apps")
        before = [(10, directory / "a.exe"), (11, directory / "sub" / "b.exe")]
        after = [(11, directory / "sub" / "b.exe")]

        with patch.object(
            processes, "processesUnder", side_effect=[before, after]
        ), patch.object(processes, "terminateProcesses") as terminate:
            remaining = processes.terminateProcessesUnder(directory, timeout=1)

        terminate.assert_called_once_with([10, 11], 1)
        self.assertEqual(remaining, [directory / "sub" / "b.exe"])

    def testOtherPlatformsHaveNoProcessesToFind(self):
        with patch.object(processes.os, "name", "posix"):
            self.assertEqual(processes.processesUnder(Path("/apps")), [])
            self.assertEqual(processes.runningExecutables(), [])
            processes.terminateProcesses([1, 2])
