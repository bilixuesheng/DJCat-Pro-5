import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from app.view.pages.broadcast_page import (
    AIMarkdownDialog,
    BroadcastEditPage,
    _iterSseContent,
)
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

        parent.resize(760, 500)
        self.app.processEvents()
        self.assertEqual(dialog.widget.width(), 680)

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
