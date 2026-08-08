import os
import sys
import traceback

from loguru import logger
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from qfluentwidgets import qconfig, setThemeColor

from app.common.update_download import clearUpdateDirectory
from app.config.cfg import cfg
from app.config.paths import CONFIG_PATH
from app.signal_bus import signalBus
from app.view.windows.main_window import MainWindow


def exceptionHook(excType, excValue, excTraceback):
    excInfo = (excType, excValue, excTraceback)
    message = "".join(traceback.format_exception(*excInfo)).rstrip()
    logger.opt(exception=excInfo).error("未处理的程序异常")

    try:
        signalBus.catchException.emit(message)
    except RuntimeError:
        pass

    if "__compiled__" not in globals():
        sys.__excepthook__(*excInfo)


def startApp(isSilent: bool = False) -> MainWindow:
    return MainWindow(isSilent=isSilent)


def configureLogging():
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

    clearUpdateDirectory()
    configureLogging()
    sys.excepthook = exceptionHook

    app = QApplication(sys.argv)
    qconfig.load(CONFIG_PATH, cfg)
    setThemeColor(QColor(49, 101, 49))

    app.window = startApp(isSilent="--silence" in sys.argv)
    app.aboutToQuit.connect(app.window._shutdownResources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
