import io
import tokenize
from pathlib import Path
from unittest import TestCase

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

from app.platform.screens import screenFor

APP_ROOT = Path(__file__).resolve().parents[1] / "app"


def _destroy(widget):
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class ScreenForTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def testDestroyingAWindowLeavesTheGlobalScreenAlone(self):
        """QWidget.screen() hands the QScreen wrapper to the widget as a shiboken child,
        so destroying the widget invalidates the one global screen. Later ownership
        shuffles then let a garbage collection delete the C++ QScreen that Qt still
        lists, and the next screen lookup anywhere crashes."""
        screen = QGuiApplication.primaryScreen()
        for _ in range(3):
            window = QWidget()
            window.resize(300, 200)
            window.show()
            self.assertIs(screenFor(window), screen)
            _destroy(window)
            self.assertTrue(shiboken6.isValid(screen))
        self.assertFalse(shiboken6.ownedByPython(screen))

    def testChildWidgetsResolveToTheirWindowsScreen(self):
        window = QWidget()
        child = QWidget(window)
        window.show()
        try:
            self.assertIs(screenFor(child), screenFor(window))
        finally:
            _destroy(window)

    def testUnplacedWindowFallsBackToThePrimaryScreen(self):
        window = QWidget()
        window.move(-100000, -100000)
        try:
            self.assertIs(screenFor(window), QGuiApplication.primaryScreen())
        finally:
            _destroy(window)


class NoWidgetScreenCallsTest(TestCase):
    def testAppCodeNeverCallsScreenOnAWidgetOrWindow(self):
        offenders = []
        for path in sorted(APP_ROOT.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tokens = [
                token
                for token in tokenize.generate_tokens(io.StringIO(source).readline)
                if token.type not in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE)
            ]
            for previous, name, opening, closing in zip(
                tokens, tokens[1:], tokens[2:], tokens[3:]
            ):
                if (
                    previous.string == "."
                    and name.string == "screen"
                    and opening.string == "("
                    and closing.string == ")"
                ):
                    offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{name.start[0]}")
        self.assertEqual(offenders, [], "use app.platform.screens.screenFor instead")
