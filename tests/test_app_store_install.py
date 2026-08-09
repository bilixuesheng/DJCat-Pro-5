import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app.common import app_store
from app.common.app_store import (
    MANIFEST_NAME,
    clearImageCache,
    downloadPackage,
    executeAction,
    extractPackage,
    installPackage,
    installedApplications,
    uninstallApplication,
)
from app.platform import app_maintenance
from app.platform.app_maintenance import performMaintenance, runMaintenanceJob


class AppStoreInstallTest(TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempDir.name)
        self.programDir = self.root / "Program"
        self.tempInstallDir = self.root / "Temp"
        self.application = {
            "id": 7,
            "name": "ClassIsland",
            "developer": "HelloWRC",
            "description": "课表工具",
            "version": "1.0-pre.1",
            "download_url": "https://example.com/classisland.zip",
            "icon_url": "https://example.com/classisland.png",
            "install_dir": "classisland",
            "recommended": True,
            "open_action": {
                "type": "program",
                "target": "ClassIsland.exe",
                "arguments": [],
            },
            "components": [],
        }

    def tearDown(self):
        self.tempDir.cleanup()

    def _archive(self, name, files):
        path = self.root / name
        with zipfile.ZipFile(path, "w") as archive:
            for filename, content in files.items():
                archive.writestr(filename, content)
        return path

    def test_install_accepts_both_zip_layouts_and_update_preserves_extra_files(self):
        nested = self._archive(
            "nested.zip",
            {
                "release/ClassIsland.exe": b"version-1",
                "release/data/default.json": b"default-1",
            },
        )
        installPackage(
            nested,
            self.application,
            programDir=self.programDir,
            tempDir=self.tempInstallDir,
        )
        target = self.programDir / "classisland"
        self.assertEqual((target / "ClassIsland.exe").read_bytes(), b"version-1")
        (target / "user.db").write_bytes(b"keep-me")

        flat = self._archive(
            "flat.zip",
            {
                "ClassIsland.exe": b"version-2",
                "data/default.json": b"default-2",
            },
        )
        updated = {**self.application, "version": "2-beta"}
        installPackage(
            flat,
            updated,
            programDir=self.programDir,
            tempDir=self.tempInstallDir,
        )

        self.assertEqual((target / "ClassIsland.exe").read_bytes(), b"version-2")
        self.assertEqual((target / "data/default.json").read_bytes(), b"default-2")
        self.assertEqual((target / "user.db").read_bytes(), b"keep-me")
        self.assertEqual(
            json.loads((target / MANIFEST_NAME).read_text(encoding="utf-8"))[
                "version"
            ],
            "2-beta",
        )
        self.assertEqual(installedApplications(self.programDir)[0]["id"], 7)

    def test_extract_rejects_paths_outside_the_managed_directory(self):
        archive = self._archive(
            "unsafe.zip",
            {"../outside.exe": b"bad", "App.exe": b"good"},
        )

        with self.assertRaisesRegex(ValueError, "不安全"):
            extractPackage(archive, self.root / "Extracted")

        self.assertFalse((self.root / "outside.exe").exists())

    def test_uninstall_only_removes_the_named_managed_directory(self):
        archive = self._archive("app.zip", {"App.exe": b"app"})
        app = {
            **self.application,
            "install_dir": "managed-app",
            "open_action": {
                "type": "program",
                "target": "App.exe",
                "arguments": [],
            },
        }
        installPackage(
            archive,
            app,
            programDir=self.programDir,
            tempDir=self.tempInstallDir,
        )
        sibling = self.programDir / "keep"
        sibling.mkdir()
        (sibling / "data.txt").write_text("keep", encoding="utf-8")

        uninstallApplication("managed-app", programDir=self.programDir)

        self.assertFalse((self.programDir / "managed-app").exists())
        self.assertEqual((sibling / "data.txt").read_text(encoding="utf-8"), "keep")
        with self.assertRaises(ValueError):
            uninstallApplication("../keep", programDir=self.programDir)

    def test_maintenance_job_is_restricted_to_the_temp_and_program_roots(self):
        self.tempInstallDir.mkdir()
        archive = self._archive("maintenance.zip", {"App.exe": b"app"})
        managedArchive = self.tempInstallDir / "maintenance.zip"
        archive.replace(managedArchive)
        job = self.tempInstallDir / "job.json"
        job.write_text(
            json.dumps(
                {
                    "operation": "install",
                    "archive": str(managedArchive),
                    "application": {
                        **self.application,
                        "install_dir": "maintenance-app",
                        "open_action": {
                            "type": "program",
                            "target": "App.exe",
                            "arguments": [],
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        runMaintenanceJob(
            job,
            programDir=self.programDir,
            tempDir=self.tempInstallDir,
        )

        self.assertTrue((self.programDir / "maintenance-app" / "App.exe").is_file())
        outsideJob = self.root / "outside.json"
        outsideJob.write_text(job.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaises(ValueError):
            runMaintenanceJob(
                outsideJob,
                programDir=self.programDir,
                tempDir=self.tempInstallDir,
            )

    def test_program_and_url_actions_use_only_their_allowlisted_dispatchers(self):
        installDir = self.programDir / "classisland"
        installDir.mkdir(parents=True)
        executable = installDir / "bin" / "ClassIsland.exe"
        executable.parent.mkdir()
        executable.write_bytes(b"MZ")
        with (
            patch.object(app_store, "PROGRAM_DIR", self.programDir),
            patch.object(app_store.QProcess, "startDetached", return_value=True) as start,
        ):
            executeAction(
                self.application,
                {
                    "type": "program",
                    "target": "bin/ClassIsland.exe",
                    "arguments": ["--silent"],
                },
            )
        start.assert_called_once_with(
            str(executable), ["--silent"], str(installDir)
        )

        with patch.object(
            app_store.QDesktopServices, "openUrl", return_value=True
        ) as openUrl:
            executeAction(
                self.application,
                {"type": "url", "target": "https://example.com", "arguments": []},
            )
        self.assertEqual(openUrl.call_args.args[0].toString(), "https://example.com")
        with self.assertRaises(ValueError):
            executeAction(
                self.application,
                {"type": "program", "target": "../outside.exe", "arguments": []},
            )
        with self.assertRaisesRegex(ValueError, "不安全"):
            executeAction(
                self.application,
                {"type": "program", "target": "C:/outside.exe", "arguments": []},
            )

    def test_interrupted_directory_swap_restores_the_previous_install(self):
        backup = self.programDir / ".classisland.backup-deadbeef"
        backup.mkdir(parents=True)
        (backup / "ClassIsland.exe").write_bytes(b"old")
        (backup / ".djcat-app.json").write_text(
            json.dumps(self.application, ensure_ascii=False), encoding="utf-8"
        )
        candidate = self.programDir / ".classisland.installing-deadbeef"
        candidate.mkdir()

        applications = installedApplications(self.programDir)

        self.assertEqual([app["id"] for app in applications], [7])
        self.assertEqual(
            (self.programDir / "classisland" / "ClassIsland.exe").read_bytes(),
            b"old",
        )
        self.assertFalse(backup.exists())
        self.assertFalse(candidate.exists())

    def test_interrupted_uninstall_restores_the_quarantined_directory(self):
        quarantine = self.programDir / ".classisland.removing-deadbeef"
        quarantine.mkdir(parents=True)
        (quarantine / ".djcat-app.json").write_text(
            json.dumps(self.application, ensure_ascii=False), encoding="utf-8"
        )

        applications = installedApplications(self.programDir)

        self.assertEqual([app["id"] for app in applications], [7])
        self.assertTrue((self.programDir / "classisland").is_dir())
        self.assertFalse(quarantine.exists())

    def test_manual_image_cache_clear_reports_deleted_bytes(self):
        cacheDir = self.root / "Cache"
        cacheDir.mkdir()
        (cacheDir / "icon.png").write_bytes(b"1234")
        (cacheDir / "banner.webp").write_bytes(b"123456")

        self.assertEqual(clearImageCache(cacheDir), 10)
        self.assertFalse(cacheDir.exists())

    def test_permission_failure_uses_restricted_elevated_job_and_cleans_it(self):
        self.tempInstallDir.mkdir()
        archive = self.tempInstallDir / "package.zip"
        archive.write_bytes(b"zip")
        with (
            patch.object(app_maintenance, "PROGRAM_DIR", self.programDir),
            patch.object(
                app_maintenance, "installPackage", side_effect=PermissionError
            ),
            patch.object(app_maintenance, "runElevatedJob") as elevated,
        ):
            performMaintenance(
                "install",
                self.application,
                archive,
                programDir=self.programDir,
                tempDir=self.tempInstallDir,
            )

        jobPath = elevated.call_args.args[0]
        self.assertFalse(jobPath.exists())
        self.assertFalse(jobPath.with_suffix(".result.json").exists())

    def test_canceled_elevation_is_reported_without_leaving_a_job(self):
        self.tempInstallDir.mkdir()
        archive = self.tempInstallDir / "package.zip"
        archive.write_bytes(b"zip")
        with (
            patch.object(app_maintenance, "PROGRAM_DIR", self.programDir),
            patch.object(
                app_maintenance, "installPackage", side_effect=PermissionError
            ),
            patch.object(
                app_maintenance,
                "runElevatedJob",
                side_effect=OSError("用户取消了操作"),
            ) as elevated,
        ):
            with self.assertRaisesRegex(OSError, "用户取消"):
                performMaintenance(
                    "install",
                    self.application,
                    archive,
                    programDir=self.programDir,
                    tempDir=self.tempInstallDir,
                )

        jobPath = elevated.call_args.args[0]
        self.assertFalse(jobPath.exists())

    def test_download_streams_a_valid_zip_into_the_managed_temp_directory(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("App.exe", b"MZ")
        content = buffer.getvalue()

        class Response:
            headers = {"Content-Length": str(len(content))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, _size):
                yield content[:5]
                yield content[5:]

        progress = []
        with patch.object(app_store.requests, "get", return_value=Response()):
            path = downloadPackage(
                "https://example.com/app.zip",
                tempDir=self.tempInstallDir,
                progress=lambda downloaded, total: progress.append(
                    (downloaded, total)
                ),
            )

        try:
            self.assertEqual(path.parent, self.tempInstallDir)
            self.assertTrue(zipfile.is_zipfile(path))
            self.assertEqual(progress[-1], (len(content), len(content)))
        finally:
            path.unlink()


if __name__ == "__main__":
    import unittest

    unittest.main()
