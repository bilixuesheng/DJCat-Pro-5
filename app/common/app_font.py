"""App Font: the font DJCat shows its text in.

QFluentWidgets widgets take the families in ``qconfig.fontFamilies`` through their style
sheets and ``getFont()``. Plain Qt widgets (the banner's "主页", the countdown and clock
titles, the Projection body) name no family and inherit the QApplication font, which Qt 6
on Windows takes from the system message font. When that font has no Chinese glyphs,
Qt does not follow Windows font linking (SystemLink); it walks its own fallback list,
and for the Simplified Chinese locale that list starts with SimSun. Both sides must
therefore carry the same families.

Qt picks a font per character: the first family in the list that has the glyph. So the
Chinese families always come last, and nothing finer than "Latin first, then Chinese"
can be set: a font for English punctuation alone would also take the letters.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget
from qfluentwidgets import qconfig
from qfluentwidgets.common.style_sheet import updateStyleSheet

from app.config.cfg import APP_FONT_MODES, DEFAULT_FONT, SYSTEM_FONT, cfg
from app.signal_bus import signalBus

SEPARATE_MODE = APP_FONT_MODES[1]
# QFluentWidgets 的默认字体；PingFang SC 是 macOS 的，照原样留着。
DEFAULT_LATIN_FAMILIES = ("Segoe UI",)
DEFAULT_CJK_FAMILIES = ("Microsoft YaHei", "PingFang SC")


def systemFontFamily() -> str:
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()


def fontInstalled(value: str) -> bool:
    return value not in (DEFAULT_FONT, SYSTEM_FONT) and QFontDatabase.hasFamily(value)


def _latinFamilies(value: str) -> list[str]:
    if value == SYSTEM_FONT:
        return [systemFontFamily()]
    return [value] if fontInstalled(value) else list(DEFAULT_LATIN_FAMILIES)


def _cjkFamilies(value: str) -> list[str]:
    # 选的中文字体缺字时仍由雅黑补，不落到 Qt 的候补列表（宋体）。
    return [value, *DEFAULT_CJK_FAMILIES] if fontInstalled(value) else list(DEFAULT_CJK_FAMILIES)


def resolveFamilies(mode: str, appFont: str, latinFont: str, cjkFont: str) -> list[str]:
    if mode == SEPARATE_MODE:
        families = _latinFamilies(latinFont) + _cjkFamilies(cjkFont)
    else:
        families = _latinFamilies(appFont) + list(DEFAULT_CJK_FAMILIES)
    return list(dict.fromkeys(families))


def appFontFamilies() -> list[str]:
    return resolveFamilies(
        cfg.appFontMode.value, cfg.appFont.value, cfg.latinFont.value, cfg.cjkFont.value
    )


def previewFamilies(item, value: str) -> list[str]:
    """The App Font families if ``item`` held ``value``, in the Font Mode that shows it."""
    values = {font: font.value for font in (cfg.appFont, cfg.latinFont, cfg.cjkFont)}
    values[item] = value
    mode = SEPARATE_MODE if item is not cfg.appFont else APP_FONT_MODES[0]
    return resolveFamilies(mode, values[cfg.appFont], values[cfg.latinFont], values[cfg.cjkFont])


def applyAppFont(*_args) -> None:
    app = QApplication.instance()
    families = appFontFamilies()
    oldFamilies = qconfig.get(qconfig.fontFamilies)
    font = app.font()
    if families == oldFamilies and font.families() == families:
        return
    # 下面重新套用组件库样式表时，--FontFamilies 按它代入。
    qconfig.set(qconfig.fontFamilies, families, save=False)
    font.setFamilies(families)
    app.setFont(font)
    _refreshWidgets(oldFamilies, families)
    signalBus.appFontChanged.emit()


def _refreshWidgets(oldFamilies: list[str], families: list[str]) -> None:
    # 组件库样式表里的 --FontFamilies 在套用时才代入。
    updateStyleSheet()
    # 程序字体的变化传不到这些控件：自己设过字体的（getFont()、抄了程序字体再改字号）；挂着
    # 样式表的（polish 时就按样式表定下字体，Qt 文档也说 QApplication::setFont 不要和样式表
    # 混用）；以及它们下面的子控件。自上而下处理，父控件先换好：自己设过的只换家族，其余的
    # 清掉字体让它重新继承，样式表定的字号粗细照旧。不能重新 polish：在 Windows 上从这里
    # 对控件调用 QStyle.polish 会访问冲突。
    for window in QApplication.topLevelWidgets():
        for widget in (window, *window.findChildren(QWidget)):
            font = widget.font()
            if font.families() != oldFamilies:
                continue
            if widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
                font.setFamilies(families)
            else:
                font = QFont()
            widget.setFont(font)


def bindAppFont() -> None:
    """Apply the App Font before any widget exists, then follow its settings."""
    applyAppFont()
    for item in (cfg.appFontMode, cfg.appFont, cfg.latinFont, cfg.cjkFont):
        item.valueChanged.connect(applyAppFont)
