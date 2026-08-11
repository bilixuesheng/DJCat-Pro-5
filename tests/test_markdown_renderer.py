import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PySide6.QtGui import QImage, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScroller, QWidget

from app.view.components.markdown_view import MarkdownView
from app.view.pages.broadcast_page import BroadcastWindow
from app.view.windows.main_window import UpdateDialog
from pyqt_github_markdown.blocks import BlockQuote, CodeBlock, ListBlock, TableBlock
from pyqt_github_markdown.blocks.image_block import ImagePlaceholder
from pyqt_github_markdown.markdown_service import markdownService
from pyqt_github_markdown.renderer import markdownRenderer
from pyqt_github_markdown.theme import LIGHT


class _ImageHandler(BaseHTTPRequestHandler):
    payload = b""

    def do_GET(self):
        if self.path != "/image.png":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *_):
        pass


def _pngBytes() -> bytes:
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


class MarkdownRendererTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        _ImageHandler.payload = _pngBytes()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _ImageHandler)
        cls.serverThread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.serverThread.start()
        cls.imageUrl = f"http://127.0.0.1:{cls.server.server_port}/image.png"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.serverThread.join(timeout=2)

    def _waitFor(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QTest.qWait(10)
        self.fail("timed out waiting for Qt event")

    @staticmethod
    def _render(text):
        return markdownRenderer.buildDocument(markdownService.toTree(text), LIGHT)

    def testRendererSupportsAlertsListsTablesAndCodeCopy(self):
        alert = self._render("> [!WARNING]\n> 注意\n")[0]
        taskList = self._render("- [x] 完成\n- [ ] 待办")[0]
        table = self._render("| A | B |\n|---|---|\n| 1 | 2 |")[0]
        code = self._render("```python\nprint(1)\n```")[0]

        self.assertIsInstance(alert, BlockQuote)
        self.assertEqual(alert.property("kind"), "warning")
        self.assertIsInstance(taskList, ListBlock)
        self.assertIsInstance(table, TableBlock)
        self.assertIsInstance(code, CodeBlock)
        code.onCopyClicked()
        self.assertEqual(QApplication.clipboard().text(), "print(1)\n")

    def testRendererEscapesRawHtmlAndRendersInlineLinks(self):
        html = self._render("<script>alert(1)</script>")[0]
        link = self._render("[链接](https://example.com)")[0]

        self.assertIn("&lt;script&gt;", html.text())
        self.assertIn('href="https://example.com"', link.text())

    def testMarkdownViewRendersGfmAndEnablesTouchScrolling(self):
        view = MarkdownView()
        view.setMarkdown(
            "# 标题\n\n- [x] 完成\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint(1)\n```\n\n"
            + "\n\n".join(f"段落 {index}" for index in range(20))
        )

        self.assertEqual(
            QScroller.hasScroller(view.viewport()),
            True,
        )
        self.assertTrue(any(label.objectName() == "h1" for label in view.findChildren(QLabel)))

        view.resize(320, 180)
        view.show()
        self.app.processEvents()
        scrollBar = view._scroll.verticalScrollBar()
        self.assertGreater(scrollBar.maximum(), 0)
        touchDevice = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        QTest.touchEvent(view.viewport(), touchDevice).press(
            0,
            QPoint(160, 150),
            view.viewport(),
        ).commit()
        QTest.touchEvent(view.viewport(), touchDevice).move(
            0,
            QPoint(160, 20),
            view.viewport(),
        ).commit()
        QTest.qWait(250)
        QTest.touchEvent(view.viewport(), touchDevice).release(
            0,
            QPoint(160, 20),
            view.viewport(),
        ).commit()
        self.assertGreater(scrollBar.value(), 0)
        view.deleteLater()

    def testLinksOnlyOpenHttpAndHttps(self):
        view = MarkdownView()
        with patch(
            "app.view.components.markdown_view.QDesktopServices.openUrl",
            return_value=True,
        ) as openUrl:
            view._openLink("https://example.com")
            view._openLink("javascript:alert(1)")

        openUrl.assert_called_once()
        self.assertEqual(openUrl.call_args.args[0].scheme(), "https")
        view.deleteLater()

    def testRemoteImageLoadsAsynchronously(self):
        image = ImagePlaceholder("sample", self.imageUrl)
        image.show()
        self._waitFor(
            lambda: (
                image.findChild(QLabel).pixmap() is not None
                and not image.findChild(QLabel).pixmap().isNull()
            )
        )

        pixmap = image.findChild(QLabel).pixmap()
        self.assertFalse(pixmap.isNull())
        self.assertLessEqual(pixmap.width(), 760)
        image.deleteLater()

    def testRemoteImageDecoderRejectsOversizedImages(self):
        image = QImage(8193, 1, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.red)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")

        self.assertIsNone(ImagePlaceholder._decode(bytes(buffer.data())))

    def testBroadcastSwitchesBetweenPlainAndMarkdownViews(self):
        window = BroadcastWindow()
        window.setContent("title", "# markdown", is_markdown=True)
        self.assertTrue(window.contentEdit.isHidden())
        self.assertFalse(window.markdownView.isHidden())
        self.assertEqual(
            QScroller.hasScroller(window.markdownView.viewport()),
            True,
        )

        window.setContent("title", "plain", is_markdown=False)
        self.assertTrue(window.markdownView.isHidden())
        self.assertFalse(window.contentEdit.isHidden())
        window.close()

    def testUpdateDialogUsesTouchScrollableMarkdownView(self):
        parent = QWidget()
        parent.resize(800, 600)
        dialog = UpdateDialog("5.0.1", "# 更新\n\n内容", parent)
        self.assertIsInstance(dialog.markdownView, MarkdownView)
        self.assertEqual(
            QScroller.hasScroller(dialog.markdownView.viewport()),
            True,
        )
        dialog.close()
        parent.close()
