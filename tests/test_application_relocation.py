import json
import tempfile
import time
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar, MessageBox

from app.common import install_location
from app.common.install_location import MANIFEST_NAME, relocationJournal
from app.config.cfg import cfg
from app.view.components.update_toast import COMPLETED, FAILED
from app.view.windows.application_relocation import ApplicationRelocation
from tests.support import isolateCfg


def _application(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / MANIFEST_NAME).write_text(
        json.dumps({"id": len(name), "name": name.title()}), encoding="utf-8"
    )
    (folder / "app.exe").write_bytes(b"program")
    return folder


class ApplicationRelocationTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "old"
        self.target = self.root / "new"
        self.source.mkdir()
        self.target.mkdir()
        cfg.set(cfg.appInstallLocation, str(self.source), save=False)
        for name, value in (
            ("terminateProcessesUnder", []),
            ("processesUnder", []),
        ):
            patcher = patch.object(install_location, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        save = patch.object(cfg, "save")
        save.start()
        self.addCleanup(save.stop)
        self.addCleanup(install_location.setRelocationState, install_location.IDLE)
        self.window = QWidget()
        self.window.resize(800, 600)
        self.addCleanup(self.window.deleteLater)
        self.busy = Mock(return_value=False)
        self.relocation = ApplicationRelocation(self.window, self.busy)
        self.addCleanup(self.relocation.shutdown)

    def _waitUntilIdle(self, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            QTest.qWait(10)
            if install_location.relocationState() == install_location.IDLE:
                return
        self.fail("应用迁移没有结束")

    def testChangesDirectlyWhenNothingIsInstalled(self):
        with patch.object(InfoBar, "success") as success, patch.object(
            MessageBox, "exec"
        ) as confirm:
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        confirm.assert_not_called()
        success.assert_called_once()
        self.assertEqual(cfg.appInstallLocation.value, str(self.target))
        self.assertEqual(cfg.appRelocation.value, {})

    def testRelocatesInstalledApplicationsAfterConfirmation(self):
        _application(self.source, "alpha")
        _application(self.source, "beta")

        with patch.object(MessageBox, "exec", return_value=1) as confirm:
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        confirm.assert_called_once()
        self.assertEqual(cfg.appInstallLocation.value, str(self.target))
        self.assertEqual(
            sorted(path.name for path in self.target.iterdir()), ["alpha", "beta"]
        )
        self.assertFalse((self.source / "alpha").exists())
        self.assertEqual(cfg.appRelocation.value, {})
        self.assertEqual(self.relocation._toast._state, COMPLETED)

    def testCopiesAcrossVolumesAndRemovesTheOldFolders(self):
        _application(self.source, "alpha")

        with patch.object(
            install_location, "sameVolume", return_value=False
        ), patch.object(MessageBox, "exec", return_value=1):
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        self.assertTrue((self.target / "alpha" / "app.exe").is_file())
        self.assertFalse((self.source / "alpha").exists())
        self.assertEqual(cfg.appInstallLocation.value, str(self.target))

    def testCancelingTheConfirmationKeepsTheLocation(self):
        _application(self.source, "alpha")

        with patch.object(MessageBox, "exec", return_value=0):
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        self.assertEqual(cfg.appInstallLocation.value, str(self.source))
        self.assertTrue((self.source / "alpha").is_dir())
        self.assertEqual(list(self.target.iterdir()), [])

    def testFailedRelocationReportsAndKeepsTheOldLocation(self):
        _application(self.source, "alpha")
        install_location.terminateProcessesUnder.return_value = [
            self.source / "alpha" / "app.exe"
        ]

        with patch.object(MessageBox, "exec", return_value=1):
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        self.assertEqual(cfg.appInstallLocation.value, str(self.source))
        self.assertEqual(cfg.appRelocation.value, {})
        self.assertEqual(self.relocation._toast._state, FAILED)
        self.assertIn("应用仍在原位置", self.relocation._toast.content)

    def testConflictingFoldersStopBeforeAnyQuestion(self):
        _application(self.source, "alpha")
        (self.target / "alpha").mkdir()

        with patch.object(InfoBar, "error") as error, patch.object(
            MessageBox, "exec"
        ) as confirm:
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        confirm.assert_not_called()
        self.assertIn("alpha", error.call_args.args[1])
        self.assertEqual(cfg.appInstallLocation.value, str(self.source))

    def testInsufficientSpaceStopsBeforeClosingApplications(self):
        _application(self.source, "alpha")

        with patch.object(
            install_location, "sameVolume", return_value=False
        ), patch.object(install_location, "freeSpace", return_value=1), patch.object(
            InfoBar, "error"
        ) as error, patch.object(MessageBox, "exec") as confirm:
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        confirm.assert_not_called()
        self.assertIn("空间不足", error.call_args.args[1])
        install_location.terminateProcessesUnder.assert_not_called()

    def testBusyApplicationStoreRefusesToStart(self):
        self.busy.return_value = True

        with patch.object(InfoBar, "warning") as warning:
            self.relocation.request(str(self.target))

        warning.assert_called_once()
        self.assertEqual(install_location.relocationState(), install_location.IDLE)
        self.assertEqual(cfg.appInstallLocation.value, str(self.source))

    def testForbiddenLocationIsRejectedWithItsReason(self):
        with patch.object(InfoBar, "error") as error:
            self.relocation.request(str(self.source / "inner"))

        self.assertIn("当前位置", error.call_args.args[1])
        self.assertEqual(install_location.relocationState(), install_location.IDLE)

    def testDecliningElevationCancelsTheChange(self):
        with patch.object(
            install_location, "isWritable", return_value=False
        ), patch.object(MessageBox, "exec", return_value=0) as confirm:
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        confirm.assert_called_once()
        self.assertEqual(cfg.appInstallLocation.value, str(self.source))

    def testGrantedPermissionContinuesTheChange(self):
        writable = iter([False, True])

        with patch.object(
            install_location, "isWritable", side_effect=lambda _path: next(writable)
        ), patch.object(
            install_location, "grantUsersModify", return_value=True
        ) as grant, patch.object(MessageBox, "exec", return_value=1), patch.object(
            InfoBar, "success"
        ):
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        self.assertEqual(grant.call_args.args[0], self.target)
        self.assertEqual(cfg.appInstallLocation.value, str(self.target))

    def testRejectedUacPromptCancelsSilently(self):
        with patch.object(
            install_location, "isWritable", return_value=False
        ), patch.object(
            install_location, "grantUsersModify", return_value=None
        ), patch.object(MessageBox, "exec", return_value=1), patch.object(
            InfoBar, "error"
        ) as error:
            self.relocation.request(str(self.target))
            self._waitUntilIdle()

        error.assert_not_called()
        self.assertEqual(cfg.appInstallLocation.value, str(self.source))

    def testStartupRecoveryFinishesAnInterruptedRelocation(self):
        _application(self.source, "alpha")
        (self.source / "alpha").rename(self.target / "alpha")
        cfg.set(
            cfg.appRelocation,
            relocationJournal(self.source, self.target, ["alpha"], "token"),
            save=False,
        )

        self.relocation.recoverAtStartup()
        self.assertTrue(install_location.applicationsBlocked())
        self._waitUntilIdle()

        self.assertTrue((self.source / "alpha" / "app.exe").is_file())
        self.assertEqual(cfg.appRelocation.value, {})
        self.assertEqual(cfg.appInstallLocation.value, str(self.source))
