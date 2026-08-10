import os
import re
import tempfile
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
                "DJCATAI_RATE_LIMIT_SALT": "test-only",
                "DJCATAI_ADMIN_HOST": "dash.djcatpro.top",
                "DJCATAI_ADMIN_USERNAME": "admin",
                "DJCATAI_ADMIN_PASSWORD_HASH": generate_password_hash("secret"),
                "DJCATAI_SETTINGS_KEY": Fernet.generate_key().decode(),
            },
        )
        self.databasePatch.start()
        self.environmentPatch.start()
        self.addCleanup(self.databasePatch.stop)
        self.addCleanup(self.environmentPatch.stop)
        self.addCleanup(self.tempDir.cleanup)
        ai_markdown.app.config.update(
            TESTING=True,
            SECRET_KEY="test-session-secret",
            SESSION_COOKIE_SECURE=True,
        )
        self.client = ai_markdown.app.test_client()

    @staticmethod
    def _csrf(response):
        return re.search(
            rb'name="csrf_token" value="([^"]+)"', response.data
        ).group(1).decode()

    def _login(self):
        login = self.client.get(
            "/admin/login", base_url="https://dash.djcatpro.top"
        )
        return self.client.post(
            "/admin/login",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(login),
                "username": "admin",
                "password": "secret",
            },
            follow_redirects=True,
        )

    def test_admin_entries_are_published_as_one_catalog(self):
        dashboard = self._login()
        csrfToken = self._csrf(dashboard)
        response = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": csrfToken,
                "name": "ClassIsland",
                "developer": "HelloWRC",
                "description": "课表与提醒工具",
                "version": "1.6.0-pre.2",
                "download_url": "https://download.example/classisland.zip",
                "icon_url": "https://download.example/classisland.png",
                "install_dir": "classisland",
                "recommended": "1",
                "action_type": "program",
                "action_target": "ClassIsland.exe",
                "action_arguments": "--profile\nclass 1",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        self.client.post(
            "/admin/app-store/apps/1/components/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(response),
                "title": "打开课表",
                "description": "直接进入当前课表",
                "action_type": "url",
                "action_target": "https://example.com/timetable",
                "action_arguments": "",
            },
        )
        self.client.post(
            "/admin/app-store/ads/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(response),
                "title": "新学期推荐",
                "description": "查看 ClassIsland",
                "image_url": "https://download.example/banner.webp",
                "app_id": "1",
                "sort_order": "10",
            },
        )

        catalog = self.client.get(
            "/app-store/catalog", base_url="https://api.djcatpro.top"
        )

        self.assertEqual(catalog.status_code, 200)
        self.assertEqual(
            catalog.get_json(),
            {
                "apps": [
                    {
                        "id": 1,
                        "name": "ClassIsland",
                        "developer": "HelloWRC",
                        "description": "课表与提醒工具",
                        "version": "1.6.0-pre.2",
                        "download_url": "https://download.example/classisland.zip",
                        "icon_url": "https://download.example/classisland.png",
                        "install_dir": "classisland",
                        "recommended": True,
                        "open_action": {
                            "type": "program",
                            "target": "ClassIsland.exe",
                            "arguments": ["--profile", "class 1"],
                        },
                        "components": [
                            {
                                "id": 1,
                                "title": "打开课表",
                                "description": "直接进入当前课表",
                                "action": {
                                    "type": "url",
                                    "target": "https://example.com/timetable",
                                    "arguments": [],
                                },
                            }
                        ],
                    }
                ],
                "ads": [
                    {
                        "id": 1,
                        "title": "新学期推荐",
                        "description": "查看 ClassIsland",
                        "image_url": "https://download.example/banner.webp",
                        "app_id": 1,
                        "sort_order": 10,
                    }
                ],
            },
        )

    def test_app_list_create_and_settings_are_separate_pages(self):
        dashboard = self._login()
        createPage = self.client.get(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
        )
        self.assertIn("新增软件", createPage.get_data(as_text=True))
        self.assertIn("data-component-list", createPage.get_data(as_text=True))

        created = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(dashboard),
                "name": "Component App",
                "developer": "Developer",
                "description": "Created with preset cards",
                "version": "1",
                "download_url": "https://example.com/app.zip",
                "icon_url": "https://example.com/icon.png",
                "install_dir": "component-app",
                "action_type": "program",
                "action_target": "App.exe",
                "component_title": ["打开主页", "查看文档"],
                "component_description": ["运行主程序", "打开在线文档"],
                "component_action_type": ["program", "url"],
                "component_action_target": [
                    "App.exe",
                    "https://example.com/docs",
                ],
                "component_action_arguments": ["--home", ""],
            },
            follow_redirects=True,
        )
        self.assertEqual(created.request.path, "/admin/app-store/apps/1/")
        self.assertIn("软件设置", created.get_data(as_text=True))
        self.assertIn("打开主页", created.get_data(as_text=True))
        self.assertIn("查看文档", created.get_data(as_text=True))

        applications = self.client.get(
            "/admin/app-store/apps/",
            base_url="https://dash.djcatpro.top",
        )
        applicationsHtml = applications.get_data(as_text=True)
        self.assertIn("已发布软件", applicationsHtml)
        self.assertIn("/admin/app-store/apps/1/", applicationsHtml)
        self.assertNotIn('name="install_dir"', applicationsHtml)

        catalog = self.client.get(
            "/app-store/catalog", base_url="https://api.djcatpro.top"
        ).get_json()
        self.assertEqual(
            [component["title"] for component in catalog["apps"][0]["components"]],
            ["打开主页", "查看文档"],
        )

    def test_missing_application_actions_return_to_the_published_list(self):
        dashboard = self._login()
        csrfToken = self._csrf(dashboard)
        application = {
            "csrf_token": csrfToken,
            "name": "Missing",
            "developer": "Developer",
            "description": "No longer exists",
            "version": "1",
            "download_url": "https://example.com/app.zip",
            "icon_url": "https://example.com/icon.png",
            "action_type": "program",
            "action_target": "App.exe",
        }

        edited = self.client.post(
            "/admin/app-store/apps/999/edit",
            base_url="https://dash.djcatpro.top",
            data=application,
            follow_redirects=True,
        )
        component = self.client.post(
            "/admin/app-store/apps/999/components/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(edited),
                "title": "Missing",
                "description": "No parent application",
                "action_type": "program",
                "action_target": "App.exe",
            },
            follow_redirects=True,
        )

        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.request.path, "/admin/app-store/apps/")
        self.assertIn("未找到软件", edited.get_data(as_text=True))
        self.assertEqual(component.status_code, 200)
        self.assertEqual(component.request.path, "/admin/app-store/apps/")
        self.assertIn("未找到软件", component.get_data(as_text=True))

    def test_admin_validates_edits_and_cascades_application_deletion(self):
        dashboard = self._login()
        csrfToken = self._csrf(dashboard)
        invalid = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": csrfToken,
                "name": "Unsafe",
                "developer": "Tester",
                "description": "不能写出 Program",
                "version": "1",
                "download_url": "https://example.com/app.zip",
                "icon_url": "https://example.com/icon.png",
                "install_dir": "../outside",
                "action_type": "program",
                "action_target": "app.exe",
            },
            follow_redirects=True,
        )
        self.assertIn("格式无效", invalid.get_data(as_text=True))

        invalidAction = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(invalid),
                "name": "Unsafe action",
                "developer": "Tester",
                "description": "不能运行 Program 外程序",
                "version": "1",
                "download_url": "https://example.com/app.zip",
                "icon_url": "https://example.com/icon.png",
                "install_dir": "safe-dir",
                "action_type": "program",
                "action_target": "C:/outside.exe",
            },
            follow_redirects=True,
        )
        self.assertIn("相对 EXE 路径", invalidAction.get_data(as_text=True))

        created = self.client.post(
            "/admin/app-store/apps/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(invalidAction),
                "name": "Original",
                "developer": "Developer",
                "description": "Original description",
                "version": "1",
                "download_url": "https://example.com/app.zip",
                "icon_url": "https://example.com/icon.png",
                "install_dir": "stable-dir",
                "action_type": "program",
                "action_target": "app.exe",
            },
            follow_redirects=True,
        )
        csrfToken = self._csrf(created)
        self.client.post(
            "/admin/app-store/apps/1/components/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": csrfToken,
                "title": "Component",
                "description": "Component description",
                "action_type": "program",
                "action_target": "tools/helper.exe",
            },
        )
        self.client.post(
            "/admin/app-store/ads/new",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": csrfToken,
                "title": "Advertisement",
                "description": "Advertisement description",
                "image_url": "https://example.com/banner.png",
                "app_id": "1",
                "sort_order": "1",
            },
        )

        appsPage = self.client.get(
            "/admin/app-store/apps/", base_url="https://dash.djcatpro.top"
        )
        self.assertIn("软件管理", appsPage.get_data(as_text=True))
        self.assertIn("Original", appsPage.get_data(as_text=True))
        adsPage = self.client.get(
            "/admin/app-store/ads/", base_url="https://dash.djcatpro.top"
        )
        self.assertIn("广告管理", adsPage.get_data(as_text=True))
        self.assertIn("Advertisement", adsPage.get_data(as_text=True))

        edited = self.client.post(
            "/admin/app-store/apps/1/edit",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(appsPage),
                "name": "Renamed",
                "developer": "Developer",
                "description": "Updated description",
                "version": "2-beta",
                "download_url": "https://example.com/app-v2.zip",
                "icon_url": "https://example.com/icon-v2.png",
                "recommended": "1",
                "action_type": "url",
                "action_target": "https://example.com/launch",
            },
            follow_redirects=True,
        )
        self.assertIn("软件已更新", edited.get_data(as_text=True))
        app = self.client.get(
            "/app-store/catalog", base_url="https://api.djcatpro.top"
        ).get_json()["apps"][0]
        self.assertEqual(app["name"], "Renamed")
        self.assertEqual(app["install_dir"], "stable-dir")
        self.assertEqual(app["open_action"]["type"], "url")

        deleted = self.client.post(
            "/admin/app-store/apps/1/delete",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(edited)},
            follow_redirects=True,
        )
        self.assertIn("软件已删除", deleted.get_data(as_text=True))
        self.assertEqual(
            self.client.get(
                "/app-store/catalog", base_url="https://api.djcatpro.top"
            ).get_json(),
            {"apps": [], "ads": []},
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
