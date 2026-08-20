import json
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
