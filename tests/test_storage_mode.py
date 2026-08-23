import json
import runpy
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.config import paths


class StorageModeTest(TestCase):
    def _writeConfig(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        config = directory / "UserConfig.json"
        config.write_text(
            json.dumps(
                {
                    "HomePage": {
                        "PinnedApplicationCards": [
                            {"icon_path": str(directory / "AppStoreCache" / "icon.png")}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )
        return config

    def testPortableDirectoryTakesPrecedenceOnEveryStartup(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            appDirectory = root / "program"
            userDirectory = root / "user" / "DJCatPro"
            portableDirectory = appDirectory / "DJCatPro"
            userConfig = self._writeConfig(userDirectory)
            portableConfig = self._writeConfig(portableDirectory)

            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "executable", str(appDirectory / "DJCat-Pro.exe")),
                patch.object(
                    paths.QStandardPaths,
                    "writableLocation",
                    return_value=str(root / "user"),
                ),
            ):
                for _startup in range(2):
                    loaded = runpy.run_path(paths.__file__)

                    self.assertEqual(loaded["USER_DATA_DIR"], userDirectory)
                    self.assertEqual(loaded["APP_DATA_DIR"], portableDirectory)
                    self.assertEqual(loaded["CONFIG_PATH"], portableConfig)
                    self.assertNotEqual(loaded["CONFIG_PATH"], userConfig)
                    self.assertEqual(
                        loaded["PROGRAM_DIR"], portableDirectory / "Program"
                    )
                    self.assertEqual(
                        loaded["APP_STORE_CACHE_DIR"],
                        portableDirectory / "AppStoreCache",
                    )
                    self.assertEqual(
                        loaded["HOME_CARD_ICON_DIR"],
                        portableDirectory / "HomeCardIcons",
                    )

    def testSwitchToPortableCopiesDataAndRebasesStoredPaths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user" / "DJCatPro"
            target = root / "program" / "DJCatPro"
            config = self._writeConfig(source)
            (source / "Program").mkdir()
            (source / "Program" / "demo.exe").write_bytes(b"demo")

            with (
                patch.object(paths, "APP_DATA_DIR", source),
                patch.object(paths, "PORTABLE_DATA_DIR", target),
                patch.object(paths, "CONFIG_PATH", config),
            ):
                paths.migrateAppData(target)

            migrated = json.loads(
                (target / "UserConfig.json").read_text(encoding="utf-8")
            )
            iconPath = migrated["HomePage"]["PinnedApplicationCards"][0][
                "icon_path"
            ]
            self.assertTrue(iconPath.startswith(str(target)))
            self.assertTrue((target / "Program" / "demo.exe").is_file())
            self.assertTrue(source.is_dir())
            self.assertFalse(target.with_name("DJCatPro.migrating").exists())

    def testMigratedApplicationsRemainAvailableAndManageable(self):
        from app.common.application_store import ApplicationStore, ImageCache

        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user" / "DJCatPro"
            target = root / "program" / "DJCatPro"
            config = self._writeConfig(source)
            installDirectory = source / "Program" / "demo"
            installDirectory.mkdir(parents=True)
            (installDirectory / "app.exe").write_bytes(b"demo")
            manifest = {
                "id": 7,
                "name": "Demo",
                "version": "1.0.0",
                "install_dir": "demo",
                "open_action": {"type": "program", "target": "app.exe"},
                "presets": [],
            }
            (installDirectory / ".djcat-app.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            with (
                patch.object(paths, "APP_DATA_DIR", source),
                patch.object(paths, "PORTABLE_DATA_DIR", target),
                patch.object(paths, "CONFIG_PATH", config),
            ):
                paths.migrateAppData(target)

            store = ApplicationStore(
                programDir=target / "Program",
                cache=ImageCache(target / "AppStoreCache"),
            )
            try:
                installed = store.installed()[7]
                self.assertEqual(installed.path, target / "Program" / "demo")
                catalog = manifest | {
                    "version": "2.0.0",
                    "packages": {store.architecture: {"enabled": True}},
                }
                merged = store.mergeInstalled([catalog])[0]
                self.assertTrue(merged["installed"])
                self.assertTrue(merged["update_available"])

                archivePath = root / "update.zip"
                with zipfile.ZipFile(archivePath, "w") as archive:
                    archive.writestr("app.exe", b"updated")
                installed = store.installZip(catalog, archivePath)
                self.assertEqual(installed.version, "2.0.0")
                self.assertEqual((installed.path / "app.exe").read_bytes(), b"updated")

                with patch("app.common.application_store.subprocess.Popen") as popen:
                    popen.return_value.poll.return_value = 0
                    store.executeAction(installed)

                self.assertEqual(
                    popen.call_args.args[0],
                    [str(target / "Program" / "demo" / "app.exe")],
                )
                self.assertEqual(
                    popen.call_args.kwargs["cwd"], target / "Program" / "demo"
                )

                store.uninstall(installed)
                self.assertNotIn(7, store.installed())
                self.assertEqual(
                    (installDirectory / "app.exe").read_bytes(), b"demo"
                )
            finally:
                store.shutdown()

    def testSwitchToInstalledModeKeepsBackupUntilNewDataExists(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "program" / "DJCatPro"
            target = root / "user" / "DJCatPro"
            config = self._writeConfig(source)

            with (
                patch.object(paths, "APP_DATA_DIR", source),
                patch.object(paths, "PORTABLE_DATA_DIR", source),
                patch.object(paths, "CONFIG_PATH", config),
            ):
                paths.migrateAppData(target)

            self.assertFalse(source.exists())
            self.assertTrue(source.with_name("DJCatPro.bak").is_dir())
            migrated = json.loads(
                (target / "UserConfig.json").read_text(encoding="utf-8")
            )
            iconPath = migrated["HomePage"]["PinnedApplicationCards"][0][
                "icon_path"
            ]
            self.assertTrue(iconPath.startswith(str(target)))

    def testFailedPortableCopyDoesNotChangeActiveMode(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "user" / "DJCatPro"
            target = root / "program" / "DJCatPro"
            config = self._writeConfig(source)

            with (
                patch.object(paths, "APP_DATA_DIR", source),
                patch.object(paths, "PORTABLE_DATA_DIR", target),
                patch.object(paths, "CONFIG_PATH", config),
                patch.object(paths.shutil, "copytree", side_effect=OSError("full")),
                self.assertRaises(OSError),
            ):
                paths.migrateAppData(target)

            self.assertTrue(source.is_dir())
            self.assertFalse(target.exists())
            self.assertFalse(target.with_name("DJCatPro.migrating").exists())
