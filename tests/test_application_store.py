import base64
from io import BytesIO
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from PIL import Image

from app.common import application_store as applicationStoreModule
from app.common.application_store import (
    ApplicationStore,
    ApplicationStoreError,
    DownloadLimitError,
    DownloadSlots,
    ImageCache,
    UnsafeArchiveError,
    clientArchitecture,
    downloadWorker,
    isUpdateAvailable,
    validateZip,
)


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _Response:
    def __init__(self, chunks=(_PNG,), url="https://example.test/icon.png"):
        self.chunks = chunks
        self.url = url
        self.headers = {}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        yield from self.chunks

    def close(self):
        self.closed = True


class _Session:
    def __init__(self):
        self.calls = 0

    def get(self, url, timeout, stream=False):
        self.calls += 1
        return _Response()


class ApplicationStoreTest(TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempDir.name)
        self.store = ApplicationStore(
            apiBaseUrl="https://api.example.test",
            programDir=self.root / "Program",
            cache=ImageCache(self.root / "cache"),
        )

    def tearDown(self):
        self.store.shutdown()
        self.tempDir.cleanup()

    def _zip(self, name="root/app.exe", content=b"first"):
        path = self.root / f"{len(list(self.root.glob('*.zip')))}.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(name, content)
        return path

    def _app(self):
        return {
            "id": 7,
            "name": "Demo",
            "version": "2.0.0",
            "install_dir": "demo",
            "icon_url": "https://example.test/icon.png",
            "open_action": None,
            "presets": [],
        }

    def testInstallStripsSingleRootAndOverwritesExistingFiles(self):
        installed = self.store.installZip(self._app(), self._zip(content=b"first"))
        self.assertEqual((installed.path / "app.exe").read_bytes(), b"first")
        (installed.path / "obsolete.txt").write_bytes(b"old")
        self.store.installZip(self._app(), self._zip(content=b"updated"))
        self.assertEqual((installed.path / "app.exe").read_bytes(), b"updated")
        self.assertFalse((installed.path / "obsolete.txt").exists())
        self.assertEqual(self.store.installed()[7].version, "2.0.0")

    def testInstallAllowsSpaceInDirectoryName(self):
        app = self._app()
        app["install_dir"] = "Demo App"

        installed = self.store.installZip(app, self._zip())

        self.assertEqual(installed.installDir, "Demo App")
        self.assertEqual(installed.path, self.store.programDir / "Demo App")
        self.assertTrue((installed.path / "app.exe").exists())

    def testUpdateCannotMoveAnInstalledApplicationToAnotherDirectory(self):
        self.store.installZip(self._app(), self._zip())
        changed = self._app() | {"install_dir": "demo-new", "version": "3.0.0"}

        with self.assertRaisesRegex(ApplicationStoreError, "安装目录"):
            self.store.installZip(changed, self._zip(content=b"new"))

        self.assertFalse((self.store.programDir / "demo-new").exists())
        self.assertEqual(self.store.installed()[7].installDir, "demo")

    def testFetchCatalogClosesResponse(self):
        response = Mock()
        response.json.return_value = {"apps": []}
        session = Mock()
        session.get.return_value = response

        self.assertEqual(self.store.fetchCatalog(session), {"apps": []})
        response.close.assert_called_once_with()

    def testFetchCatalogRejectsHttpInIntermediateRedirect(self):
        response = Mock()
        response.url = "https://api.example.test/app-store/catalog"
        response.history = [
            SimpleNamespace(url="http://mirror.example.test/catalog")
        ]
        response.json.return_value = {"apps": []}
        session = Mock()
        session.get.return_value = response

        with self.assertRaisesRegex(ApplicationStoreError, "必须保持 HTTPS"):
            self.store.fetchCatalog(session)

        response.close.assert_called_once_with()

    def testMalformedCatalogItemsAreIgnored(self):
        merged = self.store.mergeInstalled(
            [None, {"id": "bad"}, {"id": 1, "packages": [], "presets": "bad"}]
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], 1)
        self.assertEqual(merged[0]["packages"], {})

        merged = self.store.mergeInstalled(
            [{"id": 2, "packages": {"x86_64": "invalid", "arm64": {}}}]
        )
        self.assertEqual(merged[0]["packages"], {"arm64": {}})
        self.assertEqual(merged[0]["presets"], [])
        self.assertFalse(merged[0]["architecture_supported"])

        merged = self.store.mergeInstalled(
            [
                {
                    "id": 3,
                    "packages": {self.store.architecture: {"enabled": True}},
                }
            ]
        )
        self.assertTrue(merged[0]["architecture_supported"])

    @patch("app.common.application_version.platform.machine", return_value="AMD64")
    def testAmd64SourceRuntimeUsesX8664CatalogPackages(self, _machine):
        self.assertEqual(clientArchitecture(), "x86_64")
        self.store.architecture = clientArchitecture()

        merged = self.store.mergeInstalled(
            [
                {
                    "id": 3,
                    "packages": {
                        "x86_64": {"enabled": True}
                    },
                }
            ]
        )

        self.assertTrue(merged[0]["architecture_supported"])

    def testEnabledPackageDoesNotRequireChecksum(self):
        merged = self.store.mergeInstalled(
            [
                {
                    "id": 3,
                    "packages": {
                        self.store.architecture: {"enabled": True}
                    },
                }
            ]
        )

        self.assertTrue(merged[0]["architecture_supported"])
        self.assertNotIn("download_unavailable_reason", merged[0])

    def testInstallDoesNotReplaceDirectoryOwnedByAnotherApplication(self):
        self.store.installZip(self._app(), self._zip(content=b"first"))
        other = self._app() | {"id": 8, "name": "Other"}

        with self.assertRaisesRegex(ApplicationStoreError, "其他软件"):
            self.store.installZip(other, self._zip(content=b"second"))

        self.assertEqual((self.store.programDir / "demo" / "app.exe").read_bytes(), b"first")
        self.assertEqual(self.store.installed()[7].name, "Demo")

    def testInterruptedUpdateBackupIsRecoveredOnNextStartup(self):
        programDir = self.root / "RecoveryProgram"
        backup = programDir / (".demo.backup-" + "a" * 32)
        backup.mkdir(parents=True)
        (backup / "app.exe").write_bytes(b"old")
        (backup / ".djcat-app.json").write_text(
            json.dumps(
                {
                    "id": 8,
                    "name": "Recovered",
                    "version": "1.0",
                    "install_dir": "demo",
                }
            ),
            encoding="utf-8",
        )

        recoveredStore = ApplicationStore(
            apiBaseUrl="https://api.example.test",
            programDir=programDir,
            cache=ImageCache(self.root / "recovery-cache"),
        )
        self.addCleanup(recoveredStore.shutdown)

        self.assertTrue((programDir / "demo" / "app.exe").is_file())
        self.assertEqual(recoveredStore.installed()[8].name, "Recovered")

    def testMergedCatalogKeepsInstalledOpenActionSeparate(self):
        app = self._app() | {
            "open_action": {"type": "program", "target": "old.exe"}
        }
        self.store.installZip(app, self._zip("old.exe"))
        catalog = app | {
            "open_action": {"type": "program", "target": "new.exe"},
            "packages": {self.store.architecture: {"enabled": True}},
        }

        merged = self.store.mergeInstalled([catalog])[0]

        self.assertEqual(merged["open_action"]["target"], "new.exe")
        self.assertEqual(merged["installed_open_action"]["target"], "old.exe")

    def testManifestRevisionCanUpdateActionsWithoutChangingVersion(self):
        app = self._app() | {
            "manifest_revision": 1,
            "packages": {
                self.store.architecture: {"enabled": True, "sha256": "a" * 64}
            },
        }
        self.store.installZip(app, self._zip())
        catalog = app | {
            "manifest_revision": 2,
            "open_action": {"type": "program", "target": "new.exe"},
        }

        merged = self.store.mergeInstalled([catalog])[0]

        self.assertTrue(merged["update_available"])
        self.assertEqual(merged["installed_manifest_revision"], 1)

    def testInstalledApplicationRemainsVisibleWithoutCatalog(self):
        app = self._app() | {
            "description": "Offline tool",
            "developer": "DJCat",
            "open_action": {"type": "program", "target": "app.exe"},
        }
        self.store.installZip(app, self._zip())

        merged = self.store.mergeInstalled([])

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["id"], app["id"])
        self.assertTrue(merged[0]["installed"])
        self.assertEqual(merged[0]["description"], "Offline tool")
        self.assertEqual(
            merged[0]["installed_open_action"], app["open_action"]
        )

    def testInstalledManifestsAreCachedBetweenCatalogRenders(self):
        self.store.installZip(self._app(), self._zip())
        with patch.object(
            applicationStoreModule.json,
            "loads",
            wraps=json.loads,
        ) as loads:
            self.store.mergeInstalled([])
            self.store.mergeInstalled([])

        loads.assert_called_once()

    def testInstallDirectoryStillRejectsPathSeparators(self):
        archive = self._zip()
        for installDir in (
            "../Demo App",
            "Demo/App",
            "Demo\\App",
            "CON",
            "LPT1.tools",
            "Demo.",
        ):
            with self.subTest(installDir=installDir):
                app = self._app()
                app["install_dir"] = installDir
                with self.assertRaises(ApplicationStoreError):
                    self.store.installZip(app, archive)

    def testInstalledManifestCannotRedirectUninstallToAnotherDirectory(self):
        installed = self.store.installZip(self._app(), self._zip())
        victim = self.store.programDir / "victim"
        victim.mkdir()
        (victim / "keep.txt").write_text("keep", encoding="utf-8")
        manifestPath = installed.path / ".djcat-app.json"
        manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
        manifest["install_dir"] = "victim"
        manifestPath.write_text(json.dumps(manifest), encoding="utf-8")

        local = self.store.installed()[7]
        self.assertEqual(local.installDir, "demo")
        self.store.uninstall(local)

        self.assertTrue((victim / "keep.txt").is_file())
        self.assertFalse(installed.path.exists())

    def testCanceledInstallKeepsExistingVersionAndCleansStaging(self):
        installed = self.store.installZip(
            self._app(),
            self._zip(content=b"existing"),
        )
        cancelEvent = Mock()
        cancelEvent.is_set.side_effect = [False, False, False, True]

        with self.assertRaisesRegex(ApplicationStoreError, "安装已取消"):
            self.store.installZip(
                self._app(),
                self._zip(content=b"replacement"),
                cancelEvent,
            )

        self.assertEqual((installed.path / "app.exe").read_bytes(), b"existing")
        self.assertEqual(list(self.store.programDir.glob(".demo.staging-*")), [])

    def testRejectsTraversalAndSymlinkArchives(self):
        traversal = self._zip("../escape.exe")
        with self.assertRaises(UnsafeArchiveError):
            validateZip(traversal)

        reserved = self._zip("root/CON.txt")
        with self.assertRaises(UnsafeArchiveError):
            validateZip(reserved)

        symlink = self.root / "symlink.zip"
        info = zipfile.ZipInfo("root/link.exe")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(symlink, "w") as archive:
            archive.writestr(info, "target.exe")
        with self.assertRaises(UnsafeArchiveError):
            validateZip(symlink)

    def testCacheReusesImagesAndRemovesUnusedEntries(self):
        session = _Session()
        url = "https://example.test/icon.png"
        first = self.store.imagePath(url, session)
        second = self.store.imagePath(url, session)
        self.assertEqual(first, second)
        self.assertEqual(session.calls, 1)
        old = self.root / "cache" / "old.img"
        old.write_bytes(b"old")
        oldTime = time.time() - (8 * 24 * 60 * 60)
        os.utime(old, (oldTime, oldTime))
        self.store.cache.marker.touch()
        os.utime(self.store.cache.marker, (oldTime, oldTime))
        self.store.cache.sweepIfDue()
        self.assertFalse(old.exists())

    def testCacheNormalizesBmpBasedIcoToPng(self):
        url = "https://example.test/icon.ICO?revision=2"
        icon = Image.new("RGBA", (48, 48), (30, 100, 220, 180))
        ico = BytesIO()
        icon.save(
            ico,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48)],
            bitmap_format="bmp",
        )
        session = _Session()
        session.get = lambda *args, **kwargs: _Response((ico.getvalue(),), url)

        path = self.store.imagePath(url, session)

        self.assertEqual(path.suffix, ".png")
        self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertTrue(self.store.cache._isValidImage(path))
        with Image.open(path) as normalized:
            self.assertEqual(normalized.size, (48, 48))

    def testCacheReleasesUnusedPathLocks(self):
        self.store.imagePath("https://example.test/icon.png", _Session())

        self.assertEqual(len(self.store.cache._pathLocks), 0)

    def testCacheRejectsNonImageResponsesAndRepairsBadEntries(self):
        url = "https://example.test/icon.png"
        path = self.store.cache.pathFor(url)
        path.write_bytes(b"<html>not an image</html>")
        session = _Session()

        repaired = self.store.imagePath(url, session)

        self.assertEqual(repaired, path)
        self.assertEqual(session.calls, 1)
        self.assertTrue(self.store.cache._isValidImage(path))

        path.unlink()
        session.get = lambda *args, **kwargs: _Response((b"not an image",))
        with self.assertRaisesRegex(ApplicationStoreError, "有效图片"):
            self.store.imagePath(url, session)
        self.assertFalse(path.exists())

    def testCacheSizeCountsOnlyClearableFiles(self):
        first = self.root / "cache" / "first.png"
        second = self.root / "cache" / "second.img"
        partial = self.root / "cache" / "downloads" / "demo.zip.part"
        partial.parent.mkdir()
        first.write_bytes(b"123")
        second.write_bytes(b"4567")
        partial.write_bytes(b"x" * 4096)
        self.store.cache.marker.touch()

        self.assertEqual(self.store.cache.size(), 4103)

        self.store.cache.clear()

        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertFalse(partial.exists())

    def testActivePackageOperationPreventsCacheFromDeletingInstaller(self):
        package = self.root / "cache" / "downloads" / "demo.zip"
        package.parent.mkdir(exist_ok=True)
        package.write_bytes(b"package")

        with patch.object(
            applicationStoreModule,
            "appStoreImageCache",
            self.store.cache,
        ):
            applicationStoreModule.beginAppStorePackageOperation()
            try:
                with self.assertRaisesRegex(
                    ApplicationStoreError,
                    "正在下载或安装",
                ):
                    applicationStoreModule.clearAppStoreCache()
                self.assertTrue(package.exists())
            finally:
                applicationStoreModule.endAppStorePackageOperation()

            applicationStoreModule.clearAppStoreCache()

        self.assertFalse(package.exists())

    def testClearDoesNotLetAnInFlightCacheReadRecreateTheImage(self):
        url = "https://example.test/icon.png"
        path = self.store.imagePath(url, _Session())
        validated = threading.Event()
        release = threading.Event()
        results = []
        errors = []
        isValidImage = self.store.cache._isValidImage

        def delayedValidation(candidate):
            result = isValidImage(candidate)
            validated.set()
            release.wait(1)
            return result

        def readCache():
            try:
                results.append(self.store.imagePath(url, _Session()))
            except Exception as error:
                errors.append(error)

        with patch.object(
            self.store.cache,
            "_isValidImage",
            side_effect=delayedValidation,
        ):
            reader = threading.Thread(target=readCache)
            try:
                reader.start()
                self.assertTrue(validated.wait(1))
                self.store.cache.clear()
            finally:
                release.set()
                reader.join(1)

        self.assertFalse(reader.is_alive())
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertFalse(path.exists())

    def testCacheStopsOversizedImageBeforeItIsFullyBuffered(self):
        response = _Response((b"abc", b"def"))
        session = _Session()
        session.get = lambda *args, **kwargs: response

        with (
            patch("app.common.application_store.MAX_IMAGE_BYTES", 4),
            self.assertRaises(ApplicationStoreError),
        ):
            self.store.imagePath("https://example.test/large.png", session)

        self.assertTrue(response.closed)
        self.assertFalse(any((self.root / "cache").glob("*.part")))

    def testCacheRejectsHttpInIntermediateRedirect(self):
        response = _Response()
        response.history = [
            SimpleNamespace(url="http://mirror.example.test/icon.png")
        ]
        session = _Session()
        session.get = lambda *args, **kwargs: response

        with self.assertRaisesRegex(ApplicationStoreError, "必须保持 HTTPS"):
            self.store.imagePath("https://example.test/icon.png", session)

        self.assertTrue(response.closed)

    def testActionsAndDownloadSlotsAreGuarded(self):
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(self._app(), "not an action")
        for target in ("bad?.exe", "CON.exe", "folder./app.exe"):
            with self.subTest(target=target), self.assertRaises(
                ApplicationStoreError
            ):
                self.store.executeAction(
                    self._app(),
                    {"type": "program", "target": target},
                )
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(self._app(), {"type": "uri", "target": "file:///bad"})
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(
                self._app(),
                {"type": "uri", "target": r"C:\\Windows\\System32\\calc.exe"},
            )
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(
                self._app(),
                {"type": "program", "target": "app\x00.exe"},
            )
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(
                self._app(),
                {"type": "url", "target": "https://["},
            )
        slots = DownloadSlots(3)
        slots.acquire()
        slots.acquire()
        slots.acquire()
        with self.assertRaises(DownloadLimitError):
            slots.acquire()
        slots.release()
        slots.acquire()

    @patch("app.common.application_store.subprocess.Popen")
    def testProgramLaunchDoesNotInheritNuitkaBundlePath(self, popen):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        bundleDir = self.root / "djcat.dist"
        systemPath = str(self.root / "system")

        with (
            patch.dict(
                os.environ,
                {
                    "PATH": f"{bundleDir}{os.pathsep}{systemPath}",
                    "QML2_IMPORT_PATH": (
                        f"{bundleDir / 'PySide6' / 'qml'}"
                        f"{os.pathsep}{self.root / 'shared-qml'}"
                    ),
                },
            ),
            patch(
                "app.common.application_store.__compiled__",
                SimpleNamespace(containing_dir=str(bundleDir)),
                create=True,
            ),
        ):
            self.store.executeAction(installed)

        self.assertEqual(popen.call_args.kwargs["env"]["PATH"], systemPath)
        self.assertEqual(
            popen.call_args.kwargs["env"]["QML2_IMPORT_PATH"],
            str(self.root / "shared-qml"),
        )

    @patch("app.common.application_store._activateProcessWindow")
    @patch("app.common.application_store.subprocess.Popen")
    def testNewlyLaunchedApplicationDoesNotLookForWindow(self, popen, activate):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        process = Mock(pid=42)
        process.poll.return_value = None
        popen.return_value = process

        self.assertIs(self.store.executeAction(installed), process)

        popen.assert_called_once()
        activate.assert_not_called()

    @patch("app.common.application_store._activateProcessWindow")
    @patch("app.common.application_store.subprocess.Popen")
    def testOpeningRunningApplicationFocusesItWithoutLaunchingAgain(
        self, popen, activate
    ):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        process = Mock(pid=42)
        process.poll.return_value = None
        popen.return_value = process
        worker = Mock()
        worker.is_alive.return_value = True
        activate.return_value = worker

        first = self.store.executeAction(installed)
        second = self.store.executeAction(installed)

        self.assertIs(first, process)
        self.assertIs(second, process)
        popen.assert_called_once()
        activate.assert_called_once()

    @patch("app.common.application_store._activateProcessWindow")
    @patch("app.common.application_store.subprocess.Popen")
    def testDifferentProgramArgumentsLaunchSeparateProcesses(
        self, popen, activate
    ):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        first = Mock(pid=41)
        first.poll.return_value = None
        second = Mock(pid=42)
        second.poll.return_value = None
        popen.side_effect = [first, second]
        worker = Mock()
        worker.is_alive.return_value = True
        activate.return_value = worker
        settingsAction = {
            "type": "program",
            "target": "app.exe",
            "arguments": {"args": ["--settings"]},
        }

        self.assertIs(self.store.executeAction(installed), first)
        self.assertIs(
            self.store.executeAction(installed, settingsAction),
            second,
        )
        self.assertIs(
            self.store.executeAction(installed, settingsAction),
            second,
        )

        self.assertEqual(popen.call_count, 2)

    @patch("app.common.application_store._activateProcessWindow")
    @patch("app.common.application_store.subprocess.Popen")
    def testShutdownStopsWindowActivation(self, popen, activate):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        process = Mock(pid=42)
        process.poll.return_value = None
        popen.return_value = process
        worker = Mock()
        worker.is_alive.return_value = True
        activate.return_value = worker

        self.store.executeAction(installed)
        self.store.executeAction(installed)
        self.store.shutdown()

        worker.join.assert_called_once()

    @patch("app.common.application_store.threading.Thread")
    def testWindowActivationRejectsInvalidPid(self, thread):
        applicationStoreModule._activateProcessWindow(Mock())

        thread.assert_not_called()

    def testWindowActivationReportsAnEarlyNonzeroExit(self):
        if os.name != "nt":
            self.skipTest("Windows window activation only")
        process = Mock(
            pid=999999,
            args=[r"C:\missing\djcat-activation-test-6f2500.exe"],
        )
        process.poll.return_value = 1
        messages = []

        worker = applicationStoreModule._activateProcessWindow(
            process,
            onFailure=messages.append,
        )
        worker.join(3)

        self.assertFalse(worker.is_alive())
        self.assertEqual(
            messages,
            ["程序启动后立即退出，可能已有实例正在运行"],
        )

    @patch("app.common.application_store._activateProcessWindow")
    def testFinishedActivationWorkersAreReclaimed(self, activate):
        firstWorker = Mock()
        firstWorker.is_alive.return_value = False
        secondWorker = Mock()
        secondWorker.is_alive.return_value = False
        activate.side_effect = [firstWorker, secondWorker]

        self.store._activateProcess(Mock(pid=41))
        self.store._activateProcess(Mock(pid=42))

        self.assertEqual(set(self.store._activationThreads), {42})

    @patch("app.common.application_store.subprocess.Popen")
    def testRunningApplicationMustExitBeforeUninstall(self, popen):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        popen.return_value.poll.return_value = None
        self.store.executeAction(installed)

        with (
            patch("app.common.application_store.shutil.rmtree") as rmtree,
            self.assertRaisesRegex(ApplicationStoreError, "仍在运行"),
        ):
            self.store.uninstall(installed)

        rmtree.assert_not_called()

    def testExternallyStartedApplicationBlocksUpdateAndUninstall(self):
        installed = self.store.installZip(self._app(), self._zip())
        executable = installed.path / "app.exe"

        with patch(
            "app.common.application_store._runningExecutablesUnder",
            return_value=[executable],
        ):
            with self.assertRaisesRegex(ApplicationStoreError, "仍在运行"):
                self.store.uninstall(installed)
            with self.assertRaisesRegex(ApplicationStoreError, "仍在运行"):
                self.store.installZip(
                    self._app() | {"version": "3.0.0"},
                    self._zip(content=b"new"),
                )

        self.assertEqual((installed.path / "app.exe").read_bytes(), b"first")

    @patch("app.common.application_store._activateProcessWindow", return_value=None)
    @patch("app.common.application_store.subprocess.Popen")
    def testProgramLaunchWaitsForInstallationOperation(self, popen, _activate):
        app = self._app() | {
            "open_action": {"type": "program", "target": "app.exe"}
        }
        installed = self.store.installZip(app, self._zip())
        popen.return_value.pid = 42
        popen.return_value.poll.return_value = None

        self.store._installedLock.acquire()
        worker = threading.Thread(target=self.store.executeAction, args=(installed,))
        try:
            worker.start()
            time.sleep(0.05)
            popen.assert_not_called()
        finally:
            self.store._installedLock.release()
            worker.join(1)

        self.assertFalse(worker.is_alive())
        popen.assert_called_once()

    @patch("app.common.application_store.subprocess.Popen")
    def testExitedApplicationProcessIsReleasedBeforeNextLaunch(self, popen):
        app = self._app()
        app["open_action"] = {"type": "program", "target": "app.exe"}
        installed = self.store.installZip(app, self._zip())
        first = Mock()
        first.poll.return_value = 0
        second = Mock()
        popen.side_effect = [first, second]

        self.store.executeAction(installed)
        self.store.executeAction(installed)

        tracked = [
            process
            for processes in self.store._launchedProcesses.values()
            for process in processes
        ]
        self.assertEqual(tracked, [second])

    def testLockedUninstallUsesUserFacingError(self):
        installed = self.store.installZip(self._app(), self._zip())

        with (
            patch.object(
                Path,
                "replace",
                side_effect=PermissionError(5, "Access denied"),
            ),
            self.assertRaisesRegex(ApplicationStoreError, "完全退出"),
        ):
            self.store.uninstall(installed)

    def testUninstallRemovesLegacyDuplicateDirectoriesForTheSameApplication(self):
        installed = self.store.installZip(self._app(), self._zip())
        duplicate = self.store.programDir / "demo-old"
        shutil.copytree(installed.path, duplicate)
        manifestPath = duplicate / ".djcat-app.json"
        manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
        manifest["version"] = "1.0.0"
        manifestPath.write_text(json.dumps(manifest), encoding="utf-8")

        current = self.store.installed()[7]
        self.store.uninstall(current)

        self.assertFalse(installed.path.exists())
        self.assertFalse(duplicate.exists())
        self.assertNotIn(7, self.store.installed())

    def testDownloadUrlUsesOneUniqueTokenPerTask(self):
        first = parse_qs(urlparse(self.store.downloadUrl(self._app())).query)
        second = parse_qs(urlparse(self.store.downloadUrl(self._app())).query)

        self.assertEqual(first["arch"], [self.store.architecture])
        self.assertRegex(first["token"][0], r"^[a-f0-9]{32}$")
        self.assertNotEqual(first["token"], second["token"])

    def testPackageDownloadUsesOptionalCatalogSha256(self):
        app = self._app() | {
            "packages": {
                self.store.architecture: {
                    "enabled": True,
                    "sha256": "a" * 64,
                }
            }
        }

        worker = downloadWorker(app, self.store)

        self.assertEqual(worker._expectedSha256, "a" * 64)
        worker = downloadWorker(
            self._app()
            | {
                "packages": {self.store.architecture: {"enabled": True}}
            },
            self.store,
        )
        self.assertIsNone(worker._expectedSha256)

    def testVersionComparison(self):
        self.assertTrue(isUpdateAvailable("1.0.0", "1.1.0"))
        self.assertFalse(isUpdateAvailable("2.0.0", "1.9.0"))
        self.assertTrue(isUpdateAvailable("1.0.0-rc.1", "1.0.0"))
        self.assertFalse(isUpdateAvailable("1.0.0", "1.0.0-rc.1"))
        self.assertFalse(isUpdateAvailable("1.0", "1.0.0"))
