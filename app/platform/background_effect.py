"""Background Effect: the material Windows composes behind the main window.

The choices and how each is applied follow Ghost Downloader's personalization setting,
on top of qframelesswindow's ``WindowEffect``. Mica and MicaAlt exist only on Win11; on
Win10 they are still offered and leave the window transparent with nothing composed
behind it, as Ghost does.
"""

import sys
from ctypes import pointer

BACKGROUND_EFFECTS = ("Acrylic", "Mica", "MicaAlt", "Aero", "None")

# SetWindowCompositionAttribute 的取值，与 qframelesswindow.windows.c_structures 相同；
# 那个包只能在 Windows 上导入，这里只用到三个数。
_ACCENT_ENABLE_GRADIENT = 1
_ACCENT_ENABLE_TRANSPARENTGRADIENT = 2
_WCA_ACCENT_POLICY = 19


def isWin10() -> bool:
    return sys.platform == "win32" and sys.getwindowsversion().build < 22000


def defaultBackgroundEffect() -> str:
    return "None" if isWin10() else "Mica"


def applyBackgroundEffect(window, effect: str, isDark: bool, removeFirst: bool = True) -> None:
    """Compose ``effect`` behind a qframelesswindow window in the given theme."""
    windowEffect = window.windowEffect
    hWnd = window.winId()
    if removeFirst:
        windowEffect.removeBackgroundEffect(hWnd)
    if effect == "Acrylic":
        windowEffect.setAcrylicEffect(hWnd, "00000030" if isDark else "FFFFFF30")
    elif effect == "Mica":
        windowEffect.setMicaEffect(hWnd, isDark)
    elif effect == "MicaAlt":
        windowEffect.setMicaEffect(hWnd, isDark, isAlt=True)
    elif effect == "Aero":
        windowEffect.setAeroEffect(hWnd)
    elif isWin10():
        # 照 Ghost：Win10 上的 None 换成不透明渐变，而不是只关掉 Accent。
        _setAccentState(windowEffect, hWnd, _ACCENT_ENABLE_GRADIENT)


def suspendsAcrylicDuringMove(effect: str) -> bool:
    """Win10 acrylic trails a moving window, so the blur is dropped until the move ends."""
    return effect == "Acrylic" and isWin10()


def suspendAcrylic(window) -> None:
    _setAccentState(window.windowEffect, window.winId(), _ACCENT_ENABLE_TRANSPARENTGRADIENT)


def _setAccentState(windowEffect, hWnd, state: int) -> None:
    windowEffect.accentPolicy.AccentState = state
    windowEffect.winCompAttrData.Attribute = _WCA_ACCENT_POLICY
    windowEffect.SetWindowCompositionAttribute(int(hWnd), pointer(windowEffect.winCompAttrData))
