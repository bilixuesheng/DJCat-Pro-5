import io
import json
import re
import sqlite3
import tarfile
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from server import ai_markdown, server_update
from tests import test_ai_admin

REPO = "bilixuesheng/DJCat-Pro-5"
OLD_COMMIT = "a" * 40
NEW_COMMIT = "c" * 40


def versionFile(version, commit):
    return f'SERVER_VERSION = "{version}"\nSERVER_COMMIT = "{commit}"\n'


class FakeGitHub:
    """A tiny GitHub: server packages published onto main in order, or only onto a fork."""

    API = f"https://api.github.com/repos/{REPO}"

    def __init__(self):
        self.packages = {}
        self.tarballs = {}
        self.histories = {}
        self.main = []
        # 提交 → 它之前最近一个改过 server/ 的提交；没写的就当它自己改过。
        self.newestServerCommit = {}
        self.requested = []
        self.offline = False

    def publish(self, commit, files, history=(), onMain=True, extraMembers=()):
        self.packages[commit] = files
        self.tarballs[commit] = tarball(commit, files, extraMembers)
        self.histories[commit] = list(history)
        if onMain:
            self.main.append(commit)

    def fetch(self, url, accept=None):
        self.requested.append(url)
        if self.offline:
            raise server_update.ServerUpdateError("下载", "连不上 GitHub")
        routes = (
            (rf"{self.API}/commits/main", lambda: self.main[-1].encode()),
            (
                rf"{self.API}/contents/server/version\.py\?ref=(\w+)",
                lambda sha: self.packages[sha]["version.py"].encode(),
            ),
            (
                rf"{self.API}/commits\?sha=(\w+)&path=server&per_page=100",
                lambda sha: json.dumps(self.histories[sha]).encode(),
            ),
            (
                rf"{self.API}/commits\?sha=(\w+)&path=server&per_page=1",
                lambda sha: json.dumps(
                    [{"sha": self.newestServerCommit.get(sha, sha)}]
                ).encode(),
            ),
            (rf"{self.API}/compare/main\.\.\.(\w+)", self._compare),
            (rf"https://codeload\.github\.com/{REPO}/tar\.gz/(\w+)", self.tarballs.__getitem__),
        )
        for pattern, respond in routes:
            match = re.fullmatch(pattern, url)
            if match:
                try:
                    return respond(*match.groups())
                except KeyError:
                    break
        raise server_update.ServerUpdateError("下载", f"404 {url}")

    def _compare(self, sha):
        if sha == self.main[-1]:
            status = "identical"
        elif sha in self.main:
            status = "behind"
        else:
            status = "diverged"
        return json.dumps({"status": status}).encode()


def tarball(commit, files, extraMembers=()):
    buffer = io.BytesIO()
    root = f"bilixuesheng-DJCat-Pro-5-{commit[:7]}"
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in {"README.md": "repo readme"}.items():
            addFile(archive, f"{root}/{name}", text)
        for name, text in files.items():
            addFile(archive, f"{root}/server/{name}", text)
        for member, data in extraMembers:
            archive.addfile(member, io.BytesIO(data) if data is not None else None)
    return buffer.getvalue()


def addFile(archive, name, text):
    data = text.encode()
    member = tarfile.TarInfo(name)
    member.size = len(data)
    archive.addfile(member, io.BytesIO(data))


def historyEntry(commit, title, parents=1):
    return {
        "sha": commit,
        "commit": {"message": f"{title}\n\n正文"},
        "parents": [{"sha": "0" * 40}] * parents,
    }


