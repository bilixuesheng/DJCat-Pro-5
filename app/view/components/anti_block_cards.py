"""反弹窗拦截的「管理模式」「轮换间隔」卡片和「自定义名」对话框。

规则在 app/common/anti_popup_block.py；这里只显示和改 cfg，不负责重启——
重启由 setting_page 发出 antiPopupBlockApplyRequested、交给 MainWindow。
"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    LineEdit,
    MessageBoxBase,
    SegmentedWidget,
    SettingCard,
    SpinBox,
    SubtitleLabel,
)

from app.common import anti_popup_block as apb
from app.config.cfg import cfg


class AntiBlockModeCard(SettingCard):
    """自动管理 / 手动管理的左右切换；切换模式只改 cfg，不重启。"""

    def __init__(self, parent=None):
        super().__init__(
            FluentIcon.SETTING,
            "管理模式",
            "自动管理每隔几天自动换名，手动管理只在你手动换时才换",
            parent,
        )
        self._applying = False
        self.segmented = SegmentedWidget(self)
        self.segmented.addItem(apb.MODE_AUTO, "自动管理")
        self.segmented.addItem(apb.MODE_MANUAL, "手动管理")
        self.hBoxLayout.addWidget(self.segmented)
        self.hBoxLayout.addSpacing(16)
        self.segmented.currentItemChanged.connect(self._onChanged)
        cfg.antiPopupBlockMode.valueChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, _value=None) -> None:
        # setCurrentItem 也会发 currentItemChanged，用标志挡掉免得回写 cfg。
        self._applying = True
        try:
            key = cfg.antiPopupBlockMode.value
            if key not in (apb.MODE_AUTO, apb.MODE_MANUAL):
                key = apb.MODE_AUTO
            self.segmented.setCurrentItem(key)
        finally:
            self._applying = False

    def _onChanged(self, key: str) -> None:
        if self._applying:
            return
        cfg.set(cfg.antiPopupBlockMode, key)


class RotateDaysCard(SettingCard):
    """轮换间隔数值框（1–30 天）；说明里只读显示当前伪装名，供 IT 核对。"""

    def __init__(self, parent=None):
        super().__init__(FluentIcon.SYNC, "轮换间隔", "", parent)
        self.spinBox = SpinBox(self)
        self.spinBox.setRange(apb.MIN_ROTATE_DAYS, 30)
        self.spinBox.setSuffix(" 天")
        self.spinBox.setFixedWidth(150)
        # 边打字边存会让到点判定来回跳，输完（回车/失焦/点箭头）才存。
        self.spinBox.setKeyboardTracking(False)
        self.hBoxLayout.addWidget(self.spinBox)
        self.hBoxLayout.addSpacing(16)
        self.spinBox.valueChanged.connect(self._onValueChanged)
        cfg.antiPopupBlockRotateDays.valueChanged.connect(self.refresh)
        cfg.disguisedProductName.valueChanged.connect(self._refreshContent)
        self.refresh()
        self._refreshContent()

    def refresh(self, _value=None) -> None:
        with QSignalBlocker(self.spinBox):
            self.spinBox.setValue(int(cfg.antiPopupBlockRotateDays.value))

    def _refreshContent(self, _value=None) -> None:
        name = (cfg.disguisedProductName.value or "").strip() or apb.DEFAULT_DISGUISED_NAME
        self.setContent(f"每隔这么多天自动换一个随机伪装名（当前：{name}）")

    def _onValueChanged(self, value: int) -> None:
        # 改间隔不重启：只改 cfg，到下次轮换才体现。
        if int(cfg.antiPopupBlockRotateDays.value) != int(value):
            cfg.set(cfg.antiPopupBlockRotateDays, int(value))


class CustomNameDialog(MessageBoxBase):
    """让用户填一个自定义伪装名；确定按钮即「确定并重启」，最低校验。"""

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self._name = None
        self.titleLabel = SubtitleLabel("自定义伪装名称", self)
        self.lineEdit = LineEdit(self)
        self.lineEdit.setPlaceholderText("填一个像正常软件的英文名，如 SmartClass 4")
        self.lineEdit.setText(current)
        self.lineEdit.setClearButtonEnabled(True)
        self.errorLabel = CaptionLabel("", self)
        self.errorLabel.setTextColor("#c42b1c", "#ff99a4")
        self.errorLabel.hide()

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.lineEdit)
        self.viewLayout.addWidget(self.errorLabel)
        self.yesButton.setText("确定并重启")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(360)
        self.lineEdit.textChanged.connect(lambda _=None: self.errorLabel.hide())

    def validate(self) -> bool:
        # 返回 False 时对话框不关闭；最低校验：非空、不等于诚实名。
        name = apb.normalizeCustomName(self.lineEdit.text())
        if name is None:
            self.errorLabel.setText(f"名称不能为空，也不能就是「{apb.HONEST_PRODUCT_NAME}」")
            self.errorLabel.show()
            return False
        self._name = name
        return True

    def name(self) -> "str | None":
        return self._name
