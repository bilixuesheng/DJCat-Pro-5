from unittest import TestCase

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import InfoBar

from app.view.windows.main_window import MainWindow


class ExceptionInfoBarTest(TestCase):
    def testInfoBarWithLogButtonSlidesFullyInsideWindow(self):
        window = QWidget()
        window.resize(640, 480)
        window.show()
        try:
            MainWindow._onExceptionCaught(window, "boom")
            infoBar = window.findChild(InfoBar)
            # 滑入动画 200 ms；这期间没有任何东西会让 InfoBarManager 重算位置。
            QTest.qWait(400)

            self.assertTrue(
                window.rect().contains(infoBar.geometry()),
                f"{infoBar.geometry()} 超出 {window.rect()}",
            )
        finally:
            window.close()
            window.deleteLater()
