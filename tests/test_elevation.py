import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

from app.common import install_location
from app.platform import elevation, processes
from app.platform.elevation import ElevatedProcess


class StartElevatedTest(TestCase):
    def testOtherPlatformsCannotElevate(self):
        with patch.object(elevation.os, "name", "posix"):
            with self.assertRaises(OSError):
                elevation.startElevated(["app.exe"])


class GrantUsersModifyTest(TestCase):
    def grant(self, **startElevated):
        with (
            # 只替换这个模块看到的 os：改全局的 os.name，pathlib 也会跟着当成 Windows。
            patch.object(
                install_location, "os", SimpleNamespace(name="nt", environ={})
            ),
            patch.object(
                install_location, "startElevated", Mock(**startElevated)
            ) as start,
        ):
            return install_location.grantUsersModify(Path("D:/Apps"), 7), start

    def testRunsIcaclsHiddenAndReportsItsExitCode(self):
        succeeded = Mock()
        succeeded.wait.return_value = 0
        failed = Mock()
        failed.wait.return_value = 5

        granted, start = self.grant(return_value=succeeded)
        refused, _start = self.grant(return_value=failed)

        self.assertIs(granted, True)
        self.assertIs(refused, False)
        args = start.call_args.args[0]
        self.assertEqual(Path(args[0]).name, "icacls.exe")
        self.assertEqual(
            args[1:],
            [str(Path("D:/Apps")), "/grant", "*S-1-5-32-545:(OI)(CI)M", "/Q"],
        )
        self.assertEqual(start.call_args.kwargs, {"window": 7, "hidden": True})

    def testDecliningUacIsToldApartFromFailure(self):
        self.assertIsNone(self.grant(return_value=None)[0])
        self.assertIs(self.grant(side_effect=OSError("拒绝访问。"))[0], False)


@skipUnless(os.name == "nt", "只有 Windows 有进程句柄")
class ElevatedProcessTest(TestCase):
    def testHandleAnswersPollWaitAndKill(self):
        # 管理员进程要弹 UAC，CI 上开不了；用普通进程的同一种句柄检查包装本身。
        child = subprocess.Popen(
            ["ping", "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL
        )
        self.addCleanup(child.wait, 5)
        self.addCleanup(child.kill)
        handle = processes._kernel32().OpenProcess(
            processes.PROCESS_TERMINATE
            | processes.PROCESS_QUERY_LIMITED_INFORMATION
            | processes.SYNCHRONIZE,
            False,
            child.pid,
        )
        self.assertTrue(handle)
        process = ElevatedProcess(handle, ["ping"])

        self.assertEqual(process.pid, child.pid)
        self.assertIsNone(process.poll())
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(0.01)
        process.kill()
        self.assertEqual(process.wait(5), 1)
        self.assertEqual(process.poll(), 1)
        process.kill()
