import json
import os
import stat
import tempfile
import time
import zipfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

from app.common.application_store import (
    ApplicationStore,
    ApplicationStoreError,
    DownloadLimitError,
    DownloadSlots,
    ImageCache,
    UnsafeArchiveError,
    isUpdateAvailable,
    validateZip,
)


class _Response:
    def __init__(self, chunks=(b"image",), url="https://example.test/icon.png"):
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

    def testActionsAndDownloadSlotsAreGuarded(self):
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(self._app(), {"type": "uri", "target": "file:///bad"})
        with self.assertRaises(ApplicationStoreError):
            self.store.executeAction(
                self._app(),
                {"type": "uri", "target": r"C:\\Windows\\System32\\calc.exe"},
            )
        slots = DownloadSlots(3)
        slots.acquire()
        slots.acquire()
        slots.acquire()
        with self.assertRaises(DownloadLimitError):
            slots.acquire()
        slots.release()
        slots.acquire()

    def testDownloadUrlUsesOneUniqueTokenPerTask(self):
        first = parse_qs(urlparse(self.store.downloadUrl(self._app())).query)
        second = parse_qs(urlparse(self.store.downloadUrl(self._app())).query)

        self.assertEqual(first["arch"], [self.store.architecture])
        self.assertRegex(first["token"][0], r"^[a-f0-9]{32}$")
        self.assertNotEqual(first["token"], second["token"])

    def testVersionComparison(self):
        self.assertTrue(isUpdateAvailable("1.0.0", "1.1.0"))
        self.assertFalse(isUpdateAvailable("2.0.0", "1.9.0"))
        self.assertTrue(isUpdateAvailable("1.0.0-rc.1", "1.0.0"))
        self.assertFalse(isUpdateAvailable("1.0.0", "1.0.0-rc.1"))
        self.assertFalse(isUpdateAvailable("1.0", "1.0.0"))