class ServerUpdateTest(TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempDir.cleanup)
        self.projectDir = Path(self.tempDir.name) / "djcat-ai"
        self.databasePath = self.projectDir / "data" / "usage.sqlite3"
        self.installed = {
            "version.py": versionFile("1.4.8", OLD_COMMIT),
            "ai_markdown.py": "VALUE = 'old'\n",
            "app_store.py": "OLD = True\n",
            "requirements.txt": "Flask>=3.1,<4\ngunicorn>=23,<24\n",
            "templates/admin_base.html": "old base",
        }
        for name, text in self.installed.items():
            self.write(name, text)
        self.protected = {
            ".venv/bin/python": "venv",
            "gunicorn_conf.py": "bind = '0.0.0.0:18080'",
            "uwsgi.ini": "[uwsgi]",
            "server.zip": "old upload",
            "__pycache__/ai_markdown.cpython-312.pyc": "bytecode",
        }
        for name, text in self.protected.items():
            self.write(name, text)
        self.databasePath.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.databasePath)) as database:
            database.execute("CREATE TABLE usage (machine TEXT)")
            database.execute("INSERT INTO usage VALUES ('DJ-000001')")
            database.commit()
        self.github = FakeGitHub()
        self.pipRuns = []
        self.updater = server_update.ServerUpdater(
            self.projectDir,
            lambda: self.databasePath,
            fetch=self.github.fetch,
            runPip=lambda requirements: self.pipRuns.append(
                requirements.read_text(encoding="utf-8")
            ),
        )

    def write(self, name, text):
        path = self.projectDir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, name):
        return (self.projectDir / name).read_text(encoding="utf-8")

    def release(self, version, changes=None, commit=NEW_COMMIT, history=(), **options):
        files = dict(self.installed)
        files["version.py"] = versionFile(version, commit)
        for name, text in (changes or {}).items():
            if text is None:
                files.pop(name, None)
            else:
                files[name] = text
        self.github.publish(commit, files, history, **options)
        return commit

    def testCheckOffersHigherVersionWithServerCommitTitlesSinceInstalled(self):
        self.release(
            "1.4.9",
            history=[
                historyEntry(NEW_COMMIT, "fix: 字体按 font/woff2 返回"),
                historyEntry("d" * 40, "Merge pull request #38", parents=2),
                historyEntry("b" * 40, "feat: 后台一键更新服务端"),
                historyEntry(OLD_COMMIT, "已安装的提交"),
                historyEntry("e" * 40, "更早的提交"),
            ],
        )

        check = self.updater.check()

        self.assertEqual(check.version, "1.4.9")
        self.assertEqual(check.commit, NEW_COMMIT)
        self.assertEqual(
            check.titles,
            ["fix: 字体按 font/woff2 返回", "feat: 后台一键更新服务端"],
        )

    def testCommitTitlesStopAtTheInstalledServerCodeEvenWhenTheInstalledCommitIsClientOnly(self):
        self.github.newestServerCommit[OLD_COMMIT] = "e" * 40
        self.release(
            "1.4.9",
            history=[
                historyEntry(NEW_COMMIT, "fix: 字体按 font/woff2 返回"),
                historyEntry("b" * 40, "feat: 后台一键更新服务端"),
                historyEntry("e" * 40, "已安装的服务端代码"),
                historyEntry("d" * 40, "更早的提交"),
            ],
        )

        self.assertEqual(
            self.updater.check().titles,
            ["fix: 字体按 font/woff2 返回", "feat: 后台一键更新服务端"],
        )

    def testCheckOffersNothingWhenMainIsNotHigher(self):
        for version in ("1.4.8", "1.4.7", "0.9.10"):
            with self.subTest(version=version):
                self.release(version)
                self.assertIsNone(self.updater.check())

    def testCheckComparesVersionsNumerically(self):
        self.release("1.4.10")
        self.assertEqual(self.updater.check().version, "1.4.10")

    def usageRows(self):
        with closing(sqlite3.connect(self.databasePath)) as database:
            return database.execute("SELECT machine FROM usage").fetchall()

    def testApplyReplacesPackageFilesAndNeverTouchesProtectedOnes(self):
        self.release(
            "1.4.9",
            {
                "ai_markdown.py": "VALUE = 'new'\n",
                "static/admin.css": "body {}",
                "data/usage.sqlite3": "from the package",
                "gunicorn_conf.py": "from the package",
            },
        )

        result = self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual((result.version, result.commit), ("1.4.9", NEW_COMMIT))
        self.assertEqual(self.updater.installedVersion(), ("1.4.9", NEW_COMMIT))
        self.assertEqual(self.read("ai_markdown.py"), "VALUE = 'new'\n")
        self.assertEqual(self.read("static/admin.css"), "body {}")
        for name, text in self.protected.items():
            self.assertEqual(self.read(name), text, name)
        self.assertEqual(self.usageRows(), [("DJ-000001",)])

    def testApplyRejectsUnsafeArchiveEntriesWithoutWritingAnything(self):
        root = f"bilixuesheng-DJCat-Pro-5-{NEW_COMMIT[:7]}"
        escape = tarfile.TarInfo(f"{root}/server/../../escaped.py")
        escape.size = 4
        link = tarfile.TarInfo(f"{root}/server/static/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        for member, data in ((escape, b"evil"), (link, None)):
            with self.subTest(member=member.name):
                self.release(
                    "1.4.9",
                    {"ai_markdown.py": "VALUE = 'new'\n"},
                    extraMembers=[(member, data)],
                )

                with self.assertRaises(server_update.ServerUpdateError) as raised:
                    self.updater.apply("1.4.9", NEW_COMMIT)

                self.assertEqual(raised.exception.step, "下载")
                self.assertEqual(self.read("ai_markdown.py"), "VALUE = 'old'\n")
                self.assertFalse((Path(self.tempDir.name) / "escaped.py").exists())

    def testApplyReportsTheVersionFileItInstalled(self):
        unfilled = 'SERVER_VERSION = "1.4.9"\nSERVER_COMMIT = "$Format:%H$"\n'
        self.release("1.4.9", {"version.py": unfilled})

        result = self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual((result.version, result.commit), ("1.4.9", ""))

    def testFilesDroppedFromThePackageAreRemovedOnlyOnceTheyWereInstalledByAnUpdate(self):
        self.write("templates/hand_added.html", "not from any package")
        self.release("1.4.9", {"templates/admin_old.html": "shipped in 1.4.9"})
        self.updater.apply("1.4.9", NEW_COMMIT)

        self.release(
            "1.5.0",
            {"templates/admin_old.html": None, "app_store.py": None},
            commit="f" * 40,
        )
        self.updater.apply("1.5.0", "f" * 40)

        self.assertFalse((self.projectDir / "templates/admin_old.html").exists())
        self.assertFalse((self.projectDir / "app_store.py").exists())
        self.assertEqual(self.read("templates/hand_added.html"), "not from any package")

    def testFirstUpdateRemovesNothing(self):
        self.release("1.4.9", {"app_store.py": None})
        self.updater.apply("1.4.9", NEW_COMMIT)
        self.assertEqual(self.read("app_store.py"), "OLD = True\n")

    def testNewCodeThatFailsToImportIsNeverInstalled(self):
        self.release(
            "1.4.9",
            {
                "ai_markdown.py": "raise RuntimeError('新代码坏了')\n",
                "app_store.py": "NEW = True\n",
            },
        )

        with self.assertRaises(server_update.ServerUpdateError) as raised:
            self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual(raised.exception.step, "试导入")
        self.assertIn("新代码坏了", raised.exception.detail)
        for name, text in self.installed.items():
            self.assertEqual(self.read(name), text, name)

    def testTrialImportRunsAgainstACopyOfTheDatabase(self):
        self.release(
            "1.4.9",
            {
                "ai_markdown.py": (
                    "import os, sqlite3\n"
                    "database = sqlite3.connect(os.environ['DJCATAI_DATABASE_PATH'])\n"
                    "assert database.execute('SELECT COUNT(*) FROM usage').fetchone() == (1,)\n"
                    "database.execute('ALTER TABLE usage ADD COLUMN migrated TEXT')\n"
                    "database.execute(\"INSERT INTO usage VALUES ('DJ-999999', 'x')\")\n"
                    "database.commit()\n"
                ),
            },
        )

        self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual(self.usageRows(), [("DJ-000001",)])

    def testUnchangedRequirementsSkipPip(self):
        self.release("1.4.9")
        result = self.updater.apply("1.4.9", NEW_COMMIT)
        self.assertEqual(self.pipRuns, [])
        self.assertFalse(result.gunicornChanged)

    def testChangedRequirementsAreInstalledBeforeTheCodeIsReplaced(self):
        requirements = "Flask>=3.1,<4\ngunicorn>=23,<24\nrequests>=2.32,<3\n"
        self.release("1.4.9", {"requirements.txt": requirements})

        result = self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual(self.pipRuns, [requirements])
        self.assertEqual(self.read("requirements.txt"), requirements)
        self.assertFalse(result.gunicornChanged)

    def testGunicornRequirementChangeAsksForAPanelRestart(self):
        self.release("1.4.9", {"requirements.txt": "Flask>=3.1,<4\ngunicorn>=24,<25\n"})
        self.assertTrue(self.updater.apply("1.4.9", NEW_COMMIT).gunicornChanged)

    def testFailedDependencyInstallLeavesTheOldCode(self):
        def failingPip(requirements):
            raise server_update.ServerUpdateError("依赖", "No matching distribution")

        self.updater.runPip = failingPip
        self.release(
            "1.4.9",
            {"requirements.txt": "Flask>=9\n", "ai_markdown.py": "VALUE = 'new'\n"},
        )

        with self.assertRaises(server_update.ServerUpdateError) as raised:
            self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual(raised.exception.step, "依赖")
        self.assertEqual(self.read("ai_markdown.py"), "VALUE = 'old'\n")

    def testEachUpdateBacksUpTheDatabaseKeepingTheNewestThree(self):
        for index, version in enumerate(("1.4.9", "1.5.0", "1.5.1", "1.5.2")):
            self.release(version, commit=str(index + 1) * 40)
            self.updater.apply(version, str(index + 1) * 40)

        backups = sorted((self.databasePath.parent / "server-update").glob("database-*.sqlite3"))
        self.assertEqual(
            [backup.name.rsplit("-", 1)[1] for backup in backups],
            ["1.4.9.sqlite3", "1.5.0.sqlite3", "1.5.1.sqlite3"],
        )
        with closing(sqlite3.connect(backups[-1])) as database:
            self.assertEqual(
                database.execute("SELECT machine FROM usage").fetchall(), [("DJ-000001",)]
            )

    def testRollbackSwapsTheCurrentAndPreviousVersions(self):
        self.assertIsNone(self.updater.previousVersion())
        self.release(
            "1.4.9",
            {"ai_markdown.py": "VALUE = 'new'\n", "static/admin.css": "body {}"},
        )
        self.updater.apply("1.4.9", NEW_COMMIT)
        self.assertEqual(self.updater.previousVersion(), ("1.4.8", OLD_COMMIT))

        result = self.updater.rollback()

        self.assertEqual((result.version, result.commit), ("1.4.8", OLD_COMMIT))
        self.assertEqual(self.updater.installedVersion(), ("1.4.8", OLD_COMMIT))
        self.assertEqual(self.read("ai_markdown.py"), "VALUE = 'old'\n")
        self.assertFalse((self.projectDir / "static/admin.css").exists())
        self.assertEqual(self.updater.previousVersion(), ("1.4.9", NEW_COMMIT))

        self.updater.rollback()

        self.assertEqual(self.updater.installedVersion(), ("1.4.9", NEW_COMMIT))
        self.assertEqual(self.read("static/admin.css"), "body {}")
        self.assertEqual(self.usageRows(), [("DJ-000001",)])

    def testRollbackWithoutAPreviousVersionIsRefused(self):
        with self.assertRaises(server_update.ServerUpdateError) as raised:
            self.updater.rollback()
        self.assertEqual(raised.exception.step, "回滚")

    def testAFailedReplacementRestoresEveryOldFile(self):
        (self.projectDir / "templates/zz_blocked.html").mkdir()
        self.release(
            "1.4.9",
            {
                "ai_markdown.py": "VALUE = 'new'\n",
                "static/admin.css": "body {}",
                "templates/zz_blocked.html": "cannot replace a directory",
            },
        )

        with self.assertRaises(server_update.ServerUpdateError) as raised:
            self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual(raised.exception.step, "替换")
        for name, text in self.installed.items():
            self.assertEqual(self.read(name), text, name)
        self.assertFalse((self.projectDir / "static/admin.css").exists())
        self.assertEqual(
            sorted(path.name for path in (self.projectDir / "templates").iterdir()),
            ["admin_base.html", "zz_blocked.html"],
        )
        self.assertIsNone(self.updater.previousVersion())

    def testApplyInstallsTheCommitTheAdminConfirmedEvenAfterMainMovedOn(self):
        self.release("1.4.9", {"ai_markdown.py": "VALUE = '1.4.9'\n"})
        self.release("1.5.0", {"ai_markdown.py": "VALUE = '1.5.0'\n"}, commit="f" * 40)

        result = self.updater.apply("1.4.9", NEW_COMMIT)

        self.assertEqual((result.version, result.commit), ("1.4.9", NEW_COMMIT))
        self.assertEqual(self.read("ai_markdown.py"), "VALUE = '1.4.9'\n")

    def testApplyRefusesCommitsThatAreNotARelease(self):
        self.release("1.4.9")
        self.release("1.5.0", commit="f" * 40, onMain=False)
        cases = {
            "not on main": ("1.5.0", "f" * 40),
            "another version": ("1.5.0", NEW_COMMIT),
            "not higher": ("1.4.8", OLD_COMMIT),
            "not a commit": ("1.4.9", "main"),
        }
        for case, (version, commit) in cases.items():
            with self.subTest(case):
                with self.assertRaises(server_update.ServerUpdateError) as raised:
                    self.updater.apply(version, commit)
                self.assertEqual(raised.exception.step, "检查")
                self.assertNotIn(
                    f"https://codeload.github.com/{REPO}/tar.gz/{commit}", self.github.requested
                )
        self.assertEqual(self.updater.installedVersion(), ("1.4.8", OLD_COMMIT))

    def testUnexpectedFileErrorsStillNameAStep(self):
        self.release("1.4.9")
        (self.databasePath.parent / "server-update").write_text("not a directory")
        with self.assertRaises(server_update.ServerUpdateError):
            self.updater.apply("1.4.9", NEW_COMMIT)

    def testAnUnreadableDatabaseStopsTheTrialImport(self):
        self.release("1.4.9")
        self.databasePath.write_bytes(b"not a database" * 100)
        with self.assertRaises(server_update.ServerUpdateError) as raised:
            self.updater.apply("1.4.9", NEW_COMMIT)
        self.assertEqual(raised.exception.step, "试导入")

    def testOnlyOneUpdateRunsAtATime(self):
        self.release("1.4.9")
        downloading = threading.Event()
        release = threading.Event()
        fetch = self.github.fetch

        def slowFetch(url, accept=None):
            if "codeload" in url:
                downloading.set()
                release.wait(10)
            return fetch(url, accept)

        self.updater.fetch = slowFetch
        first = threading.Thread(target=self.updater.apply, args=("1.4.9", NEW_COMMIT))
        first.start()
        self.addCleanup(first.join)
        self.addCleanup(release.set)
        self.assertTrue(downloading.wait(10))

        with self.assertRaises(server_update.ServerUpdateError) as raised:
            self.updater.rollback()

        self.assertIn("已有更新在进行", raised.exception.detail)
        release.set()
        first.join()
        self.assertEqual(self.updater.installedVersion(), ("1.4.9", NEW_COMMIT))


class _AdminFixture(test_ai_admin.AIAdminTest):
    """Borrow the admin fixture without collecting AIAdminTest's own tests."""

    __test__ = False


class ServerUpdateAdminTest(TestCase):
    BASE = "https://dash.djcatpro.top"

    def setUp(self):
        self.admin = _AdminFixture("setUp")
        self.admin.setUp()
        self.addCleanup(self.admin.doCleanups)
        self.client = self.admin.client
        self.packages = ServerUpdateTest("setUp")
        self.packages.setUp()
        self.addCleanup(self.packages.doCleanups)
        self.restarts = []
        self.restarter = lambda: (lambda: self.restarts.append("SIGHUP"))
        extension = patch.dict(
            ai_markdown.app.extensions["server_update"],
            {"updater": self.packages.updater, "restarter": lambda: self.restarter()},
        )
        extension.start()
        self.addCleanup(extension.stop)

    def get(self, url):
        return self.client.get(url, base_url=self.BASE)

    def post(self, url, **data):
        page = self.get("/admin/server-update/")
        return self.client.post(
            url,
            base_url=self.BASE,
            data={"csrf_token": self.admin._csrf(page), **data},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )

    def testPageNeedsLoginAndTheSidebarShowsTheRunningServerVersion(self):
        self.assertEqual(self.get("/admin/server-update/").status_code, 302)
        self.admin._login()

        page = self.get("/admin/").get_data(as_text=True)

        self.assertIn(f"服务端 {server_update.SERVER_VERSION}", page)
        self.assertIn('href="/admin/server-update/"', page)

    def testCheckReplacesTheResultInPlaceWithTheNewVersionAndItsChanges(self):
        self.admin._login()
        self.packages.release(
            "1.4.9", history=[historyEntry(NEW_COMMIT, "feat: 后台一键更新服务端"),
                              historyEntry(OLD_COMMIT, "已安装")],
        )

        response = self.post("/admin/server-update/check")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["message"], "发现新版本 1.4.9")
        html = response.json["replace"]["server-update-check"]
        self.assertIn("feat: 后台一键更新服务端", html)
        self.assertIn('name="version" value="1.4.9"', html)
        self.assertIn(f'name="commit" value="{NEW_COMMIT}"', html)

    def testCheckSaysUpToDateOrWhyItFailed(self):
        self.admin._login()
        self.packages.release("1.4.8")
        self.assertEqual(self.post("/admin/server-update/check").json["message"], "已是最新版本")

        self.packages.github.offline = True
        response = self.post("/admin/server-update/check")
        self.assertEqual(response.status_code, 502)
        self.assertIn("检查更新失败", response.json["message"])

    def testEveryActionNeedsTheCsrfToken(self):
        self.admin._login()
        for action in ("check", "apply", "rollback"):
            with self.subTest(action=action):
                response = self.client.post(
                    f"/admin/server-update/{action}", base_url=self.BASE, data={"version": "1.4.9"}
                )
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.packages.github.requested, [])

    def testUpdateAnswersFirstThenRestartsAndTellsThePageWhichVersionToWaitFor(self):
        self.admin._login()
        self.packages.release("1.4.9", {"ai_markdown.py": "VALUE = 'new'\n"})

        response = self.post("/admin/server-update/apply", version="1.4.9", commit=NEW_COMMIT)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["message"], "已更新到 1.4.9")
        self.assertEqual(response.json["redirect"], "/admin/server-update/")
        self.assertEqual(
            response.json["awaitVersion"],
            {"url": "/admin/server-update/running", "version": "1.4.9", "commit": NEW_COMMIT},
        )
        response.close()
        self.assertEqual(self.restarts, ["SIGHUP"])
        self.assertEqual(self.packages.read("ai_markdown.py"), "VALUE = 'new'\n")

    def testRunningReportsTheVersionThisWorkerImported(self):
        self.admin._login()
        self.assertEqual(
            self.get("/admin/server-update/running").json,
            {"version": server_update.SERVER_VERSION, "commit": ""},
        )

    def testAFailedUpdateNamesTheStepAndDoesNotRestart(self):
        self.admin._login()
        self.packages.release("1.4.9", {"ai_markdown.py": "raise SystemExit('坏了')\n"})

        response = self.post("/admin/server-update/apply", version="1.4.9", commit=NEW_COMMIT)

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json["message"].startswith("试导入失败："))
        self.assertNotIn("awaitVersion", response.json)
        response.close()
        self.assertEqual(self.restarts, [])

    def testRollbackRestartsIntoThePreviousVersion(self):
        self.admin._login()
        self.packages.release("1.4.9")
        self.post("/admin/server-update/apply", version="1.4.9", commit=NEW_COMMIT).close()
        page = self.get("/admin/server-update/").get_data(as_text=True)
        self.assertIn("回滚到 1.4.8", page)

        response = self.post("/admin/server-update/rollback")

        self.assertEqual(response.json["message"], "已回滚到 1.4.8")
        self.assertEqual(response.json["awaitVersion"]["commit"], OLD_COMMIT)
        response.close()
        self.assertEqual(self.restarts, ["SIGHUP", "SIGHUP"])

    def testOutsideGunicornTheAdminIsAskedToRestartByHand(self):
        self.admin._login()
        self.restarter = lambda: None
        self.packages.release("1.4.9", {"requirements.txt": "gunicorn>=24\n"})

        response = self.post("/admin/server-update/apply", version="1.4.9", commit=NEW_COMMIT)

        self.assertIn("请手动重启", response.json["message"])
        self.assertNotIn("awaitVersion", response.json)

    def testGunicornUpgradeAsksForAPanelRestart(self):
        self.admin._login()
        self.packages.release("1.4.9", {"requirements.txt": "gunicorn>=24\n"})
        response = self.post("/admin/server-update/apply", version="1.4.9", commit=NEW_COMMIT)
        self.assertIn("宝塔面板重启", response.json["message"])
