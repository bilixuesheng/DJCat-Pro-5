"""反拦截提示：设置顶层页上建议用户试开反弹窗拦截的常驻横幅。

它无条件显示（不检测窗口是否真被关），只按开关状态与两种"关掉"决定显隐，规则见
:func:`app.common.anti_popup_block.tipShouldShow`。本组件只发信号，显隐和持久化由
设置页决定。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    IconWidget,
    PrimaryPushButton,
    PushButton,
    TransparentToolButton,
)

from app.view.components.setting_card_group import SettingMaterialCard

ANTI_BLOCK_TIP_TEXT = (
    "若「电教猫 Pro 5」主页以外的窗口（投送、设置、各种对话框等）刚打开几秒就自动消失，"
    "可能是被「弹窗拦截 / 桌面管理 / 安全防护」类软件误当成广告弹窗关掉了。"
    "可以试试开启「反弹窗拦截」。"
)


class AntiBlockTip(SettingMaterialCard):
    goRequested = Signal()
    dismissedForNow = Signal()
    dismissedForever = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self) -> None:
        self.iconWidget = IconWidget(FluentIcon.INFO, self)
        self.iconWidget.setFixedSize(20, 20)
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

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)
        top.addWidget(self.iconWidget, 0, Qt.AlignmentFlag.AlignTop)
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
