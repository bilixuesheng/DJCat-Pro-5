import os
import socket
import threading
import time
from unittest import TestCase
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PySide6.QtGui import QImage, QInputDevice
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScroller, QTextEdit, QWidget

from app.view.components.markdown_view import MarkdownView
from app.view.pages.broadcast_page import BroadcastWindow
from app.view.windows.main_window import UpdateDialog
from pyqt_github_markdown.blocks import BlockQuote, CodeBlock, ListBlock, TableBlock
from pyqt_github_markdown.blocks import image_block as imageBlockModule
from pyqt_github_markdown.blocks.image_block import ImagePlaceholder
from pyqt_github_markdown.markdown_service import markdownService
from pyqt_github_markdown.renderer import markdownRenderer
from pyqt_github_markdown.theme import DARK, LIGHT


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

    def testThemeUsesReadableAlertStripWidth(self):
        for theme in (LIGHT, DARK):
            self.assertIn("border-left: 6px solid", theme.qss)

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

    def testRepeatedMarkdownRendersDetachReplacedWidgetsImmediately(self):
        view = MarkdownView()
        self.addCleanup(view.deleteLater)
        view.setMarkdown("[旧链接](https://old.example)")
        previous = view._content.findChild(QLabel)

        view.setMarkdown("[新链接](https://new.example)")

        labels = view._content.findChildren(QLabel)
        self.assertIsNone(previous.parent())
        self.assertEqual(len(labels), 1)
        self.assertIn("new.example", labels[0].text())

    def testUnchangedMarkdownThemeDoesNotRebuildTheDocument(self):
        view = MarkdownView()
        self.addCleanup(view.deleteLater)
        view.setMarkdown("# 标题")

        with patch.object(view, "_rebuild") as rebuild:
            view.syncTheme()

        rebuild.assert_not_called()

    def testReplacingMarkdownCancelsRemoteImageImmediately(self):
        for prefix in ("", "> "):
            with self.subTest(nested=bool(prefix)):
                started = threading.Event()

                def fetch(_url, cancelEvent, _setConnection):
                    started.set()
                    cancelEvent.wait(1)
                    return None

                view = MarkdownView()
                self.addCleanup(view.deleteLater)
                with patch.object(
                    imageBlockModule,
                    "_fetchRemoteImage",
                    side_effect=fetch,
                ):
                    view.setMarkdown(
                        f"{prefix}![图片](https://images.example.test/image.png)"
                    )
                    image = view._content.findChild(ImagePlaceholder)
                    self.assertTrue(started.wait(1))

                    view.setMarkdown("替换后的正文")

                    self.assertTrue(image._remoteCancelEvent.is_set())

    def testMarkdownDisablesSelectionAndUsesBroadcastTypography(self):
        window = BroadcastWindow()
        window.setContent("title", "普通正文", is_markdown=False)
        plainFont = window.contentEdit.font()
        markdownMargins = window.markdownView._contentLayout.contentsMargins()
        documentMargin = round(window.contentEdit.document().documentMargin())
        self.assertEqual(markdownMargins.left(), documentMargin)
        self.assertEqual(markdownMargins.top(), documentMargin)

        window.setContent(
            "title",
            "# 标题\n\n正文\n\n[链接](https://example.com)\n\n"
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n"
            "```python\nprint(1)\n```",
            is_markdown=True,
        )
        self.app.processEvents()

        paragraph = next(
            label
            for label in window.markdownView.findChildren(QLabel)
            if label.objectName() == "paragraph"
        )
        heading = next(
            label
            for label in window.markdownView.findChildren(QLabel)
            if label.objectName() == "h1"
        )
        self.assertEqual(plainFont.pointSizeF(), 26.0)
        self.assertEqual(paragraph.font().pointSizeF(), 26.0)
        self.assertEqual(heading.font().pointSizeF(), 49.0)
        self.assertIn("Microsoft YaHei", paragraph.font().families())

        labels = window.markdownView.findChildren(QLabel)
        self.assertTrue(
            all(
                not label.textInteractionFlags()
                & Qt.TextInteractionFlag.TextSelectableByMouse
                for label in labels
            )
        )
        link = next(label for label in labels if 'href="https://example.com"' in label.text())
        self.assertTrue(
            link.textInteractionFlags() & Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        editor = window.markdownView.findChild(QTextEdit, "code-editor")
        self.assertIsNotNone(editor)
        self.assertEqual(
            editor.textInteractionFlags(), Qt.TextInteractionFlag.NoTextInteraction
        )
        self.assertIsNotNone(window.markdownView._scrollDelegate)
        self.assertIsNotNone(window.contentScrollDelegate)
        self.assertIsNotNone(editor.parentWidget()._scrollDelegate)
        window.close()

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
        with patch.object(
            imageBlockModule,
            "_fetchRemoteImage",
            return_value=_pngBytes(),
        ):
            image = ImagePlaceholder(
                "sample",
                "https://images.example.test/image.png",
            )
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

    def testRemoteImagesRejectPrivateAndNonHttpsTargets(self):
        for url in (
            "http://example.test/image.png",
            "https://127.0.0.1/image.png",
            "https://localhost/image.png",
        ):
            image = ImagePlaceholder("unsafe", url)
            self.assertIsNone(image._remoteThread)
            self.assertIn("unsafe", image.findChild(QLabel).text())
            image.deleteLater()

    def testRemoteImagesRejectDomainsThatResolveToPrivateAddresses(self):
        with patch.object(
            imageBlockModule.socket,
            "getaddrinfo",
            return_value=[
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("127.0.0.1", 443),
                )
            ],
        ):
            with self.assertRaises(OSError):
                imageBlockModule._fetchRemoteImage(
                    "https://127.0.0.1.nip.io/image.png",
                    threading.Event(),
                    lambda _connection: True,
                )

    def testRemoteImageRedirectsAreDnsCheckedBeforeFollowing(self):
        response = MagicMock(status=302)
        response.getheader.side_effect = lambda name: (
            "https://private.example.test/image.png"
            if name == "Location"
            else None
        )
        connection = MagicMock()
        connection.getresponse.return_value = response

        with (
            patch.object(
                imageBlockModule,
                "_resolvePublicAddresses",
                side_effect=[("93.184.216.34",), OSError("private target")],
            ) as resolve,
            patch.object(
                imageBlockModule,
                "_PinnedHTTPSConnection",
                return_value=connection,
            ),
        ):
            with self.assertRaisesRegex(OSError, "private target"):
                imageBlockModule._fetchRemoteImage(
                    "https://example.test/image.png",
                    threading.Event(),
                    lambda _connection: True,
                )

        self.assertEqual(resolve.call_count, 2)

    def testRemoteImageConnectionPinsValidatedIpAndOriginalTlsIdentity(self):
        rawSocket = MagicMock()
        context = MagicMock()
        connection = imageBlockModule._PinnedHTTPSConnection(
            "images.example.test",
            "93.184.216.34",
            443,
            10,
        )
        connection._context = context

        with patch.object(
            imageBlockModule.socket,
            "create_connection",
            return_value=rawSocket,
        ) as createConnection:
            connection.connect()

        createConnection.assert_called_once_with(
            ("93.184.216.34", 443),
            10,
            None,
        )
        context.wrap_socket.assert_called_once_with(
            rawSocket,
            server_hostname="images.example.test",
        )

    def testCanceledRemoteImageCannotReconnectAfterSocketCreation(self):
        cancelEvent = MagicMock()
        cancelEvent.is_set.side_effect = [False, True]
        rawSocket = MagicMock()
        connection = imageBlockModule._PinnedHTTPSConnection(
            "images.example.test",
            "93.184.216.34",
            443,
            10,
            cancelEvent,
        )

        with patch.object(
            imageBlockModule.socket,
            "create_connection",
            return_value=rawSocket,
        ):
            with self.assertRaises(imageBlockModule._RemoteCanceled):
                connection._connectPinned(("images.example.test", 443), 10, None)

        rawSocket.close.assert_called_once_with()

    def testRemoteImageDnsResolutionHonorsTheOverallDeadline(self):
        release = threading.Event()

        def blockedLookup(*_args, **_kwargs):
            release.wait(1)
            return []

        started = time.monotonic()
        try:
            with patch.object(
                imageBlockModule.socket,
                "getaddrinfo",
                side_effect=blockedLookup,
            ), patch.object(
                imageBlockModule,
                "_TOTAL_TIMEOUT_SECONDS",
                0.02,
            ):
                with self.assertRaises(TimeoutError):
                    imageBlockModule._fetchRemoteImage(
                        "https://images.example.test/image.png",
                        threading.Event(),
                        lambda _connection: True,
                    )
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.5)

    def testMarkdownLimitsRemoteImagesPerDocument(self):
        with patch.object(ImagePlaceholder, "_isSafeRemote", return_value=False):
            widgets = self._render(
                "\n\n".join(
                    f"![image {index}](https://example.com/{index}.png)"
                    for index in range(20)
                )
            )

        self.assertEqual(
            sum(isinstance(widget, ImagePlaceholder) for widget in widgets),
            8,
        )
        self.assertEqual(sum(isinstance(widget, QLabel) for widget in widgets), 12)

    def testRemoteImageDecoderScalesBeforeKeepingThePixmap(self):
        image = QImage(2000, 1000, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.red)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")

        pixmap = ImagePlaceholder._decode(bytes(buffer.data()))

        self.assertIsNotNone(pixmap)
        self.assertLessEqual(pixmap.width(), 760)
        self.assertLessEqual(pixmap.width() * pixmap.height(), 1_000_000)

    def testRemoteImageDecoderRejectsOversizedImages(self):
        image = QImage(8193, 1, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.red)
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")

        self.assertIsNone(ImagePlaceholder._decode(bytes(buffer.data())))

    def testMarkdownImageDoesNotReadLocalOrUncPaths(self):
        with patch("pyqt_github_markdown.blocks.image_block.QPixmap") as pixmap:
            image = ImagePlaceholder("unsafe", r"\\attacker\share\image.png")

        pixmap.assert_not_called()
        self.assertIn("unsafe", image.findChild(QLabel).text())
        image.deleteLater()

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
        self.assertEqual(window.markdownView._content.findChildren(QLabel), [])
        window.close()

    def testClosingBroadcastReleasesItsRenderedDocument(self):
        window = BroadcastWindow()
        window.setContent("title", "# 标题\n\n正文", is_markdown=True)
        self.assertTrue(window.markdownView._content.findChildren(QLabel))

        window.close()

        self.assertEqual(window.contentEdit.toPlainText(), "")
        self.assertEqual(window.markdownView._content.findChildren(QLabel), [])

    def testDraggingMarkdownTextDoesNotReachTheFullscreenWindow(self):
        window = BroadcastWindow()
        self.addCleanup(window.close)
        window.setContent(
            "title",
            "**【数学】**\n- 尝试拖动这段已经禁用文字选择的正文\n\n"
            "[查看作业](https://example.com)",
            is_markdown=True,
        )
        window.startBroadcast()
        self.app.processEvents()

        paragraph = next(
            label
            for label in window.markdownView.findChildren(QLabel)
            if label.objectName() == "paragraph"
        )
        start = paragraph.rect().center()

        with (
            patch.object(
                window, "mousePressEvent", wraps=window.mousePressEvent
            ) as mousePress,
            patch.object(
                window, "mouseReleaseEvent", wraps=window.mouseReleaseEvent
            ) as mouseRelease,
        ):
            QTest.mousePress(paragraph, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(paragraph, start + QPoint(80, 0))
            QTest.mouseRelease(
                paragraph,
                Qt.MouseButton.LeftButton,
                pos=start + QPoint(80, 0),
            )
            self.app.processEvents()

        mousePress.assert_not_called()
        mouseRelease.assert_not_called()
        self.assertIsNone(QWidget.mouseGrabber())

        link = next(
            label
            for label in window.markdownView.findChildren(QLabel)
            if 'href="https://example.com"' in label.text()
        )
        with patch(
            "app.view.components.markdown_view.QDesktopServices.openUrl"
        ) as openUrl:
            QTest.mouseClick(
                link,
                Qt.MouseButton.LeftButton,
                pos=QPoint(
                    link.fontMetrics().horizontalAdvance("查看作业") // 2,
                    link.height() // 2,
                ),
            )
        openUrl.assert_called_once()

        window.btn_win.click()
        self.assertTrue(window.is_windowed)

    def testBroadcastTouchScrollDoesNotDragWindow(self):
        window = BroadcastWindow()
        window.contentEdit.setPlainText(
            "\n".join(f"line {index}" for index in range(200))
        )
        window.is_windowed = True
        window.resize(720, 300)
        window.move(100, 100)
        window.show()
        self.app.processEvents()
        viewport = window.contentEdit.viewport()
        scrollBar = window.contentEdit.verticalScrollBar()
        startScroll = scrollBar.value()
        startPosition = window.pos()
        device = QTest.createTouchDevice(QInputDevice.DeviceType.TouchScreen)
        start = QPoint(viewport.width() // 2, viewport.height() - 30)

        QTest.touchEvent(viewport, device).press(0, start, viewport).commit()
        for distance in (30, 60, 90, 120):
            QTest.touchEvent(viewport, device).move(
                0, start - QPoint(0, distance), viewport
            ).commit()
            QTest.qWait(20)
        QTest.touchEvent(viewport, device).release(
            0, start - QPoint(0, 120), viewport
        ).commit()
        QTest.qWait(300)

        self.assertGreater(scrollBar.value(), startScroll)
        self.assertEqual(window.pos(), startPosition)
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

    def testUpdateDialogMatchesItsSurfaceAndScalesWithLargeWindow(self):
        parent = QWidget()
        parent.resize(1600, 1000)
        dialog = UpdateDialog("5.0.1", "# 更新\n\n内容", parent)

        self.assertIn("background: transparent", dialog.markdownView.styleSheet())
        self.assertGreaterEqual(dialog.markdownView.width(), 800)
        self.assertGreaterEqual(dialog.markdownView.height(), 520)
        self.assertGreaterEqual(
            dialog.widget.minimumWidth(),
            dialog.markdownView.width() + 40,
        )

        dialog.close()
        parent.close()
