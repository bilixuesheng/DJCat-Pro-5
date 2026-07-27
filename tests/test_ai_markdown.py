import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.view.pages.broadcast_page import BroadcastEditPage, _iterSseContent
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
                        "data: [DONE]",
                    ]
                )
            ),
            ["**【语文】**", "\n- 作业"],
        )

    def testDailyLimit(self):
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
                [ai_markdown._claim(machineId) for _ in range(15)],
                list(range(14, -1, -1)),
            )
            self.assertEqual(ai_markdown._claim(machineId), -1)
            ai_markdown._refund(machineId)
            self.assertEqual(ai_markdown._remaining(machineId), 1)


if __name__ == "__main__":
    unittest.main()
