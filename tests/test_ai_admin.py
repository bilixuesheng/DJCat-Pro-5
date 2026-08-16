import os
import re
import tempfile
from contextlib import closing
from datetime import datetime
from html import escape
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from server import ai_markdown


class AIAdminTest(TestCase):
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

    def _csrf(self, response):
        return re.search(
            rb'name="csrf_token" value="([^"]+)"', response.data
        ).group(1).decode()

    def _login(self):
        login = self.client.get(
            "/admin/login", base_url="https://dash.djcatpro.top"
        )
        response = self.client.post(
            "/admin/login",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(login),
                "username": "admin",
                "password": "secret",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("服务总览", response.get_data(as_text=True))
        self.assertIn("AI 写 Markdown", response.get_data(as_text=True))
        self.assertIn("待配置 API", response.get_data(as_text=True))
        self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        return response

    def _markdownPage(self):
        return self.client.get(
            "/admin/ai/markdown/", base_url="https://dash.djcatpro.top"
        )

    def _settingsPage(self):
        return self.client.get(
            "/admin/ai/markdown/settings", base_url="https://dash.djcatpro.top"
        )

    def _promptPage(self):
        return self.client.get(
            "/admin/ai/markdown/prompt", base_url="https://dash.djcatpro.top"
        )

    def _machinesPage(self, query=""):
        return self.client.get(
            f"/admin/ai/markdown/machines/{query}",
            base_url="https://dash.djcatpro.top",
        )

    def testAdminSeparatesOverviewAndMarkdownManagement(self):
        dashboard = self._login().get_data(as_text=True)
        logo = self.client.get(
            "/static/logo.png", base_url="https://dash.djcatpro.top"
        )
        self.assertEqual(logo.status_code, 200)
        self.assertEqual(
            logo.data,
            (Path(__file__).parents[1] / "app" / "assets" / "logo.png").read_bytes(),
        )
        logo.close()
        self.assertIn("主页", dashboard)
        self.assertIn('class="service-icon"><img src="/static/logo.png"', dashboard)
        self.assertIn("AI 写 Markdown", dashboard)
        self.assertNotIn("AI 管理", dashboard)
        self.assertNotIn("注册机器</h2>", dashboard)

        markdown = self._markdownPage()
        self.assertEqual(markdown.status_code, 200)
        content = markdown.get_data(as_text=True)
        self.assertIn("运行情况", content)
        self.assertNotIn('name="system_prompt"', content)
        self.assertNotIn("<table", content)

        settings = self._settingsPage()
        self.assertEqual(settings.status_code, 200)
        content = settings.get_data(as_text=True)
        self.assertIn("请求与计费", content)
        self.assertIn('name="daily_limit"', content)
        self.assertNotIn('name="system_prompt"', content)

        prompt = self._promptPage()
        self.assertEqual(prompt.status_code, 200)
        content = prompt.get_data(as_text=True)
        self.assertIn("提示词", content)
        self.assertIn('name="system_prompt"', content)
        self.assertIn(escape(ai_markdown.SYSTEM_PROMPT), content)

        machines = self._machinesPage()
        self.assertEqual(machines.status_code, 200)
        content = machines.get_data(as_text=True)
        self.assertIn("注册机器", content)
        self.assertIn("<table", content)
        self.assertNotIn('name="system_prompt"', content)

    def testDashboardStatsRefreshWhileThePageIsVisible(self):
        dashboard = self._login().get_data(as_text=True)

        self.assertNotIn("每天 00:00 刷新", dashboard)
        self.assertNotIn("refresh-note", dashboard)
        self.assertIn(
            'data-dashboard-stats-url="/admin/dashboard/stats"',
            dashboard,
        )
        self.assertIn('data-stat="today.ai_requests"', dashboard)
        self.assertIn('data-stat="processing"', dashboard)
        self.assertIn('data-stat="consumed"', dashboard)
        self.assertIn('data-stat="market.downloads"', dashboard)

        response = self.client.get(
            "/admin/dashboard/stats",
            base_url="https://dash.djcatpro.top",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("today", response.json)
        self.assertIn("all", response.json)
        self.assertIn("market", response.json)

    def testDashboardStatsScanRequestHistoryOnlyTwice(self):
        statements = []
        originalConnect = ai_markdown._connect

        def connect():
            database = originalConnect()
            database.set_trace_callback(statements.append)
            return database

        with patch.object(ai_markdown, "_connect", connect):
            ai_markdown._dashboardStats()

        requestQueries = [
            statement
            for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
            and "FROM request_log" in statement
        ]
        self.assertEqual(len(requestQueries), 2)

    def testMachineRegistrationReturnsStableShortCode(self):
        first = self.client.post(
            "/ai/markdown/register", json={"machine_id": "a" * 64}
        )
        second = self.client.post(
            "/ai/markdown/register", json={"machine_id": "a" * 64}
        )
        third = self.client.post(
            "/ai/markdown/register", json={"machine_id": "b" * 64}
        )

        self.assertEqual(first.get_json()["machine_code"], "DJ-000001")
        self.assertEqual(second.get_json()["machine_code"], "DJ-000001")
        self.assertEqual(third.get_json()["machine_code"], "DJ-000002")

    def testAdminUpdatesEncryptedAISettings(self):
        self._login()
        settings = self._settingsPage()
        response = self.client.post(
            "/admin/ai/markdown/settings",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(settings),
                "daily_limit": "20",
                "model": "deepseek-v4-flash-test",
                "api_key": "sk-panel-test",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ai_markdown._dailyLimit(), 20)
        self.assertEqual(ai_markdown._deepseekModel(), "deepseek-v4-flash-test")
        self.assertEqual(ai_markdown._deepseekApiKey(), "sk-panel-test")
        prompt = self._promptPage()
        response = self.client.post(
            "/admin/ai/markdown/prompt",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(prompt),
                "system_prompt": "管理员设置的全局提示词",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        home = self.client.get("/admin/", base_url="https://dash.djcatpro.top")
        self.assertIn("API 已配置", home.get_data(as_text=True))
        self.assertEqual(
            ai_markdown._systemPrompt("用户微调"),
            "管理员设置的全局提示词"
            f"{ai_markdown.CUSTOM_STYLE_PREFIX}用户微调",
        )
        self.assertEqual(
            ai_markdown._quotaCost(
                datetime(2026, 8, 1, 10, tzinfo=ai_markdown.TIMEZONE)
            ),
            1,
        )
        quota = self.client.get(
            "/ai/markdown/quota", query_string={"machine_id": "a" * 64}
        ).get_json()
        self.assertFalse(quota["peak_enabled"])
        self.assertEqual(quota["cost"], 1)
        overview = self._markdownPage().get_data(as_text=True)
        self.assertNotIn("高峰双倍扣除", overview)
        self.assertNotIn("高峰时段", overview)
        with closing(ai_markdown._connect()) as database:
            encrypted = database.execute(
                "SELECT value FROM settings WHERE key = 'deepseek_api_key'"
            ).fetchone()[0]
        self.assertNotIn("sk-panel-test", encrypted)

    def testAdminWriteRoutesSupportAjaxResponses(self):
        self._login()
        headers = {
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        settings = self._settingsPage()
        response = self.client.post(
            "/admin/ai/markdown/settings",
            base_url="https://dash.djcatpro.top",
            headers=headers,
            data={
                "csrf_token": self._csrf(settings),
                "daily_limit": "18",
                "model": "deepseek-v4-flash",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["category"], "success")
        self.assertNotIn("Location", response.headers)

        prompt = self._promptPage()
        response = self.client.post(
            "/admin/ai/markdown/prompt",
            base_url="https://dash.djcatpro.top",
            headers=headers,
            data={
                "csrf_token": self._csrf(prompt),
                "system_prompt": "管理员异步保存的提示词",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["category"], "success")

        registered = self.client.post(
            "/ai/markdown/register", json={"machine_id": "a" * 64}
        ).get_json()
        machines = self._machinesPage()
        response = self.client.post(
            f"/admin/ai/markdown/machines/{registered['machine_code']}/reset",
            base_url="https://dash.djcatpro.top",
            headers=headers,
            data={"csrf_token": self._csrf(machines)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["category"], "success")

        response = self.client.post(
            "/admin/ai/markdown/reset-all",
            base_url="https://dash.djcatpro.top",
            headers=headers,
            data={"csrf_token": self._csrf(machines)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["category"], "success")

    def testInvalidEncryptionKeyDoesNotPartiallySaveSettings(self):
        self._login()
        settings = self._settingsPage()
        with patch.dict(os.environ, {"DJCATAI_SETTINGS_KEY": "invalid"}):
            response = self.client.post(
                "/admin/ai/markdown/settings",
                base_url="https://dash.djcatpro.top",
                data={
                    "csrf_token": self._csrf(settings),
                    "daily_limit": "20",
                    "model": "changed-model",
                    "api_key": "sk-will-not-save",
                },
                follow_redirects=True,
            )

        self.assertIn("格式无效", response.get_data(as_text=True))
        self.assertEqual(ai_markdown._dailyLimit(), 15)
        self.assertEqual(ai_markdown._deepseekModel(), "deepseek-v4-flash")

    def testAdminRejectsOversizedSystemPrompt(self):
        self._login()
        prompt = self._promptPage()
        response = self.client.post(
            "/admin/ai/markdown/prompt",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(prompt),
                "system_prompt": "x" * (ai_markdown.MAX_SYSTEM_PROMPT_LENGTH + 1),
            },
            follow_redirects=True,
        )

        self.assertIn("系统提示词不能超过", response.get_data(as_text=True))
        self.assertEqual(ai_markdown._setting("system_prompt"), None)

    def testAdminSearchSortAndQuotaReset(self):
        self.client.post("/ai/markdown/register", json={"machine_id": "b" * 64})
        self.client.post("/ai/markdown/register", json={"machine_id": "a" * 64})
        machineId = ai_markdown._machineId("a" * 64)
        ai_markdown._claim(machineId, 2)
        dashboard = self._login()

        search = self._machinesPage("?q=DJ-000002&sort=code").get_data(as_text=True)
        self.assertIn("DJ-000002", search)
        self.assertNotIn("DJ-000001", search)
        machines = self._machinesPage().get_data(as_text=True)
        self.assertGreaterEqual(machines.count("data-confirm="), 2)

        reset = self.client.post(
            "/admin/ai/markdown/machines/DJ-000002/reset",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(dashboard)},
            follow_redirects=True,
        )
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(ai_markdown._remaining(machineId), 15)

        ai_markdown._claim(machineId, 1)
        self.client.post(
            "/admin/ai/markdown/reset-all",
            base_url="https://dash.djcatpro.top",
            data={"csrf_token": self._csrf(reset)},
        )
        self.assertEqual(ai_markdown._remaining(machineId), 15)

    def testAdminRequiresLoginAndCsrf(self):
        response = self.client.get(
            "/admin/login", base_url="https://api.djcatpro.top"
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.get(
            "/admin/", base_url="https://dash.djcatpro.top"
        )
        self.assertEqual(response.status_code, 302)

        self._login()
        response = self.client.post(
            "/admin/ai/markdown/reset-all", base_url="https://dash.djcatpro.top"
        )
        self.assertEqual(response.status_code, 400)

    def testAdminFeedbackUsesToastAndPageMotion(self):
        self._login()
        settings = self._settingsPage()
        response = self.client.post(
            "/admin/ai/markdown/settings",
            base_url="https://dash.djcatpro.top",
            data={
                "csrf_token": self._csrf(settings),
                "daily_limit": "0",
                "model": "deepseek-v4-flash",
            },
            follow_redirects=True,
        )
        content = response.get_data(as_text=True)
        self.assertIn('class="toast-region"', content)
        self.assertIn("每日额度必须在 1 到 10000 之间", content)
        self.assertNotIn('<main class="page-main">\n                <div class="notice', content)

        cssResponse = self.client.get(
            "/static/admin.css", base_url="https://dash.djcatpro.top"
        )
        css = cssResponse.get_data(as_text=True)
        cssResponse.close()
        self.assertIn("@view-transition", css)
        self.assertIn("::view-transition-new(admin-workspace)", css)
        self.assertIn("::view-transition-group(sidebar-active)", css)
        self.assertIn("view-transition-name: sidebar-active", css)
        self.assertIn("admin-topbar", css)
        self.assertIn(".service-card + .service-card { margin-top: 16px; }", css)
        self.assertNotIn(".market-page { animation:", css)
        self.assertIn("toast-progress", css)
        self.assertIn("toast-progress 10s", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn("button:active:not(:disabled)", css)
        self.assertIn(".button-danger:hover", css)
        self.assertIn("background: var(--danger); color: #fff", css)

        javascriptResponse = self.client.get(
            "/static/admin.js", base_url="https://dash.djcatpro.top"
        )
        javascript = javascriptResponse.get_data(as_text=True)
        javascriptResponse.close()
        self.assertIn("[data-toast]", javascript)
        self.assertIn("data-sidebar-toggle", content)
        self.assertIn("data-sidebar-close", content)
        self.assertIn("sidebar-open", css)
        self.assertIn("translateX(-105%)", css)
        self.assertIn("Escape", javascript)
        self.assertIn("form[data-confirm]", javascript)
        self.assertIn("form.requestSubmit", javascript)
        self.assertIn("form[data-async-form]", javascript)
        self.assertIn("[data-dashboard-stats-url]", javascript)
        self.assertIn("visibilitychange", javascript)
        self.assertIn("10_000", javascript)
        self.assertIn("if (refreshStarted) refreshStats();", javascript)
        self.assertIn(".table-action { min-height: 40px;", css)
        self.assertIn(".order-controls button { width: 40px; height: 40px;", css)
        self.assertIn(".sidebar-toggle { width: 40px; height: 40px;", css)
        self.assertIn("@media (hover: none), (pointer: coarse)", css)
        self.assertIn(
            'if (form.dataset.confirm && form.dataset.confirmed !== "true") return;',
            javascript,
        )
        self.assertNotIn("submitter.dataset.confirmed", javascript)
        self.assertNotIn("button.dataset.confirmed", javascript)
        self.assertIn("X-Requested-With", javascript)
