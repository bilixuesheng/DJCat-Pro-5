"""Who a failed AI Markdown Conversion is blamed on.

The desktop client cannot see past the DJCat server, so the attribution has to
follow what each layer can actually know: the DJCat server knows how DeepSeek
answered, a reverse proxy answers with HTML when the DJCat server itself is down,
and a request that never got an answer may just as well be the classroom PC's
own network.
"""

import os
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import requests
from PySide6.QtWidgets import QApplication

from app.config.constants import AI_MARKDOWN_API
from app.view.pages import broadcast_page
from server import ai_markdown

DEEPSEEK_OFFLINE = "DeepSeek 服务器已离线"
NOT_OUR_FAULT = "也不是我们的问题"
DJCAT_OFFLINE = "电教猫 Pro 基础服务器已离线"


class ServerAttributionTest(TestCase):
    def _convertWithUpstream(self, **upstreamBehaviour):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(
                ai_markdown, "DATABASE_PATH", Path(directory) / "usage.sqlite3"
            ),
            patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "test-only", "DJCATAI_RATE_LIMIT_SALT": "t"},
            ),
            patch.object(ai_markdown.requests, "post", **upstreamBehaviour),
        ):
            response = ai_markdown.app.test_client().post(
                "/ai/markdown", json={"content": "作业", "machine_id": "a" * 64}
            )
        return response.status_code, response.get_json()["message"]

    def _upstreamStatus(self, status):
        upstream = MagicMock()
        upstream.url = ai_markdown.DEEPSEEK_API
        upstream.history = []
        failed = MagicMock(status_code=status)
        upstream.raise_for_status.side_effect = requests.HTTPError(response=failed)
        return upstream

    def testUnreachableDeepSeekIsBlamedOnDeepSeek(self):
        status, message = self._convertWithUpstream(
            side_effect=requests.ConnectionError("down")
        )
        self.assertEqual(status, 502)
        self.assertIn(DEEPSEEK_OFFLINE, message)

    def testDeepSeekServerErrorIsBlamedOnDeepSeek(self):
        status, message = self._convertWithUpstream(
            return_value=self._upstreamStatus(503)
        )
        self.assertEqual(status, 502)
        self.assertIn(DEEPSEEK_OFFLINE, message)

    def testRejectedKeyOrEmptyBalanceIsNotBlamedOnDeepSeek(self):
        # 401 密钥无效、402 余额不足：DeepSeek 在线，是运营方的问题，
        # 不能告诉老师"也不是我们的问题"。
        for upstreamStatus in (401, 402, 403):
            with self.subTest(upstreamStatus=upstreamStatus):
                status, message = self._convertWithUpstream(
                    return_value=self._upstreamStatus(upstreamStatus)
                )
                self.assertEqual(status, 502)
                self.assertNotIn(DEEPSEEK_OFFLINE, message)
                self.assertNotIn(NOT_OUR_FAULT, message)
                self.assertIn("管理员", message)


class ClientAttributionTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def _run(self, **postBehaviour):
        request = SimpleNamespace(
            _remaining=10,
            _limit=15,
            _cost=1,
            _source="作业",
            _responseLock=threading.Lock(),
            _cancelEvent=threading.Event(),
            _activeResponse=None,
            conversionFinished=MagicMock(),
            conversionFailed=MagicMock(),
        )
        with patch.object(broadcast_page.requests, "post", **postBehaviour):
            broadcast_page._streamAIMarkdown(request, lambda chunk: None)
        request.conversionFailed.emit.assert_called_once()
        return request.conversionFailed.emit.call_args.args[0]

    def _response(self, status, body=None):
        response = MagicMock()
        response.url = AI_MARKDOWN_API
        response.history = []
        response.headers = {}
        response.ok = False
        response.status_code = status
        response.__enter__.return_value = response
        if body is None:
            response.json.side_effect = requests.JSONDecodeError("x", "<html>", 0)
        else:
            response.json.return_value = body
        return response

    def testTheServersOwnMessageIsShownWhenTheServerAnswered(self):
        for status in (502, 503):
            with self.subTest(status=status):
                message = self._run(
                    return_value=self._response(status, {"message": "服务端给的原因"})
                )
                self.assertEqual(message, "服务端给的原因")

    def testAProxyErrorPageMeansTheDJCatServerIsDown(self):
        # 反向代理在 Flask 挂掉时回的是 HTML，不是服务端的 JSON。
        for status in (502, 503, 504):
            with self.subTest(status=status):
                message = self._run(return_value=self._response(status))
                self.assertIn(DJCAT_OFFLINE, message)
                self.assertNotIn(DEEPSEEK_OFFLINE, message)

    def testNoAnswerAtAllPointsAtTheLocalNetworkFirst(self):
        # 连不上可能是服务器挂了，也可能是教室电脑自己没网；不能只说服务器离线。
        message = self._run(side_effect=requests.ConnectionError("no route"))
        self.assertIn("网络", message)
        self.assertNotIn(DEEPSEEK_OFFLINE, message)
