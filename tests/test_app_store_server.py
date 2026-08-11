import os
import re
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from server import ai_markdown


class AppStoreServerTest(TestCase):
    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.databasePatch = patch.object(
            ai_markdown,
            "DATABASE_PATH",
            Path(self.tempDir.name) / "usage.sqlite3",
        )
        self.environmentPatch = patch.dict(
            os.environ,
            {
                "DJCATAI_ADMIN_HOST": "dash.djcatpro.top",
                "DJCATAI_API_HOST": "api.djcatpro.top",
                "DJCATAI_ADMIN_USERNAME": "admin",
                "DJCATAI_ADMIN_PASSWORD_HASH": generate_password_hash("secret"),
                "DJCATAI_SETTINGS_KEY": Fernet.generate_key().decode(),
            },
        )
        self.databasePatch.start()
        self.environmentPatch.start()
        self.addCleanup(self.databasePatch.stop)
        self.addCleanup(self.environmentPatch.stop)
        ai_markdown.app.config.update(TESTING=True, SECRET_KEY="test-session")
        self.client = ai_markdown.app.test_client()

    def tearDown(self):
        self.tempDir.cleanup()

    def _login(self):
        page = self.client.get("/admin/login", base_url="https://dash.djcatpro.top")
        token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        response = self.client.post(
            "/admin/login",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": token, "username": "admin", "password": "secret"},
        )
        self.assertEqual(response.status_code, 302)

    def _csrf(self):
        page = self.client.get("/admin/app-store/apps/", base_url="https://dash.djcatpro.top")
        return re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

    def _createApp(self):
        self._login()
        response = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "name": "Demo",
                "developer": "DJCat",
                "description": "A demo app",
                "version": "1.2.0",
                "install_dir": "demo",
                "icon_url": "https://cdn.example.test/demo.png",
                "recommended": "1",
                "announcement": "维护公告",
                "x86_64_enabled": "1",
                "x86_64_url": "https://cdn.example.test/demo-x64.zip",
                "presets_json": '[{"title":"打开","description":"启动","action_type":"program","action_target":"demo.exe","action_arguments":{}}]',
            },
        )
        self.assertEqual(response.status_code, 302)

    def testCatalogIsApiOnlyAndUsesEtag(self):
        api = self.client.get("/app-store/catalog", base_url="https://api.djcatpro.top")
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json["architectures"], ["x86_64", "arm64"])
        self.assertTrue(api.headers["ETag"])
        cached = self.client.get(
            "/app-store/catalog",
            base_url="https://api.djcatpro.top",
            headers={"If-None-Match": api.headers["ETag"]},
        )
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(
            self.client.get("/app-store/catalog", base_url="https://dash.djcatpro.top").status_code,
            404,
        )

    def testAdminCanManageAppAndPublicDownloadIncrementsCount(self):
        self._createApp()
        catalog = self.client.get("/app-store/catalog", base_url="https://api.djcatpro.top")
        app = catalog.json["apps"][0]
        self.assertEqual(app["announcement"], "维护公告")
        self.assertEqual(app["presets"][0]["action"]["target"], "demo.exe")
        self.assertTrue(app["recommended"])

        redirect = self.client.get(
            "/app-store/apps/1/download?arch=x86_64",
            base_url="https://api.djcatpro.top",
        )
        self.assertEqual(redirect.status_code, 302)
        self.assertEqual(redirect.location, "https://cdn.example.test/demo-x64.zip")
        with closing(ai_markdown._connect()) as database:
            self.assertEqual(database.execute("SELECT download_count FROM market_applications WHERE id = 1").fetchone()[0], 1)
        self.client.get(
            "/app-store/apps/1/download?arch=x86_64",
            base_url="https://api.djcatpro.top",
            headers={"Range": "bytes=0-0"},
        )
        with closing(ai_markdown._connect()) as database:
            self.assertEqual(database.execute("SELECT download_count FROM market_applications WHERE id = 1").fetchone()[0], 1)

        page = self.client.get("/admin/app-store/apps/1", base_url="https://dash.djcatpro.top")
        self.assertEqual(page.status_code, 200)
        self.assertIn("预设卡片", page.get_data(as_text=True))

    def testAdminAndApiHostsDoNotCross(self):
        self.assertEqual(
            self.client.get("/admin/app-store/apps/", base_url="https://api.djcatpro.top").status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/admin/app-store/ads/", base_url="https://api.djcatpro.top").status_code,
            404,
        )
        self._login()
        page = self.client.get("/admin/app-store/ads/", base_url="https://dash.djcatpro.top")
        self.assertEqual(page.status_code, 200)
        self.assertIn("广告横幅", page.get_data(as_text=True))
