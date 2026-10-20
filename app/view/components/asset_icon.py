"""Fluent-style icons that QFluentWidgets lacks, shipped in app/assets/icons.

They come from Microsoft's Fluent UI System Icons (MIT, see app/assets/icons/LICENSE),
the same family QFluentWidgets draws from. Each icon has a black and a white file, named
like QFluentWidgets' own; the viewBox is cropped to the glyph so it fills its box edge to
edge like the built-in icons do.
"""

from enum import Enum

from qfluentwidgets import FluentIconBase, Theme, getIconColor

from app.config.paths import ASSET_DIR

ICON_DIR = (ASSET_DIR / "icons").as_posix()


class AssetIcon(FluentIconBase, Enum):
    SHIFTS = "Shifts"

    def path(self, theme=Theme.AUTO) -> str:
        return f"{ICON_DIR}/{self.value}_{getIconColor(theme)}.svg"
