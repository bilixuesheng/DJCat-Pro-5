"""反拦截提示：根 Section 最上面建议用户试开反弹窗拦截的黄色提示。

它无条件显示（不检测窗口是否真被关），只按开关状态与两种"关掉"决定显隐，规则见
:func:`app.common.anti_popup_block.tipShouldShow`。本组件只发信号，显隐和持久化由
设置页决定。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IconWidget,
    InfoBarIcon,
    PrimaryPushButton,
    PushButton,
    TransparentToolButton,
    isDarkTheme,
    qconfig,
)

ANTI_BLOCK_TIP_TEXT = (
    "若「电教猫 Pro 5」主页以外的窗口（投送、设置、各种对话框等）刚打开几秒就自动消失，"
    "可能是被「弹窗拦截 / 桌面管理 / 安全防护」类软件误当成广告弹窗关掉了。"
    "可以试试开启「反弹窗拦截」。"
)

# 照 QFluentWidgets InfoBar 的 Warning 配色（info_bar.qss）。黄色只为醒目，不表示出了错。
_BACKGROUND = {False: QColor(255, 244, 206), True: QColor(67, 53, 25)}
_BORDER = {False: QColor(229, 229, 229), True: QColor(29, 29, 29)}
_RADIUS = 6
_ICON_SIZE = 16


class AntiBlockTip(QWidget):
    goRequested = Signal()
    dismissedForNow = Signal()
    dismissedForever = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.iconWidget = IconWidget(InfoBarIcon.WARNING, self)
        self.iconWidget.setFixedSize(_ICON_SIZE, _ICON_SIZE)
        self.textLabel = BodyLabel(ANTI_BLOCK_TIP_TEXT, self)
        self.textLabel.setWordWrap(True)
        self.closeButton = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeButton.setFixedSize(28, 28)
        self.closeButton.setToolTip("本次隐藏（下次启动仍会显示）")
        self.goButton = PrimaryPushButton("前往开启反弹窗拦截", self)
        self.dismissButton = PushButton("不再显示", self)

    def _initLayout(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 10, 12)
        outer.setSpacing(10)

        # 图标对着第一行文字的中线：正文一行约 20 px，图标 16 px。
        iconColumn = QVBoxLayout()
        iconColumn.setContentsMargins(0, 2, 0, 0)
        iconColumn.addWidget(self.iconWidget)
        iconColumn.addStretch(1)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        top.addLayout(iconColumn)
        top.addWidget(self.textLabel, 1)
        top.addWidget(self.closeButton, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(top)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addStretch(1)
        buttons.addWidget(self.dismissButton)
        buttons.addWidget(self.goButton)
        outer.addLayout(buttons)

    def _bind(self) -> None:
        self.closeButton.clicked.connect(self.dismissedForNow)
        self.goButton.clicked.connect(self.goRequested)
        self.dismissButton.clicked.connect(self.dismissedForever)
        qconfig.themeChanged.connect(self._onThemeChanged)

    def _onThemeChanged(self, _theme=None) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        dark = isDarkTheme()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(_BORDER[dark], 1))
        painter.setBrush(_BACKGROUND[dark])
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _RADIUS, _RADIUS
        )
