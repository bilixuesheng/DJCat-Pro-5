import os
import sys
import tempfile
import traceback

MainWindow = None


def exceptionHook(excType, excValue, excTraceback):
    from loguru import logger

    from app.signal_bus import signalBus

    excInfo = (excType, excValue, excTraceback)
    message = "".join(traceback.format_exception(*excInfo)).rstrip()
    logger.opt(exception=excInfo).error("未处理的程序异常")

    try:
        from app.common.error_report import reportError

        reportError(*excInfo)
    except Exception:
        logger.exception("报错上报失败")

    try:
        signalBus.catchException.emit(message)
    except RuntimeError:
        pass

    if "__compiled__" not in globals():
        sys.__excepthook__(*excInfo)


def bindDeveloperOptions(app) -> None:
    """Developer Options take effect at once and follow their switches."""
    from app.config.cfg import cfg
    from app.platform.animation_timer import setSuperFrameRateEnabled
    from app.platform.touch_input import setTouchPressFeedbackEnabled
    from app.view.components.frame_rate import setFrameRateShown
    from app.view.components.scroll_area import setTunedTouchScrollEnabled

    def follow(item, apply):
        apply(item.value)
        item.valueChanged.connect(apply)

    follow(
        cfg.disableTouchPressFeedback,
        lambda disabled: setTouchPressFeedbackEnabled(app, not disabled),
    )
    follow(
        cfg.disableTunedTouchScroll,
        lambda disabled: setTunedTouchScrollEnabled(not disabled),
    )
    follow(
        cfg.disableSuperFrameRate,
        lambda disabled: setSuperFrameRateEnabled(not disabled),
    )
    follow(cfg.showFrameRate, setFrameRateShown)


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


def main():
    # 从电教猫打开的程序会继承它的工作目录。留在程序目录里的话，那些程序开着期间 Windows
    # 不让给程序目录改名，Client Update 就整次退回。资源和配置都按绝对路径取，不依赖它。
    # 更新器和快捷方式都从程序目录启动电教猫，换不走就是原样，所以要有退路。
    for directory in (os.path.expanduser("~"), tempfile.gettempdir()):
        try:
            os.chdir(directory)
            break
        except OSError:
            continue

    from app.platform.application import SingletonApplication, raiseWindow
    from app.platform.text_rendering import cacheLargeGlyphs

    cacheLargeGlyphs()
    app = SingletonApplication(sys.argv)
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

    from app.common.app_font import bindAppFont
    from app.common.logs import configureLogging
    from app.common.update_download import clearUpdateDirectory, restoreUpdaterBinary
    from app.config.cfg import cfg, migrateConfig
    from app.config.paths import CONFIG_PATH
    from app.platform.dialog_animation import optimizeFluentDialogs
    from app.platform.icon_cache import cacheFluentSvgIcons
    from app.platform.menu_animation import optimizeFluentMenus
    from app.platform.style_sheet import optimizeFluentStyleSheets

    optimizeFluentDialogs()
    optimizeFluentMenus()
    cacheFluentSvgIcons()
    optimizeFluentStyleSheets()

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
    # 早于任何控件，之后跟着「个性化 › 字体」当场换。
    bindAppFont()
    # 超级帧率优化也在这里，读出配置才知道要不要设 1 ms，仍早于任何动画。
    bindDeveloperOptions(app)
    setThemeColor(QColor(49, 101, 49))

    app.window = startApp(isSilent=isSilent)
    if activationPending:
        onActivationRequested()
    app.aboutToQuit.connect(app.window._shutdownResources)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
