import os
import sys
import time
import traceback

from PySide6.QtWidgets import QApplication


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


def startApp(isSilent: bool = False):
    windowClass = MainWindow
    if windowClass is None:
        from app.view.windows.main_window import MainWindow as windowClass

    return windowClass(isSilent=isSilent)


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
    if "--app-maintenance" in sys.argv:
        index = sys.argv.index("--app-maintenance")
        if index + 1 >= len(sys.argv):
            raise SystemExit(2)
        from app.platform.app_maintenance import maintenanceMain

        raise SystemExit(maintenanceMain(sys.argv[index + 1]))

    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    app = QApplication(sys.argv)
    isSilent = "--silence" in sys.argv

    from PySide6.QtGui import QColor
    from qfluentwidgets import qconfig, setThemeColor

    from app.common.update_download import clearUpdateDirectory
    from app.common.app_store import clearImageCache, recoverInterruptedInstalls
    from app.config.cfg import cfg
    from app.config.paths import CONFIG_PATH

    clearUpdateDirectory()
    configureLogging()
    sys.excepthook = exceptionHook
    qconfig.load(CONFIG_PATH, cfg)
    try:
        recoverInterruptedInstalls()
    except OSError:
        pass
    now = int(time.time())
    try:
        lastCacheCleanup = int(cfg.appStoreCacheLastCleanup.value or 0)
    except (TypeError, ValueError):
        lastCacheCleanup = 0
    if now - lastCacheCleanup >= 7 * 24 * 60 * 60:
        try:
            clearImageCache()
        except OSError:
            pass
        else:
            cfg.set(cfg.appStoreCacheLastCleanup, now)
    setThemeColor(QColor(49, 101, 49))

    app.window = startApp(isSilent=isSilent)
    app.aboutToQuit.connect(app.window._shutdownResources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
