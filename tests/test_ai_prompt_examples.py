"""Conversion Log review and Prompt Example management on the Admin Console."""

import json
import re
from contextlib import closing
from datetime import datetime, timedelta
from unittest import TestCase
from unittest.mock import patch

import requests
from werkzeug.datastructures import MultiDict

from server import ai_markdown
# 只借夹具：把 AIAdminTest 类本身导进来会让 pytest 在这里再收集一遍它的测试。
from tests import test_ai_admin

BASE_URL = "https://dash.djcatpro.top"


class ConversionLogReviewTest(TestCase):
    setUp = test_ai_admin.AIAdminTest.setUp
    _csrf = test_ai_admin.AIAdminTest._csrf

    def _login(self):
        login = self.client.get("/admin/login", base_url=BASE_URL)
        self.client.post(
            "/admin/login",
            base_url=BASE_URL,
            data={
                "csrf_token": self._csrf(login),
                "username": "admin",
                "password": "secret",
            },
        )
        return self._csrf(self.client.get("/admin/", base_url=BASE_URL))

    def _log(self, text="英语做97页"):
        ai_markdown._saveConversionLog("a" * 64, text, f"- {text}", "")
        with closing(ai_markdown._connect()) as database:
            return database.execute(
                "SELECT MAX(id) FROM conversion_logs"
            ).fetchone()[0]

    def _exampleCount(self):
        return len(ai_markdown._allPromptExamples())

    def _approve(self, csrf, logId, route="approve"):
        return self.client.post(
            f"/admin/ai/markdown/logs/{logId}/{route}",
            base_url=BASE_URL,
            data={
                "csrf_token": csrf,
                "input_content": "英语做97页",
                "output_content": "- 做97页",
            },
        )

    def testApprovingTheSameLogTwiceAddsOneExample(self):
        csrf = self._login()
        logId = self._log()
        before = self._exampleCount()

        # 审批页的「通过并加入」是普通表单，双击或两个标签页会各提交一次。
        self._approve(csrf, logId)
        self._approve(csrf, logId)

        self.assertEqual(self._exampleCount(), before + 1)
        self.assertEqual(ai_markdown._getConversionLog(logId)["status"], "approved")

    def testAddingFromTheListIsAlsoIdempotent(self):
        csrf = self._login()
        logId = self._log()
        before = self._exampleCount()

        self._approve(csrf, logId, route="add")
        self._approve(csrf, logId, route="approve")

        self.assertEqual(self._exampleCount(), before + 1)

    def testARejectedLogCanStillBeApprovedLater(self):
        csrf = self._login()
        logId = self._log()
        before = self._exampleCount()
        self.client.post(
            f"/admin/ai/markdown/logs/{logId}/reject",
            base_url=BASE_URL,
            data={"csrf_token": csrf},
        )

        self._approve(csrf, logId)

        self.assertEqual(self._exampleCount(), before + 1)

    def testOldPendingLogsAreCleanedWithoutOpeningTheLogPage(self):
        ai_markdown._connect().close()
        old = (
            datetime.now(ai_markdown.TIMEZONE)
            - timedelta(days=ai_markdown.CONVERSION_LOG_RETENTION_DAYS + 5)
        ).isoformat(timespec="seconds")
        with closing(ai_markdown._connect()) as database:
            database.execute(
                "INSERT INTO conversion_logs "
                "(machine_id, input_content, output_content, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("a" * 64, "旧输入", "旧输出", old),
            )
            database.commit()

        # 只有新的整理记录写入，没有人打开整理记录页。
        self._log("新输入")

        with closing(ai_markdown._connect()) as database:
            inputs = [
                row[0]
                for row in database.execute(
                    "SELECT input_content FROM conversion_logs"
                ).fetchall()
            ]
        self.assertEqual(inputs, ["新输入"])


class PromptExampleOrderTest(TestCase):
    setUp = test_ai_admin.AIAdminTest.setUp
    _csrf = test_ai_admin.AIAdminTest._csrf
    _login = ConversionLogReviewTest._login

    def _ids(self):
        return [example["id"] for example in ai_markdown._allPromptExamples()]

    def _reorder(self, csrf, order, expected):
        data = [("csrf_token", csrf)]
        data += [("expected_item_id", str(value)) for value in expected]
        data += [("item_id", str(value)) for value in order]
        return self.client.post(
            "/admin/ai/markdown/examples/reorder",
            base_url=BASE_URL,
            data=MultiDict(data),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

    def testReorderAcceptsTheSharedSortableTablePayload(self):
        csrf = self._login()
        ids = self._ids()
        self.assertGreaterEqual(len(ids), 3)

        response = self._reorder(csrf, list(reversed(ids)), ids)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._ids(), list(reversed(ids)))

    def testReorderRejectsAnOrderThatIsNotAPermutation(self):
        csrf = self._login()
        ids = self._ids()

        response = self._reorder(csrf, [ids[0]] * len(ids), ids)

        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(self._ids(), ids)

    def testReorderRejectsAStaleSnapshot(self):
        csrf = self._login()
        ids = self._ids()

        response = self._reorder(csrf, list(reversed(ids)), list(reversed(ids)))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._ids(), ids)

    def testExamplesPageDoesNotPatchWindowFetch(self):
        self._login()
        page = self.client.get(
            "/admin/ai/markdown/examples/", base_url=BASE_URL
        ).get_data(as_text=True)
        # 排序的载荷格式归 admin.js 所有；页面改写全局 fetch 会让所有请求都经过它。
        self.assertNotIn("window.fetch", page)
