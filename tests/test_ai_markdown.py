import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from app.config.cfg import cfg
from app.view.pages.broadcast_page import (
    AIMarkdownDialog,
    BroadcastEditPage,
    _iterSseContent,
)
from app.view.pages.setting_page import CUSTOM_STYLE_PLACEHOLDER, SettingPage
from server import ai_markdown


class AIMarkdownTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
        self.assertNotEqual(firstStyle, dialog.inputEdit.styleSheet())
        dialog._stopBusyStyle()
        self.assertIn("border-radius", dialog.inputEdit.styleSheet())

        dialog._onQuotaReceived(8, 15, 2)
        self.assertIn("每天 0 点刷新", dialog.quotaLabel.text())
        self.assertIn("9:00–12:00、14:00–18:00", dialog.quotaLabel.text())
        self.assertIn("当前每次扣 2 次", dialog.quotaLabel.text())
        self.assertIn("设置", dialog.quotaLabel.text())
        dialog.inputEdit.setPlainText("作业")
        dialog._remaining = None
        dialog._refreshStartButton()
        self.assertFalse(dialog.yesButton.isEnabled())

        parent.resize(760, 500)
        self.app.processEvents()
        self.assertEqual(dialog.widget.width(), 680)

    def testAIStyleSettings(self):
        oldFile = cfg.file
        oldEnabled = cfg.aiMarkdownCustomStyleEnabled.value
        oldStyle = cfg.aiMarkdownCustomStyle.value
        with tempfile.TemporaryDirectory() as directory:
            cfg.file = Path(directory) / "config.json"
            try:
                cfg.set(cfg.aiMarkdownCustomStyleEnabled, False)
                cfg.set(cfg.aiMarkdownCustomStyle, "")
                with patch.object(SettingPage, "_refreshAIQuota"):
                    page = SettingPage()
                    page.show()
                self.addCleanup(page.close)

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

                page._onAIQuotaReceived(8, 15, 2)
                self.assertEqual(page.aiQuotaLabel.text(), "8 / 15")
                self.assertIn(
                    "9:00–12:00、14:00–18:00",
                    page.aiQuotaCard.contentLabel.text(),
                )
            finally:
                cfg.set(cfg.aiMarkdownCustomStyleEnabled, oldEnabled)
                cfg.set(cfg.aiMarkdownCustomStyle, oldStyle)
                cfg.file = oldFile

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

        self.assertEqual(response.status_code, 200)
        payload = post.call_args.kwargs["json"]
        self.assertTrue(payload["messages"][0]["content"].endswith("只使用列表"))
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(response.headers["X-RateLimit-Cost"], "2")
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "13")

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

        self.assertEqual(response.status_code, 429)
        self.assertIn("非双倍时段", response.get_json()["message"])
        self.assertEqual(response.headers["X-RateLimit-Remaining"], "1")
        self.assertEqual(response.headers["X-RateLimit-Cost"], "2")

    def testPeakQuotaCostAndDailyLimit(self):
        self.assertEqual(
            ai_markdown._quotaCost(
                datetime(2026, 8, 1, 8, 59, tzinfo=ai_markdown.TIMEZONE)
            ),
            1,
        )
        for hour in (9, 11, 14, 17):
            self.assertEqual(
                ai_markdown._quotaCost(
                    datetime(2026, 8, 1, hour, tzinfo=ai_markdown.TIMEZONE)
                ),
                2,
            )
        for hour in (12, 13, 18, 23):
            self.assertEqual(
                ai_markdown._quotaCost(
                    datetime(2026, 8, 1, hour, tzinfo=ai_markdown.TIMEZONE)
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
