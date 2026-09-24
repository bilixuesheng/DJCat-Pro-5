import os
import sys
import traceback

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


def installTranslators(app):
    """Qt 原生控件（Markdown 链接的右键菜单）和 QFluentWidgets 自带控件（开关的
    On/Off、输入框右键菜单、颜色对话框的 OK/Cancel）的文案默认都是英文。"""
    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
    from qfluentwidgets import FluentTranslator

    from app.config.paths import QT_TRANSLATIONS_DIR

    locale = QLocale(QLocale.Language.Chinese, QLocale.Country.China)
    qtTranslator = QTranslator(app)
    for directory in (
        QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
        str(QT_TRANSLATIONS_DIR),
    ):
        if qtTranslator.load(locale, "qtbase", "_", directory):
            app.installTranslator(qtTranslator)
            break
    # 翻译器挂在 app 上，否则 Python 对象被回收后翻译就失效了。
    app._fluentTranslator = FluentTranslator(locale)
    app.installTranslator(app._fluentTranslator)


def configureLogging():
    from loguru import logger
    from app.config.paths import LOG_DIR

    logger.add(
        str(LOG_DIR / "djcatpro日志_{time:YYYY-MM-DD}.log"),
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

    from app.platform.application import SingletonApplication, raiseWindow
    from app.platform.animation_timer import unlockQtAnimations

    app = SingletonApplication(sys.argv)
    unlockQtAnimations()
    isSilent = "--silence" in sys.argv
    activationPending = False

    def onActivationRequested():
        nonlocal activationPending
        window = getattr(app, "window", None)
        if window is None:
            activationPending = True
            return
        activationPending = False
        raiseWindow(window)

    app.activationRequested.connect(onActivationRequested)

    from PySide6.QtGui import QColor
    from qfluentwidgets import qconfig, setThemeColor

    from app.common.update_download import clearUpdateDirectory, restoreUpdaterBinary
    from app.config.cfg import cfg, migrateConfig
    from app.config.paths import CONFIG_PATH
    from app.platform.dialog_animation import optimizeFluentDialogs
    from app.platform.menu_animation import optimizeFluentMenus

    optimizeFluentDialogs()
    optimizeFluentMenus()

    installTranslators(app)

    configureLogging()
    failedCleanup = clearUpdateDirectory()
    if failedCleanup:
        from loguru import logger

        logger.warning(
            "暂时无法清理更新目录中的 {} 个文件，将在下次启动时重试",
            len(failedCleanup),
        )
    from app.config.paths import APP_DIR

    if restoreUpdaterBinary(APP_DIR):
        from loguru import logger

        logger.warning("上次更新未能替换 updater.exe，已从备份恢复")
    sys.excepthook = exceptionHook
    qconfig.load(CONFIG_PATH, cfg)
    migrateConfig()
    setThemeColor(QColor(49, 101, 49))

    app.window = startApp(isSilent=isSilent)
    if activationPending:
        onActivationRequested()
    app.aboutToQuit.connect(app.window._shutdownResources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
