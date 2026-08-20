import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScroller, QWidget

from app.common import ai_markdown as client_ai_markdown
from app.config.cfg import cfg
from app.view.pages.broadcast_page import (
    AIMarkdownDialog,
    BroadcastEditPage,
    BroadcastWindow,
    _iterSseContent,
)
from app.view.pages.setting_page import CUSTOM_STYLE_PLACEHOLDER, SettingPage
from app.view.windows.main_window import MachineRegistrationWorker
from server import ai_markdown


class AIMarkdownTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempConfigDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.markdownEnabled = cfg.broadcastMarkdownEnabled.value
        cfg.file = Path(self.tempConfigDir.name) / "config.json"
        cfg.set(cfg.broadcastMarkdownEnabled, False)

    def tearDown(self):
        cfg.set(cfg.broadcastMarkdownEnabled, self.markdownEnabled)
        cfg.file = self.configFile
        self.tempConfigDir.cleanup()

    def testEditorControlsAndStreamParsing(self):
        page = BroadcastEditPage()
        self.addCleanup(page.close)

        self.assertEqual(page.titleInput.height(), 48)
        self.assertFalse(page.aiBtn.isEnabled())
        page.markdownCheckBox.setChecked(True)
        self.assertTrue(page.aiBtn.isEnabled())
        self.assertEqual(
            list(
                _iterSseContent(
                    [
                        'data: {"choices":[{"delta":{"content":"**【语文】**"}}]}',
                        'data: {"choices":[{"delta":{"content":"\\n- 作业"}}]}',
                        'data: {"choices":[{"delta":{"content":""},'
                        '"finish_reason":"stop"}]}',
                        "data: [DONE]",
                    ]
                )
            ),
            ["**【语文】**", "\n- 作业"],
        )

    def testIncompleteStreamIsRejected(self):
        with self.assertRaisesRegex(RuntimeError, "未正常结束"):
            list(
                _iterSseContent(
                    ['data: {"choices":[{"delta":{"content":"半截内容"}}]}']
                )
            )

        with self.assertRaisesRegex(RuntimeError, "输出过长"):
            list(
                _iterSseContent(
                    [
                        'data: {"choices":[{"delta":{"content":""},'
                        '"finish_reason":"length"}]}'
                    ]
                )
            )

        with self.assertRaisesRegex(RuntimeError, "未正常完成"):
            list(
                _iterSseContent(
                    [
                        'data: {"choices":[{"delta":{"content":""},'
                        '"finish_reason":"content_filter"}]}',
                        "data: [DONE]",
                    ]
                )
            )

    def testAIDialogFitsSmallWindowAndUsesGradientBorder(self):
        parent = QWidget()
        parent.resize(500, 400)
        parent.show()
        self.addCleanup(parent.close)

        with patch.object(AIMarkdownDialog, "_fetchQuota"):
            dialog = AIMarkdownDialog("", parent)
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()

        self.assertTrue(dialog._quotaTimer.isActive())
        self.assertEqual(dialog._quotaTimer.interval(), 30_000)
        self.assertNotIn("高峰", dialog.quotaLabel.text())
        self.assertTrue(dialog.rect().contains(dialog.widget.geometry()))
        inputBottom = dialog.inputEdit.mapTo(
            dialog.widget, dialog.inputEdit.rect().bottomLeft()
        ).y()
        quotaTop = dialog.quotaLabel.mapTo(
            dialog.widget, dialog.quotaLabel.rect().topLeft()
        ).y()
        self.assertLess(inputBottom, quotaTop)

        dialog._updateBusyStyle()
        firstStyle = dialog.inputEdit.styleSheet()
        dialog._updateBusyStyle()
        self.assertIn("qlineargradient", firstStyle)
        self.assertIn("border: 2px solid", firstStyle)
        self.assertNotEqual(firstStyle, dialog.inputEdit.styleSheet())
        dialog._stopBusyStyle()
        self.assertIn("border-radius", dialog.inputEdit.styleSheet())

        dialog._onQuotaReceived(8, 15, 2, True, "DJ-000123")
        self.assertIn("每天 0 点刷新", dialog.quotaLabel.text())
        self.assertIn("9:00–12:00、14:00–18:00", dialog.quotaLabel.text())
        self.assertIn("当前每次扣 2 点", dialog.quotaLabel.text())
        self.assertIn("设置", dialog.quotaLabel.text())
        dialog._onQuotaReceived(-1, 15, 1, None, "")
        self.assertIn("暂时无法获取", dialog.quotaLabel.text())
        self.assertNotIn("高峰", dialog.quotaLabel.text())
        dialog.inputEdit.setPlainText("作业")
        dialog._remaining = None
        dialog._refreshStartButton()
        self.assertFalse(dialog.yesButton.isEnabled())

        parent.resize(760, 500)
        self.app.processEvents()
        self.assertEqual(dialog.widget.width(), 680)

    def testAIDialogCanCancelAnActiveStreamAndBatchesChunks(self):
        parent = QWidget()
        self.addCleanup(parent.close)
        with patch.object(AIMarkdownDialog, "_fetchQuota"):
            dialog = AIMarkdownDialog("原内容", parent)
        self.addCleanup(dialog.close)
        response = MagicMock()
        dialog._running = True
        dialog._activeResponse = response

        dialog.reject()

        self.assertTrue(dialog._cancelEvent.is_set())
        self.assertFalse(dialog._running)
        response.close.assert_called_once()

        with patch.object(AIMarkdownDialog, "_fetchQuota"):
            batchingDialog = AIMarkdownDialog("", parent)
        self.addCleanup(batchingDialog.close)
        batchingDialog.inputEdit.clear()
        for chunk in ("第一段", "第二段", "第三段"):
            batchingDialog._appendChunk(chunk)
        self.assertTrue(batchingDialog._flushTimer.isActive())
        self.assertEqual(batchingDialog.inputEdit.toPlainText(), "")

        batchingDialog._flushTimer.stop()
        batchingDialog._flushChunks()

        self.assertEqual(batchingDialog.resultText(), "第一段第二段第三段")
        self.assertEqual(
            batchingDialog.inputEdit.toPlainText(), "第一段第二段第三段"
        )

    def testFailedStreamDiscardsChunksThatHaveNotBeenPainted(self):
        parent = QWidget()
        self.addCleanup(parent.close)
        with patch.object(AIMarkdownDialog, "_fetchQuota"):
            dialog = AIMarkdownDialog("原内容", parent)
        self.addCleanup(dialog.close)
        dialog.inputEdit.clear()
        dialog._appendChunk("不完整结果")

        with (
            patch.object(dialog, "_refreshQuota"),
            patch("app.view.pages.broadcast_page.MessageBox") as messageBox,
        ):
            dialog._onConversionFailed("流式响应中断", 10, 15, 1)

        dialog._flushChunks()
        self.assertFalse(dialog._flushTimer.isActive())
        self.assertEqual(dialog.inputEdit.toPlainText(), "原内容")
        self.assertEqual(dialog.resultText(), "")
        messageBox.return_value.exec.assert_called_once_with()

    def testLongTextAreasSupportNativeTouchScrolling(self):
        page = BroadcastEditPage()
        window = BroadcastWindow()
        parent = QWidget()
        self.addCleanup(page.close)
        self.addCleanup(window.close)
        self.addCleanup(parent.close)
        with patch.object(AIMarkdownDialog, "_fetchQuota"):
            dialog = AIMarkdownDialog("", parent)
        self.addCleanup(dialog.close)

        for viewport in (
            page.contentInput.viewport(),
            window.contentEdit.viewport(),
            dialog.inputEdit.viewport(),
        ):
            self.assertTrue(QScroller.hasScroller(viewport))

    def testAIStyleSettings(self):
        oldFile = cfg.file
        oldEnabled = cfg.aiMarkdownCustomStyleEnabled.value
        oldStyle = cfg.aiMarkdownCustomStyle.value
        oldMachineCode = cfg.aiMarkdownMachineCode.value
        with tempfile.TemporaryDirectory() as directory:
            cfg.file = Path(directory) / "config.json"
            try:
                cfg.set(cfg.aiMarkdownCustomStyleEnabled, False)
                cfg.set(cfg.aiMarkdownCustomStyle, "")
                cfg.set(cfg.aiMarkdownMachineCode, "DJ-000123")
                with patch.object(SettingPage, "_refreshAIQuota"):
                    page = SettingPage()
                    page.show()
                self.addCleanup(page.close)
                self.assertNotIn("高峰", page.aiQuotaCard.contentLabel.text())

                self.assertEqual(
                    page.aiStyleCard.textEdit.placeholderText(),
                    CUSTOM_STYLE_PLACEHOLDER,
                )
                self.assertEqual(page.aiStyleCard.view.maximumHeight(), 0)
                page.aiStyleCard.switchButton.setChecked(True)
                QTest.qWait(250)
                self.assertTrue(cfg.aiMarkdownCustomStyleEnabled.value)
                self.assertGreater(page.aiStyleCard.view.maximumHeight(), 0)

                page.aiStyleCard.textEdit.setPlainText("只使用列表")
                page.hide()
                self.app.processEvents()
                self.assertEqual(cfg.aiMarkdownCustomStyle.value, "只使用列表")

                page.aiStyleCard.textEdit.setPlainText("a" * 4001)
                self.assertEqual(
                    len(page.aiStyleCard.textEdit.toPlainText()),
                    4000,
                )
                self.assertIn("已截去", page.aiStyleCard.limitLabel.text())
                page.aiStyleCard.flushPendingSave()
                self.assertEqual(len(cfg.aiMarkdownCustomStyle.value), 4000)

                page._onAIQuotaReceived(8, 15, 2, True, "DJ-000124")
                self.assertEqual(page.aiQuotaLabel.text(), "8 / 15")
                self.assertEqual(page.aiMachineCodeLabel.text(), "DJ-000124")
                self.assertEqual(cfg.aiMarkdownMachineCode.value, "DJ-000124")
                self.assertIn(
                    "9:00–12:00、14:00–18:00",
                    page.aiQuotaCard.contentLabel.text(),
                )
                page._onAIQuotaReceived(8, 15, 1, False, "")
                self.assertNotIn("高峰", page.aiQuotaCard.contentLabel.text())
                page._onAIQuotaReceived(-1, -1, 1, None, "")
                self.assertNotIn("高峰", page.aiQuotaCard.contentLabel.text())
            finally:
                cfg.set(cfg.aiMarkdownCustomStyleEnabled, oldEnabled)
                cfg.set(cfg.aiMarkdownCustomStyle, oldStyle)
                cfg.set(cfg.aiMarkdownMachineCode, oldMachineCode)
                cfg.file = oldFile

    def testClientRegistersMachineOnFirstStartup(self):
        response = MagicMock()
        response.json.return_value = {"machine_code": "DJ-000321"}
        with patch.object(
            client_ai_markdown.requests,
            "post",
            return_value=response,
        ) as post:
            self.assertEqual(client_ai_markdown.registerMachine(), "DJ-000321")
        self.assertTrue(post.call_args.args[0].endswith("/register"))
        self.assertEqual(len(post.call_args.kwargs["json"]["machine_id"]), 64)

        response.json.return_value = {
            "remaining": 9,
            "limit": 15,
            "cost": 1,
            "peak_enabled": False,
            "machine_code": "DJ-000321",
        }
        with patch.object(client_ai_markdown.requests, "get", return_value=response):
            self.assertEqual(
                client_ai_markdown.fetchQuota(),
                (9, 15, 1, False, "DJ-000321"),
            )

        codes = []
        worker = MachineRegistrationWorker()
        worker.finished.connect(codes.append)
        with patch(
            "app.view.windows.main_window.registerMachine",
            return_value="DJ-000321",
        ):
            worker.run()
        self.assertEqual(codes, ["DJ-000321"])

    def testCustomStylePrompt(self):
        self.assertIn("英语中午做97页，值日", ai_markdown.SYSTEM_PROMPT)
        self.assertIn(
            "当遇到任务一部分是正常的任务，一部分是其他的警告比如要值日，"
            "必须要像下面的示例一样用---分开",
            ai_markdown.SYSTEM_PROMPT,
        )
        self.assertEqual(ai_markdown._systemPrompt(""), ai_markdown.SYSTEM_PROMPT)

        customStyle = "所有提醒都放在最后"
        prompt = ai_markdown._systemPrompt(customStyle)
        self.assertIn("以上为系统默认提示词", prompt)
        self.assertTrue(prompt.endswith(customStyle))

    def testClientSendsEnabledCustomStyle(self):
        parent = QWidget()
        parent.resize(760, 500)
        self.addCleanup(parent.close)
        with patch.object(AIMarkdownDialog, "_fetchQuota"):
            dialog = AIMarkdownDialog("原内容", parent)
        self.addCleanup(dialog.close)

        response = MagicMock()
        response.__enter__.return_value = response
        response.headers = {}
        response.ok = True
        response.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"结果"}}]}',
            'data: {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]

        oldFile = cfg.file
        oldEnabled = cfg.aiMarkdownCustomStyleEnabled.value
        oldStyle = cfg.aiMarkdownCustomStyle.value
        with tempfile.TemporaryDirectory() as directory:
            cfg.file = Path(directory) / "config.json"
            try:
                cfg.set(cfg.aiMarkdownCustomStyleEnabled, True)
                cfg.set(cfg.aiMarkdownCustomStyle, "只使用列表")
                dialog._source = "原内容"
                with patch(
                    "app.view.pages.broadcast_page.requests.post",
                    return_value=response,
                ) as post:
                    dialog._streamConversion()
                self.assertEqual(
                    post.call_args.kwargs["json"]["custom_style"],
                    "只使用列表",
                )

                cfg.set(cfg.aiMarkdownCustomStyleEnabled, False)
                dialog._result = ""
                dialog._finished = False
                with patch(
                    "app.view.pages.broadcast_page.requests.post",
                    return_value=response,
                ) as post:
                    dialog._streamConversion()
                self.assertNotIn("custom_style", post.call_args.kwargs["json"])
            finally:
                cfg.set(cfg.aiMarkdownCustomStyleEnabled, oldEnabled)
                cfg.set(cfg.aiMarkdownCustomStyle, oldStyle)
                cfg.file = oldFile

    def testServerRejectsOversizedCustomStyle(self):
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-only",
                "DJCATAI_RATE_LIMIT_SALT": "test-only",
            },
        ):
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={
                    "content": "作业",
                    "machine_id": "a" * 64,
                    "custom_style": "x"
                    * (ai_markdown.MAX_CUSTOM_STYLE_LENGTH + 1),
                },
            )
        self.assertEqual(response.status_code, 400)

    def testServerRejectsOversizedRequestBodyBeforeParsing(self):
        response = ai_markdown.app.test_client().post(
            "/ai/markdown",
            data=(b"{" + b"x" * (ai_markdown.MAX_REQUEST_BYTES + 1) + b"}"),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.get_json()["message"], "请求内容过大")

    def testQuotaLookupDoesNotRegisterUnknownMachine(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {"DJCATAI_RATE_LIMIT_SALT": "test-only"},
            ),
        ):
            response = ai_markdown.app.test_client().get(
                "/ai/markdown/quota",
                query_string={"machine_id": "a" * 64},
            )
            with closing(ai_markdown._connect()) as database:
                machines = database.execute(
                    "SELECT COUNT(*) FROM machines"
                ).fetchone()[0]

        self.assertEqual(response.status_code, 404)
        self.assertEqual(machines, 0)

    def testServerForwardsCustomStyle(self):
        upstream = MagicMock()
        upstream.iter_lines.return_value = [b"data:[DONE]"]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "test-only",
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                },
            ),
            patch.object(
                ai_markdown.requests,
                "post",
                return_value=upstream,
            ) as post,
            patch.object(ai_markdown, "_quotaCost", return_value=2),
        ):
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={
                    "content": "作业",
                    "machine_id": "a" * 64,
                    "custom_style": "只使用列表",
                },
                buffered=True,
            )
            stats = ai_markdown._dashboardStats()

        self.assertEqual(response.status_code, 200)
        payload = post.call_args.kwargs["json"]
        self.assertTrue(payload["messages"][0]["content"].endswith("只使用列表"))
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(response.headers["X-RateLimit-Cost"], "2")
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "13")
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["success"], 1)
        self.assertEqual(stats["consumed"], 2)

    def testIncompleteUpstreamStreamRefundsPeakCost(self):
        upstream = MagicMock()
        upstream.iter_lines.return_value = [b'data: {"choices":[]}']
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "test-only",
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                },
            ),
            patch.object(ai_markdown, "_quotaCost", return_value=2),
            patch.object(ai_markdown.requests, "post", return_value=upstream),
        ):
            machineId = ai_markdown._machineId("a" * 64)
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={"content": "作业", "machine_id": "a" * 64},
                buffered=True,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(ai_markdown._remaining(machineId), 15)
            stats = ai_markdown._dashboardStats()
            self.assertEqual(stats["failed"], 1)
            self.assertEqual(stats["consumed"], 0)

    def testRejectedUpstreamResponseIsClosedEvenWhenFalsy(self):
        upstream = MagicMock()
        upstream.__bool__.return_value = False
        upstream.raise_for_status.side_effect = ai_markdown.requests.HTTPError()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "test-only",
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                },
            ),
            patch.object(ai_markdown.requests, "post", return_value=upstream),
        ):
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={"content": "作业", "machine_id": "a" * 64},
            )

        self.assertEqual(response.status_code, 502)
        upstream.close.assert_called_once_with()

    def testUpstreamSerializationFailureRefundsClaimedQuota(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "test-only",
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                },
            ),
            patch.object(
                ai_markdown.requests,
                "post",
                side_effect=ValueError("cannot serialize"),
            ),
        ):
            machineId = ai_markdown._machineId("a" * 64)
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={"content": "作业", "machine_id": "a" * 64},
            )
            remaining = ai_markdown._remaining(machineId)

        self.assertEqual(response.status_code, 502)
        self.assertEqual(remaining, 15)

    def testStaleProcessingRequestIsFailedAndRefunded(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {"DJCATAI_RATE_LIMIT_SALT": "test-only"},
            ),
        ):
            machineId = ai_markdown._machineId("a" * 64)
            day = ai_markdown._today()
            oldTime = (
                datetime.now(ai_markdown.TIMEZONE) - timedelta(hours=1)
            ).isoformat(timespec="seconds")
            with closing(ai_markdown._connect()) as database:
                database.execute(
                    "INSERT INTO usage(day, machine_id, count) VALUES (?, ?, 2)",
                    (day, machineId),
                )
                database.execute(
                    """
                    INSERT INTO request_log(
                        day, machine_id, requested_at, cost, status
                    ) VALUES (?, ?, ?, 2, 'processing')
                    """,
                    (day, machineId, oldTime),
                )
                database.commit()

            stats = ai_markdown._dashboardStats()

            self.assertEqual(ai_markdown._remaining(machineId), 15)
            self.assertEqual(stats["processing"], 0)
            self.assertEqual(stats["failed"], 1)

    def testRecoveredRequestCannotBeSettledOrRefundedTwice(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {"DJCATAI_RATE_LIMIT_SALT": "test-only"},
            ),
        ):
            machineId = ai_markdown._machineId("b" * 64)
            day = ai_markdown._today()
            oldTime = (
                datetime.now(ai_markdown.TIMEZONE) - timedelta(hours=1)
            ).isoformat(timespec="seconds")
            with closing(ai_markdown._connect()) as database:
                database.execute(
                    "INSERT INTO usage(day, machine_id, count) VALUES (?, ?, 2)",
                    (day, machineId),
                )
                requestId = database.execute(
                    """
                    INSERT INTO request_log(
                        day, machine_id, requested_at, cost, status
                    ) VALUES (?, ?, ?, 2, 'processing')
                    """,
                    (day, machineId, oldTime),
                ).lastrowid
                database.commit()

            ai_markdown._recoverStaleRequests()
            with closing(ai_markdown._connect()) as database:
                database.execute(
                    "UPDATE usage SET count = 2 WHERE day = ? AND machine_id = ?",
                    (day, machineId),
                )
                database.commit()

            ai_markdown._requestFinished(
                requestId,
                False,
                machineId,
                2,
                day,
            )

            self.assertEqual(ai_markdown._remaining(machineId, day, 15), 13)

    def testOldRequestLogsAreRolledUpOnceWithoutLosingStatistics(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
        ):
            machineId = "machine-one"
            oldDay = (
                datetime.now(ai_markdown.TIMEZONE).date()
                - timedelta(days=ai_markdown.REQUEST_LOG_RETENTION_DAYS + 1)
            ).isoformat()
            with closing(ai_markdown._connect()) as database:
                database.execute(
                    """
                    INSERT INTO machines(machine_id, registered_at, last_seen_at)
                    VALUES (?, ?, ?)
                    """,
                    (machineId, oldDay, oldDay),
                )
                database.execute(
                    "INSERT INTO usage(day, machine_id, count) VALUES (?, ?, 2)",
                    (oldDay, machineId),
                )
                database.executemany(
                    """
                    INSERT INTO request_log(
                        day, machine_id, requested_at, cost, status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        (oldDay, machineId, oldDay, 2, "success"),
                        (oldDay, machineId, oldDay, 1, "failed"),
                    ],
                )
                database.commit()

            self.assertEqual(ai_markdown._rollupOldRequests(force=True), 1)
            self.assertEqual(ai_markdown._rollupOldRequests(force=True), 0)

            stats = ai_markdown._dashboardStats()
            machines = ai_markdown._machineRows()
            with closing(ai_markdown._connect()) as database:
                remainingLogs = database.execute(
                    "SELECT COUNT(*) FROM request_log WHERE day = ?", (oldDay,)
                ).fetchone()[0]
                remainingUsage = database.execute(
                    "SELECT COUNT(*) FROM usage WHERE day = ?", (oldDay,)
                ).fetchone()[0]

            self.assertEqual(remainingLogs, 0)
            self.assertEqual(remainingUsage, 0)
            self.assertEqual(stats["all"]["ai_requests"], 2)
            self.assertEqual(stats["all"]["ai_success"], 1)
            self.assertEqual(stats["all"]["ai_failed"], 1)
            self.assertEqual(stats["all_consumed"], 2)
            self.assertEqual(machines[0]["requests"], 2)

    def testReplacingDatabaseAtSamePathReinitializesSchema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "usage.sqlite3"
            with patch.object(ai_markdown, "DATABASE_PATH", path):
                with closing(ai_markdown._connect()) as database:
                    database.execute("SELECT 1 FROM usage LIMIT 1")

                path.unlink()
                sqlite3.connect(path).close()

                with closing(ai_markdown._connect()) as database:
                    tables = {
                        row[0]
                        for row in database.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }

        self.assertIn("usage", tables)
        self.assertIn("request_log", tables)

    def testRequestLogFailureDoesNotConsumeQuota(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "test-only",
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                },
            ),
        ):
            machineId = ai_markdown._machineId("a" * 64)
            with closing(ai_markdown._connect()) as database:
                database.executescript(
                    """
                    CREATE TRIGGER fail_request_log
                    BEFORE INSERT ON request_log
                    BEGIN
                        SELECT RAISE(ABORT, 'test failure');
                    END;
                    """
                )
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={"content": "作业", "machine_id": "a" * 64},
            )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(ai_markdown._remaining(machineId), 15)

    def testPeakRequestWithOneRemainingWaitsForOffPeak(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "test-only",
                    "DJCATAI_RATE_LIMIT_SALT": "test-only",
                },
            ),
            patch.object(ai_markdown, "_quotaCost", return_value=2),
        ):
            machineId = ai_markdown._machineId("a" * 64)
            for _ in range(14):
                ai_markdown._claim(machineId, 1)
            response = ai_markdown.app.test_client().post(
                "/ai/markdown",
                json={"content": "作业", "machine_id": "a" * 64},
            )
            stats = ai_markdown._dashboardStats()

        self.assertEqual(response.status_code, 429)
        self.assertIn("非双倍时段", response.get_json()["message"])
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "1")
        self.assertEqual(response.headers["X-RateLimit-Cost"], "2")
        self.assertEqual(stats["requests"], 1)
        self.assertEqual(stats["failed"], 1)

    def testPeakQuotaCostAndDailyLimit(self):
        self.assertEqual(
            ai_markdown._quotaCost(
                datetime(2026, 8, 1, 8, 59, tzinfo=ai_markdown.TIMEZONE),
                peakEnabled=True,
            ),
            1,
        )
        for hour in (9, 11, 14, 17):
            self.assertEqual(
                ai_markdown._quotaCost(
                    datetime(2026, 8, 1, hour, tzinfo=ai_markdown.TIMEZONE),
                    peakEnabled=True,
                ),
                2,
            )
        for hour in (12, 13, 18, 23):
            self.assertEqual(
                ai_markdown._quotaCost(
                    datetime(2026, 8, 1, hour, tzinfo=ai_markdown.TIMEZONE),
                    peakEnabled=True,
                ),
                1,
            )

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown,
                "DATABASE_PATH",
                Path(directory) / "usage.sqlite3",
            ),
            patch.dict(
                os.environ,
                {"DJCATAI_RATE_LIMIT_SALT": "test-only"},
            ),
        ):
            machineId = ai_markdown._machineId("a" * 64)
            self.assertEqual(
                [ai_markdown._claim(machineId, 2) for _ in range(7)],
                [13, 11, 9, 7, 5, 3, 1],
            )
            self.assertEqual(ai_markdown._claim(machineId, 2), -1)
            self.assertEqual(ai_markdown._remaining(machineId), 1)
            ai_markdown._refund(machineId, 2)
            self.assertEqual(ai_markdown._remaining(machineId), 3)


if __name__ == "__main__":
    unittest.main()
