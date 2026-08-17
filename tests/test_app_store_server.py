import os
import re
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from server import ai_markdown, app_store


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

    def _createApp(self, installDir="demo", expectedStatus=302, **overrides):
        self._login()
        data = {
            "csrf_token": self._csrf(),
            "name": "Demo",
            "developer": "DJCat",
            "description": "A demo app",
            "version": "1.2.0",
            "install_dir": installDir,
            "icon_url": "https://cdn.example.test/demo.png",
            "recommended": "1",
            "announcement": "维护公告",
            "open_action_type": "program",
            "open_action_target": "demo.exe",
            "open_action_arguments": "--minimized\n--profile default",
            "x86_64_enabled": "1",
            "x86_64_url": "https://cdn.example.test/demo-x64.zip",
        }
        data.update(overrides)
        response = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"} if expectedStatus != 302 else None,
            data=data,
        )
        self.assertEqual(response.status_code, expectedStatus)

    def _createPreset(self, appId=1, title="打开应用", **overrides):
        data = {
            "csrf_token": self._csrf(),
            "preset_app_id": str(appId),
            "preset_title": title,
            "preset_description": "启动软件",
            "preset_action_type": "program",
            "preset_action_target": "demo.exe",
            "preset_action_arguments": "",
        }
        data.update(overrides)
        response = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            data=data,
        )
        self.assertEqual(response.status_code, 302)

    def _createAd(self, title="广告", enabled=True, **overrides):
        data = {
            "csrf_token": self._csrf(),
            "title": title,
            "description": "广告简介",
            "image_url": "https://cdn.example.test/ad.png",
        }
        if enabled:
            data["enabled"] = "1"
        data.update(overrides)
        response = self.client.post(
            "/admin/app-store/ads/",
            base_url="https://dash.djcatpro.top",
            data=data,
        )
        self.assertEqual(response.status_code, 302)

    def testAdminAllowsSpaceInInstallDirectory(self):
        self._createApp("Demo App")

        catalog = self.client.get(
            "/app-store/catalog",
            base_url="https://api.djcatpro.top",
        )

        self.assertEqual(catalog.json["apps"][0]["install_dir"], "Demo App")
        editPage = self.client.get(
            "/admin/app-store/apps/1",
            base_url="https://dash.djcatpro.top",
        )
        self.assertIn("可以包含空格", editPage.get_data(as_text=True))

    def testInstallDirectoryIsUniqueIgnoringCase(self):
        self._createApp("Demo")
        self._createApp("demo", expectedStatus=400)

        catalog = self.client.get(
            "/app-store/catalog",
            base_url="https://api.djcatpro.top",
        )
        self.assertEqual(len(catalog.json["apps"]), 1)

    def testInstallDirectoryRejectsWindowsReservedNames(self):
        for installDir in ("CON", "LPT1.tools", "Demo."):
            with self.subTest(installDir=installDir):
                self._createApp(installDir, expectedStatus=400)

    def testAdminRejectsOversizedCatalogFields(self):
        self._createApp(expectedStatus=400, name="x" * 121)
        self._createApp(
            expectedStatus=400,
            icon_url="https://cdn.example.test/" + "x" * 2048,
        )

    def testPresetCustomSchemeRequiresSystemProtocolWithoutDiscardingForm(self):
        self._createApp()
        target = "classisland://app/settings/general/"
        data = {
            "csrf_token": self._csrf(),
            "preset_app_id": "1",
            "preset_title": "基本设置",
            "preset_description": "进入 ClassIsland 软件的设置",
            "preset_action_type": "url",
            "preset_action_target": target,
            "preset_action_arguments": "--minimized\n--profile default",
        }

        invalid = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            data=data,
        )

        body = invalid.get_data(as_text=True)
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(
            "HTTPS 网页目标必须以 https:// 开头；classisland:// 等自定义协议请选择“系统协议”",
            body,
        )
        self.assertIn('value="基本设置"', body)
        self.assertIn('value="进入 ClassIsland 软件的设置"', body)
        self.assertIn('<option value="url" selected>HTTPS 网页</option>', body)
        self.assertIn(f'value="{target}"', body)
        self.assertIn("--minimized\n--profile default", body)

        data["preset_action_type"] = "uri"
        created = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            data=data,
        )

        self.assertEqual(created.status_code, 302)
        preset = self.client.get(
            "/app-store/catalog",
            base_url="https://api.djcatpro.top",
        ).json["apps"][0]["presets"][0]
        self.assertEqual(preset["title"], "基本设置")
        self.assertEqual(preset["action"]["type"], "uri")
        self.assertEqual(preset["action"]["target"], target)

    def testInvalidMarketFormsKeepSubmittedValues(self):
        self._login()
        appResponse = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "name": "Keep App",
                "developer": "Keep Developer",
                "description": "Keep App Description",
                "version": "1.0",
                "install_dir": "CON",
                "icon_url": "http://invalid.test/icon.png",
                "recommended": "1",
                "announcement": "Keep Announcement",
                "open_action_type": "program",
                "open_action_target": "bin/keep.exe",
                "open_action_arguments": "--minimized\n--profile default",
                "x86_64_enabled": "1",
                "x86_64_url": "http://invalid.test/keep.zip",
            },
        )

        appBody = appResponse.get_data(as_text=True)
        self.assertEqual(appResponse.status_code, 400)
        for value in (
            "Keep App",
            "Keep Developer",
            "Keep App Description",
            "CON",
            "http://invalid.test/icon.png",
            "Keep Announcement",
            "bin/keep.exe",
            "--minimized\n--profile default",
            "http://invalid.test/keep.zip",
        ):
            self.assertIn(value, appBody)
        self.assertIn('<option value="program" selected>程序</option>', appBody)
        self.assertIn('name="recommended" value="1" checked', appBody)
        self.assertIn('name="x86_64_enabled" value="1" checked', appBody)

        self._createApp()
        presetResponse = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "preset_app_id": "1",
                "preset_title": "Keep Preset",
                "preset_description": "Keep Preset Description",
                "preset_action_type": "program",
                "preset_action_target": "../invalid.exe",
                "preset_action_arguments": "--minimized\n--profile default",
            },
        )

        presetBody = presetResponse.get_data(as_text=True)
        self.assertEqual(presetResponse.status_code, 400)
        for value in (
            "Keep Preset",
            "Keep Preset Description",
            "../invalid.exe",
            "--minimized\n--profile default",
        ):
            self.assertIn(value, presetBody)
        self.assertIn('<option value="program" selected>程序</option>', presetBody)

        adResponse = self.client.post(
            "/admin/app-store/ads/",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "title": "Keep Advertisement",
                "description": "Keep Advertisement Description",
                "image_url": "http://invalid.test/ad.png",
                "app_id": "1",
                "enabled": "1",
            },
        )

        adBody = adResponse.get_data(as_text=True)
        self.assertEqual(adResponse.status_code, 400)
        for value in (
            "Keep Advertisement",
            "Keep Advertisement Description",
            "http://invalid.test/ad.png",
        ):
            self.assertIn(value, adBody)
        self.assertIn('<option value="1" selected>Demo</option>', adBody)
        self.assertIn('name="enabled" value="1" checked', adBody)

    def testDuplicateInstallDirectoryKeepsSubmittedApplication(self):
        self._createApp()
        response = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "name": "Keep Duplicate",
                "developer": "Keep Developer",
                "description": "Keep Duplicate Description",
                "version": "2.0",
                "install_dir": "Demo",
                "icon_url": "https://cdn.example.test/duplicate.png",
                "open_action_type": "program",
                "open_action_target": "bin/keep.exe",
                "open_action_arguments": "--profile duplicate",
                "x86_64_enabled": "1",
                "x86_64_url": "https://cdn.example.test/duplicate.zip",
            },
        )

        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 400)
        self.assertIn("安装目录已被其他软件使用", body)
        for value in (
            "Keep Duplicate",
            "Keep Developer",
            "Keep Duplicate Description",
            "Demo",
            "bin/keep.exe",
            "--profile duplicate",
            "https://cdn.example.test/duplicate.zip",
        ):
            self.assertIn(value, body)

    def testApplicationCustomSchemeRequiresSystemProtocolWithoutDiscardingForm(self):
        self._login()
        target = "classisland://app/settings/general/"
        data = {
            "csrf_token": self._csrf(),
            "name": "ClassIsland",
            "version": "2.0",
            "install_dir": "ClassIsland",
            "open_action_type": "url",
            "open_action_target": target,
            "open_action_arguments": "--minimized",
            "x86_64_enabled": "1",
            "x86_64_url": "https://cdn.example.test/classisland.zip",
        }

        invalid = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data=data,
        )

        body = invalid.get_data(as_text=True)
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(
            "HTTPS 网页目标必须以 https:// 开头；classisland:// 等自定义协议请选择“系统协议”",
            body,
        )
        self.assertIn('<option value="url" selected>HTTPS 网页</option>', body)
        self.assertIn(f'value="{target}"', body)
        self.assertIn("--minimized", body)

        data["open_action_type"] = "uri"
        created = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data=data,
        )
        self.assertEqual(created.status_code, 302)
        action = self.client.get(
            "/app-store/catalog",
            base_url="https://api.djcatpro.top",
        ).json["apps"][0]["open_action"]
        self.assertEqual(action["type"], "uri")
        self.assertEqual(action["target"], target)

    def testAdvertisementMissingApplicationKeepsSubmittedValues(self):
        self._createApp()
        self._createAd()
        for path, title in (
            ("/admin/app-store/ads/", "Keep New Advertisement"),
            ("/admin/app-store/ads/1", "Keep Edited Advertisement"),
        ):
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    base_url="https://dash.djcatpro.top",
                    data={
                        "csrf_token": self._csrf(),
                        "title": title,
                        "description": "Keep Missing App Description",
                        "image_url": "https://cdn.example.test/missing-app.png",
                        "app_id": "999",
                        "enabled": "1",
                    },
                )

                body = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 400)
                self.assertIn("绑定的软件不存在", body)
                self.assertIn(title, body)
                self.assertIn("Keep Missing App Description", body)
                self.assertIn("https://cdn.example.test/missing-app.png", body)
                self.assertIn('name="enabled" value="1" checked', body)

    def testEditingMissingMarketItemsReturnsNotFound(self):
        self._createApp()
        missingApp = self.client.post(
            "/admin/app-store/apps/999",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={
                "csrf_token": self._csrf(),
                "name": "Missing",
                "version": "1.0",
                "install_dir": "missing",
            },
        )
        missingPreset = self.client.post(
            "/admin/app-store/presets/999",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={
                "csrf_token": self._csrf(),
                "preset_app_id": "1",
                "preset_title": "Missing",
                "preset_action_type": "program",
                "preset_action_target": "demo.exe",
            },
        )
        missingAd = self.client.post(
            "/admin/app-store/ads/999",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={
                "csrf_token": self._csrf(),
                "title": "Missing",
                "image_url": "https://cdn.example.test/missing.png",
            },
        )

        self.assertEqual(missingApp.status_code, 404)
        self.assertEqual(missingPreset.status_code, 404)
        self.assertEqual(missingAd.status_code, 404)

    def testCatalogLoadsPackagesAndPresetsWithConstantQueryCount(self):
        self._createApp("demo-one")
        self._createApp("demo-two")
        statements = []
        connect = ai_markdown.sqlite3.connect

        def tracedConnect(*args, **kwargs):
            database = connect(*args, **kwargs)
            database.set_trace_callback(statements.append)
            return database

        with patch.object(ai_markdown.sqlite3, "connect", side_effect=tracedConnect):
            response = self.client.get(
                "/app-store/catalog",
                base_url="https://api.djcatpro.top",
            )

        self.assertEqual(response.status_code, 200)
        selects = [statement.lower() for statement in statements if statement.lstrip().lower().startswith("select")]
        self.assertEqual(sum("from market_packages" in query for query in selects), 1)
        self.assertEqual(sum("from market_presets" in query for query in selects), 1)

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
        preset = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "preset_app_id": "1",
                "preset_title": "打开",
                "preset_description": "启动",
                "preset_action_type": "program",
                "preset_action_target": "demo.exe",
                "preset_action_arguments": "--minimized",
                "preset_sort_order": "0",
            },
        )
        self.assertEqual(preset.status_code, 302)
        catalog = self.client.get("/app-store/catalog", base_url="https://api.djcatpro.top")
        app = catalog.json["apps"][0]
        self.assertEqual(app["announcement"], "维护公告")
        self.assertEqual(app["presets"][0]["action"]["target"], "demo.exe")
        self.assertEqual(app["presets"][0]["action"]["arguments"], {"args": ["--minimized"]})
        self.assertEqual(app["open_action"]["arguments"], {"args": ["--minimized", "--profile default"]})
        self.assertTrue(app["recommended"])

        redirect = self.client.get(
            "/app-store/apps/1/download?arch=x86_64",
            base_url="https://api.djcatpro.top",
        )
        self.assertEqual(redirect.status_code, 302)
        self.assertEqual(redirect.location, "https://cdn.example.test/demo-x64.zip")
        with closing(ai_markdown._connect()) as database:
            self.assertEqual(database.execute("SELECT download_count FROM market_applications WHERE id = 1").fetchone()[0], 1)
            self.assertEqual(database.execute("SELECT COUNT(*) FROM market_download_events").fetchone()[0], 1)
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
        self.assertNotIn("presets_json", page.get_data(as_text=True))
        self.assertIn("打开预设卡片管理", page.get_data(as_text=True))
        presets = self.client.get("/admin/app-store/presets/", base_url="https://dash.djcatpro.top")
        presetsBody = presets.get_data(as_text=True)
        self.assertIn("选择软件", presetsBody)
        self.assertNotIn('name="preset_title"', presetsBody)
        selectedPresets = self.client.get(
            "/admin/app-store/presets/?app_id=1",
            base_url="https://dash.djcatpro.top",
        )
        selectedBody = selectedPresets.get_data(as_text=True)
        self.assertIn("新增预设卡片", selectedBody)
        self.assertIn("--minimized", selectedBody)

        edited = self.client.post(
            "/admin/app-store/presets/1",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "preset_app_id": "1",
                "preset_title": "打开网页",
                "preset_description": "访问文档",
                "preset_action_type": "url",
                "preset_action_target": "https://docs.example.test",
                "preset_action_arguments": "",
                "preset_sort_order": "1",
            },
        )
        self.assertEqual(edited.status_code, 302)
        self.assertEqual(
            self.client.get("/app-store/catalog", base_url="https://api.djcatpro.top").json["apps"][0]["presets"][0]["action"]["target"],
            "https://docs.example.test",
        )
        self.client.post(
            "/admin/app-store/apps/1",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(),
                "name": "Demo",
                "developer": "DJCat",
                "description": "Updated",
                "version": "1.3.0",
                "install_dir": "demo",
                "icon_url": "https://cdn.example.test/demo.png",
                "recommended": "1",
                "announcement": "维护公告",
                "open_action_type": "program",
                "open_action_target": "demo.exe",
                "open_action_arguments": "--minimized",
                "x86_64_enabled": "1",
                "x86_64_url": "https://cdn.example.test/demo-x64.zip",
            },
        )
        self.assertEqual(
            len(self.client.get("/app-store/catalog", base_url="https://api.djcatpro.top").json["apps"][0]["presets"]),
            1,
        )
        deleted = self.client.post(
            "/admin/app-store/presets/1",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(), "delete": "1"},
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(
            self.client.get("/app-store/catalog", base_url="https://api.djcatpro.top").json["apps"][0]["presets"],
            [],
        )

    def testDashboardIncludesMarketServiceAndCumulativeData(self):
        self._createApp()
        self.client.get(
            "/app-store/apps/1/download?arch=x86_64",
            base_url="https://api.djcatpro.top",
        )
        dashboard = self.client.get("/admin/", base_url="https://dash.djcatpro.top")
        self.assertEqual(dashboard.status_code, 200)
        body = dashboard.get_data(as_text=True)
        self.assertIn("今日应用下载", body)
        self.assertIn("全部数据", body)
        self.assertIn("应用市场", body)
        self.assertIn("累计下载", body)
        stats = ai_markdown._dashboardStats()
        self.assertEqual(stats["today"]["market_downloads"], 1)
        self.assertEqual(stats["all"]["market_downloads"], 1)

    def testMarketplaceSchemaMigrationRunsOncePerDatabase(self):
        statements = []

        def connect():
            database = ai_markdown._connect()
            database.set_trace_callback(statements.append)
            return database

        app_store._ensureSchema(connect)
        self.assertTrue(
            any(
                "CREATE TABLE IF NOT EXISTS market_applications" in statement
                for statement in statements
            )
        )
        statements.clear()

        app_store._ensureSchema(connect)

        self.assertFalse(any("CREATE TABLE" in statement for statement in statements))

    def testDownloadRetriesWithSameTokenCountOnce(self):
        self._createApp()
        path = "/app-store/apps/1/download?arch=x86_64&token=" + "a" * 32
        for _ in range(2):
            response = self.client.get(
                path,
                base_url="https://api.djcatpro.top",
                headers={"Range": "bytes=1-1"},
            )
            self.assertEqual(response.status_code, 302)

        with closing(ai_markdown._connect()) as database:
            self.assertEqual(
                database.execute(
                    "SELECT download_count FROM market_applications WHERE id = 1"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                database.execute("SELECT COUNT(*) FROM market_download_events").fetchone()[0],
                1,
            )

    def testPresetRejectsUnsafeTargets(self):
        self._createApp()
        response = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={
                "csrf_token": self._csrf(),
                "preset_app_id": "1",
                "preset_title": "危险动作",
                "preset_action_type": "program",
                "preset_action_target": "../demo.exe",
            },
        )
        self.assertEqual(response.status_code, 400)

    def testPresetRejectsWindowsPathDisguisedAsUri(self):
        self._createApp()
        response = self.client.post(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={
                "csrf_token": self._csrf(),
                "preset_app_id": "1",
                "preset_title": "危险动作",
                "preset_action_type": "uri",
                "preset_action_target": r"C:\Windows\System32\calc.exe",
            },
        )
        self.assertEqual(response.status_code, 400)

    def testAdvertisementRejectsMissingApplicationTarget(self):
        self._login()
        response = self.client.post(
            "/admin/app-store/ads/",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={
                "csrf_token": self._csrf(),
                "title": "Missing app",
                "image_url": "https://cdn.example.test/ad.png",
                "app_id": "999",
                "enabled": "1",
            },
        )

        self.assertEqual(response.status_code, 400)

    def testDeletingAppCleansUpRelatedMarketData(self):
        self._createApp()
        with closing(ai_markdown._connect()) as database:
            database.execute(
                "INSERT INTO market_presets(app_id, title, action_type, action_target) "
                "VALUES (1, 'Open', 'program', 'demo.exe')"
            )
            database.execute(
                "INSERT INTO market_advertisements(title, image_url, app_id) "
                "VALUES ('Demo', 'https://cdn.example.test/ad.png', 1)"
            )
            database.commit()

        response = self.client.post(
            "/admin/app-store/apps/1/delete",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf()},
        )
        self.assertEqual(response.status_code, 302)
        with closing(ai_markdown._connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM market_packages").fetchone()[0], 0)
            self.assertEqual(database.execute("SELECT COUNT(*) FROM market_presets").fetchone()[0], 0)
            self.assertIsNone(database.execute("SELECT app_id FROM market_advertisements").fetchone()[0])

    def testCatalogSurvivesInvalidStoredPresetArguments(self):
        self._createApp()
        with closing(ai_markdown._connect()) as database:
            database.execute(
                "INSERT INTO market_presets"
                "(app_id, title, action_type, action_target, action_arguments) "
                "VALUES (1, 'Open', 'program', 'demo.exe', '{broken')"
            )
            database.commit()

        response = self.client.get(
            "/app-store/catalog",
            base_url="https://api.djcatpro.top",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["apps"][0]["presets"][0]["action"]["arguments"], {})

    def testNewAppFormDefaultsBothArchitecturesAndUsesEditButton(self):
        self._login()
        page = self.client.get("/admin/app-store/apps/new", base_url="https://dash.djcatpro.top")
        body = page.get_data(as_text=True)
        self.assertIn('<label class="option-row"><span><strong>x86_64</strong>', body)
        self.assertIn('name="x86_64_enabled" value="1" checked', body)
        self.assertIn('name="arm64_enabled" value="1" checked', body)
        self.assertIn("程序参数", body)
        self.assertNotIn("参数 JSON", body)

        self._createApp()
        listing = self.client.get("/admin/app-store/apps/", base_url="https://dash.djcatpro.top")
        body = listing.get_data(as_text=True)
        self.assertIn(">编辑</a>", body)
        self.assertIn('data-remove-on-success="tr"', body)
        self.assertIn("data-item-count", body)
        self.assertNotIn('class="table-action" href="/admin/app-store/apps/1">Demo</a>', body)

    def testPresetManagementSelectsAnApplicationBeforeEditingCards(self):
        self._createApp("demo-one", name="Demo One")
        self._createApp("demo-two", name="Demo Two")
        self._createPreset(1, "第一张卡片")

        overview = self.client.get(
            "/admin/app-store/presets/",
            base_url="https://dash.djcatpro.top",
        )
        body = overview.get_data(as_text=True)
        self.assertIn("选择软件", body)
        self.assertIn("Demo One", body)
        self.assertIn("Demo Two", body)
        self.assertIn("1 张卡片", body)
        self.assertNotIn('name="preset_title"', body)

        selected = self.client.get(
            "/admin/app-store/presets/?app_id=1",
            base_url="https://dash.djcatpro.top",
        )
        selectedBody = selected.get_data(as_text=True)
        self.assertIn("Demo One", selectedBody)
        self.assertIn("的预设卡片", selectedBody)
        self.assertIn("第一张卡片", selectedBody)
        self.assertIn('name="preset_app_id" value="1"', selectedBody)
        self.assertIn("返回软件列表", selectedBody)

        editing = self.client.get(
            "/admin/app-store/presets/?app_id=1&edit=1",
            base_url="https://dash.djcatpro.top",
        )
        self.assertIn("编辑预设卡片", editing.get_data(as_text=True))
        self.assertEqual(
            self.client.get(
                "/admin/app-store/presets/?app_id=999",
                base_url="https://dash.djcatpro.top",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                "/admin/app-store/presets/?app_id=2&edit=1",
                base_url="https://dash.djcatpro.top",
            ).status_code,
            404,
        )

    def testMarketContentOrderCanBeManagedWithMoveButtons(self):
        self._createApp("demo-one", name="One")
        self._createApp("demo-two", name="Two")
        self._createApp("demo-three", name="Three")

        movedApp = self.client.post(
            "/admin/app-store/apps/3/move",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(), "direction": "up"},
        )
        self.assertEqual(movedApp.status_code, 302)
        self.assertEqual(
            [app["id"] for app in self.client.get(
                "/app-store/catalog", base_url="https://api.djcatpro.top"
            ).json["apps"]],
            [1, 3, 2],
        )

        self._createPreset(1, "第一张")
        self._createPreset(1, "第二张")
        movedPreset = self.client.post(
            "/admin/app-store/presets/2/move",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(), "direction": "up"},
        )
        self.assertEqual(movedPreset.status_code, 302)
        catalog = self.client.get(
            "/app-store/catalog", base_url="https://api.djcatpro.top"
        ).json
        self.assertEqual(
            [preset["title"] for preset in catalog["apps"][0]["presets"]],
            ["第二张", "第一张"],
        )

        self._createAd("第一条广告")
        self._createAd("第二条广告")
        movedAd = self.client.post(
            "/admin/app-store/ads/2/move",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(), "direction": "up"},
        )
        self.assertEqual(movedAd.status_code, 302)
        catalog = self.client.get(
            "/app-store/catalog", base_url="https://api.djcatpro.top"
        ).json
        self.assertEqual(
            [ad["title"] for ad in catalog["ads"]],
            ["第二条广告", "第一条广告"],
        )

        invalidMove = self.client.post(
            "/admin/app-store/apps/1/move",
            base_url="https://dash.djcatpro.top",
            headers={"Accept": "application/json"},
            data={"csrf_token": self._csrf(), "direction": "sideways"},
        )
        self.assertEqual(invalidMove.status_code, 400)

    def testAdvertisementPageSeparatesCreationAndPublishedList(self):
        self._createApp()
        self._createAd("投放中的广告", app_id="1")
        self._createAd("暂停的广告", enabled=False)

        page = self.client.get(
            "/admin/app-store/ads/",
            base_url="https://dash.djcatpro.top",
        )
        body = page.get_data(as_text=True)
        self.assertIn("新建广告", body)
        self.assertIn("已投放广告", body)
        self.assertIn("投放中", body)
        self.assertIn("已暂停", body)
        self.assertIn("调整广告顺序", body)
        self.assertIn("?edit=1", body)

    def testExistingApplicationTableIsMigratedForManualOrdering(self):
        self._createApp()
        with closing(ai_markdown._connect()) as database:
            database.execute("DROP INDEX market_apps_order_idx")
            database.execute(
                "ALTER TABLE market_applications DROP COLUMN sort_order"
            )
            database.commit()
        app_store._initializedSchemas.discard(
            str(ai_markdown.DATABASE_PATH.resolve())
        )

        page = self.client.get(
            "/admin/app-store/apps/",
            base_url="https://dash.djcatpro.top",
        )

        self.assertEqual(page.status_code, 200)
        with closing(ai_markdown._connect()) as database:
            columns = {
                row[1]
                for row in database.execute(
                    "PRAGMA table_info(market_applications)"
                )
            }
        self.assertIn("sort_order", columns)

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
        body = page.get_data(as_text=True)
        self.assertIn("广告横幅", body)
        self.assertIn("广告管理", body)
        self.assertIn("预设卡片管理", body)
