import json
import os
import tempfile
import threading
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.common import install_location
from app.common.install_location import (
    MANIFEST_NAME,
    RelocationError,
    applicationFolders,
    commitInstallLocation,
    conflictingNames,
    installLocation,
    installLocationAvailable,
    isDefaultInstallLocation,
    recoverRelocation,
    relocate,
    relocationJournal,
    removeOldFolders,
    runningApplications,
    targetProblem,
)
from app.config.cfg import cfg
from app.config.paths import APP_DATA_DIR, APP_DIR, PROGRAM_DIR
from app.platform.processes import Survivor
from tests.support import isolateCfg


def _application(root: Path, name: str, title: str, files=None) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / MANIFEST_NAME).write_text(
        json.dumps({"id": len(name), "name": title}), encoding="utf-8"
    )
    for relative, content in (files or {"app.exe": b"program"}).items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return folder


class InstallLocationTest(TestCase):
    def setUp(self):
        isolateCfg(self)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "old"
        self.target = self.root / "new"
        self.source.mkdir()
        self.target.mkdir()
        terminate = patch.object(
            install_location, "terminateProcessesUnder", return_value=[]
        )
        self.terminate = terminate.start()
        self.addCleanup(terminate.stop)

    def _relocateAcrossVolumes(self, names, **kwargs):
        with patch.object(install_location, "sameVolume", return_value=False):
            relocate(self.source, self.target, names, "token", **kwargs)

    def testDefaultLocationFollowsTheAppDataDirectory(self):
        self.assertTrue(isDefaultInstallLocation())
        self.assertEqual(installLocation(), PROGRAM_DIR)
        self.assertTrue(installLocationAvailable())

        cfg.set(cfg.appInstallLocation, str(self.root / "missing"), save=False)

        self.assertFalse(isDefaultInstallLocation())
        self.assertEqual(installLocation(), self.root / "missing")
        self.assertFalse(installLocationAvailable())

    def testRejectsLocationsThatWouldLoseApplications(self):
        current = self.source
        rejected = {
            Path(self.root.anchor): "根目录",
            APP_DIR / "Apps": "程序目录或数据目录",
            APP_DATA_DIR / "Apps": "程序目录或数据目录",
            current / "inner": "当前位置",
            self.root: "当前位置",
            current: "当前位置",
        }
        for target, reason in rejected.items():
            with self.subTest(target=target):
                self.assertIn(reason, targetProblem(target, current))
        self.assertIsNone(targetProblem(self.target, current))

    def testListsRecognizedApplicationsAndConflicts(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        (self.source / "loose").mkdir()
        (self.source / ".alpha.backup-0").mkdir()
        (self.target / "beta").mkdir()

        folders = applicationFolders(self.source)

        self.assertEqual([folder.name for folder in folders], ["alpha", "beta"])
        self.assertEqual(conflictingNames(folders, self.target), ["beta"])

    def testRunningApplicationsAreNamedByTheirFolder(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        folders = applicationFolders(self.source)
        root = self.source.resolve()
        processes = [
            (1, root / "beta" / "bin" / "beta.exe"),
            (2, root / "alpha" / "app.exe"),
            (3, root / "beta" / "helper.exe"),
            (4, root / "stray.exe"),
        ]

        with patch.object(install_location, "processesUnder", return_value=processes):
            self.assertEqual(
                runningApplications(self.source, folders), ["Beta", "Alpha"]
            )

    def testSameVolumeRelocationRenamesEveryFolder(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")

        relocate(self.source, self.target, ["alpha", "beta"], "token")

        self.terminate.assert_called_once_with(self.source)
        self.assertEqual(
            sorted(path.name for path in self.target.iterdir()), ["alpha", "beta"]
        )
        self.assertEqual(list(self.source.iterdir()), [])

    def testFailedSameVolumeRelocationMovesFoldersBack(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        original = Path.rename

        def rename(path, destination):
            if path.name == "beta":
                raise PermissionError(5, "Access denied", str(path))
            return original(path, destination)

        with (
            patch.object(Path, "rename", rename),
            self.assertRaisesRegex(RelocationError, "占用") as raised,
        ):
            relocate(self.source, self.target, ["alpha", "beta"], "token")

        self.assertTrue(raised.exception.clean)
        self.assertTrue((self.source / "alpha" / "app.exe").is_file())
        self.assertEqual(list(self.target.iterdir()), [])

    def testCrossVolumeRelocationCopiesWithProgress(self):
        _application(
            self.source, "alpha", "Alpha", {"a.bin": b"a" * 10, "sub/b.bin": b"b" * 5}
        )
        total = install_location.folderSize(self.source / "alpha")
        reports = []

        self._relocateAcrossVolumes(
            ["alpha"],
            totalBytes=total,
            progress=lambda done, total: reports.append((done, total)),
        )

        self.assertEqual(reports[-1], (total, total))
        self.assertEqual((self.target / "alpha" / "sub" / "b.bin").read_bytes(), b"b" * 5)
        self.assertTrue((self.target / "alpha" / MANIFEST_NAME).is_file())
        # 旧文件提交之后才删。
        self.assertTrue((self.source / "alpha" / "a.bin").is_file())
        self.assertEqual(
            sorted(path.name for path in self.target.iterdir()), ["alpha"]
        )

    def testFailedCrossVolumeCopyLeavesNothingBehind(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        original = install_location._Copier.copyFile

        def copyFile(copier, source, target):
            if source.parent.name == "beta":
                raise OSError(28, "No space left on device", str(target))
            return original(copier, source, target)

        with (
            patch.object(install_location._Copier, "copyFile", copyFile),
            self.assertRaisesRegex(RelocationError, "空间不足") as raised,
        ):
            self._relocateAcrossVolumes(["alpha", "beta"])

        self.assertTrue(raised.exception.clean)
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertTrue((self.source / "beta" / "app.exe").is_file())

    def testCanceledCopyIsRolledBack(self):
        _application(self.source, "alpha", "Alpha")
        canceled = threading.Event()
        canceled.set()

        with self.assertRaisesRegex(RelocationError, "中断"):
            self._relocateAcrossVolumes(["alpha"], cancelEvent=canceled)

        self.assertEqual(list(self.target.iterdir()), [])

    def testApplicationThatCannotBeClosedStopsRelocation(self):
        _application(self.source, "alpha", "Alpha")
        self.terminate.return_value = [
            Survivor(self.source / "alpha" / "app.exe", False)
        ]

        with self.assertRaisesRegex(RelocationError, "无法关闭：app.exe。请手动退出"):
            relocate(self.source, self.target, ["alpha"], "token")

        self.assertTrue((self.source / "alpha").is_dir())
        self.assertEqual(list(self.target.iterdir()), [])

    def testOldFoldersAreOnlyRemovedWhenTheNewCopyExists(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        _application(self.target, "alpha", "Alpha")

        self.assertEqual(removeOldFolders(self.source, self.target, ["alpha", "beta"]), [])

        self.assertFalse((self.source / "alpha").exists())
        self.assertTrue((self.source / "beta").exists())

    def testRecoveryUndoesAnInterruptedSameVolumeRelocation(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        (self.source / "alpha").rename(self.target / "alpha")
        journal = relocationJournal(self.source, self.target, ["alpha", "beta"], "token")
        cfg.set(cfg.appInstallLocation, str(self.source), save=False)

        self.assertTrue(recoverRelocation(journal))

        self.assertTrue((self.source / "alpha" / "app.exe").is_file())
        self.assertTrue((self.source / "beta" / "app.exe").is_file())
        self.assertEqual(list(self.target.iterdir()), [])

    def testRecoveryRemovesAnUncommittedCopy(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.source, "beta", "Beta")
        _application(self.target, "alpha", "Alpha")
        (self.target / ".beta.relocating-token").mkdir()
        (self.target / "other").mkdir()
        journal = relocationJournal(self.source, self.target, ["alpha", "beta"], "token")
        cfg.set(cfg.appInstallLocation, str(self.source), save=False)

        self.assertTrue(recoverRelocation(journal))

        self.assertEqual(
            sorted(path.name for path in self.target.iterdir()), ["other"]
        )
        self.assertTrue((self.source / "alpha").is_dir())

    def testRecoveryFinishesACommittedRelocation(self):
        _application(self.source, "alpha", "Alpha")
        _application(self.target, "alpha", "Alpha")
        journal = relocationJournal(self.source, self.target, ["alpha"], "token")
        cfg.set(cfg.appInstallLocation, str(self.target), save=False)

        self.assertTrue(recoverRelocation(journal))

        self.assertFalse((self.source / "alpha").exists())
        self.assertTrue((self.target / "alpha").is_dir())

    def testRecoveryWaitsForAnUnavailableOldLocation(self):
        missing = self.root / "unplugged"
        _application(self.target, "alpha", "Alpha")
        journal = relocationJournal(missing, self.target, ["alpha"], "token")
        cfg.set(cfg.appInstallLocation, str(missing), save=False)

        self.assertFalse(recoverRelocation(journal))
        self.assertTrue((self.target / "alpha").is_dir())

    def testInvalidJournalIsDiscarded(self):
        self.assertTrue(recoverRelocation({"source": "x", "folders": ["../a"]}))
        self.assertTrue(
            recoverRelocation(
                relocationJournal(self.source, self.target, ["..\\a"], "token")
            )
        )

    def testCommitRewritesPathsUnderTheOldLocationOnce(self):
        cfg.set(cfg.appInstallLocation, str(self.source), save=False)
        cfg.set(
            cfg.customHomeCards,
            [
                {
                    "actions": [
                        {"target": str(self.source / "alpha" / "app.exe")},
                        {"target": str(self.root / "elsewhere.exe")},
                    ]
                }
            ],
            save=False,
        )
        journal = relocationJournal(self.source, self.target, ["alpha"], "token")
        cfg.set(cfg.appRelocation, journal, save=False)

        with patch.object(cfg, "save") as save:
            commitInstallLocation(self.target, rebase=True)

        save.assert_called_once()
        self.assertEqual(cfg.appInstallLocation.value, str(self.target))
        targets = [action["target"] for action in cfg.customHomeCards.value[0]["actions"]]
        self.assertEqual(
            targets,
            [str(self.target / "alpha" / "app.exe"), str(self.root / "elsewhere.exe")],
        )
        self.assertEqual(cfg.appRelocation.value, journal)

    def testResetStoresTheDefaultAsAnEmptyValue(self):
        cfg.set(cfg.appInstallLocation, str(self.source), save=False)
        cfg.set(cfg.customHomeCards, [{"target": str(self.source / "a.exe")}], save=False)

        with patch.object(cfg, "save"):
            commitInstallLocation(None, rebase=False)

        self.assertEqual(cfg.appInstallLocation.value, "")
        self.assertTrue(isDefaultInstallLocation())
        self.assertEqual(
            cfg.customHomeCards.value, [{"target": str(self.source / "a.exe")}]
        )

    def testWritableCheckLeavesNoProbeBehind(self):
        self.assertTrue(install_location.isWritable(self.target))
        self.assertEqual(list(self.target.iterdir()), [])
        self.assertTrue(install_location.isWritable(self.target / "created"))
        self.assertTrue((self.target / "created").is_dir())
        if os.name != "nt" and os.geteuid() != 0:
            self.target.chmod(0o500)
            self.addCleanup(self.target.chmod, 0o700)
            self.assertFalse(install_location.isWritable(self.target))
