import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel


MainWindow = None


def exceptionHook(excType, excValue, excTraceback):
    from loguru import logger

    from app.signal_bus import signalBus

    excInfo = (excType, excValue, excTraceback)
    message = "".join(traceback.format_exception(*excInfo)).rstrip()
    logger.opt(exception=excInfo).error("未处理的程序异常")

    try:
        signalBus.catchException.emit(message)
    except RuntimeError:
        pass

    if "__compiled__" not in globals():
        sys.__excepthook__(*excInfo)


def startApp(isSilent: bool = False, showSplash: bool = True):
    windowClass = MainWindow
    if windowClass is None:
        from app.view.windows.main_window import MainWindow as windowClass

    if showSplash:
        return windowClass(isSilent=isSilent)
    return windowClass(isSilent=isSilent, showSplash=False)


def createStartupScreen() -> QLabel:
    iconPath = Path(__file__).resolve().parent / "app" / "assets" / "logo.png"
    icon = QPixmap(str(iconPath))
    canvas = QPixmap(800, 450)
    canvas.fill(QApplication.palette().window().color())

    if not icon.isNull():
        icon = icon.scaled(
            96,
            96,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter = QPainter(canvas)
        painter.drawPixmap(
            (canvas.width() - icon.width()) // 2,
            (canvas.height() - icon.height()) // 2,
            icon,
        )
        painter.end()

    splashScreen = QLabel()
    splashScreen.setPixmap(canvas)
    splashScreen.setWindowFlags(
        Qt.WindowType.SplashScreen | Qt.WindowType.WindowStaysOnTopHint
    )
    splashScreen.setWindowIcon(QIcon(str(iconPath)))
    splashScreen.resize(canvas.size())
    screen = QApplication.primaryScreen()
    if screen is not None:
        splashScreen.move(
            screen.availableGeometry().center() - splashScreen.rect().center()
        )
    splashScreen.show()
    QApplication.processEvents()
    return splashScreen


def configureLogging():
    from loguru import logger

    logger.add(
        "Log/djcatpro日志_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="14 days",
        enqueue=True,
        encoding="utf-8",
    )


def main():
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    app = QApplication(sys.argv)
    isSilent = "--silence" in sys.argv
    startupScreen = None if isSilent else createStartupScreen()

    from PySide6.QtGui import QColor
    from qfluentwidgets import qconfig, setThemeColor

    from app.common.update_download import clearUpdateDirectory
    from app.config.cfg import cfg
    from app.config.paths import CONFIG_PATH

    clearUpdateDirectory()
    configureLogging()
    sys.excepthook = exceptionHook
    qconfig.load(CONFIG_PATH, cfg)
    setThemeColor(QColor(49, 101, 49))

    try:
        app.window = startApp(
            isSilent=isSilent,
            showSplash=startupScreen is None,
        )
    except Exception:
        if startupScreen is not None:
            startupScreen.close()
        raise

    if startupScreen is not None:
        startupScreen.close()
        startupScreen.deleteLater()
    app.aboutToQuit.connect(app.window._shutdownResources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
