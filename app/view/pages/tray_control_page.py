from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import (
    ComboBoxSettingCard,
    FluentIcon,
    SettingCard,
    SettingCardGroup,
    SwitchSettingCard,
    TitleLabel,
)

from app.config.cfg import cfg
from app.view.components.scroll_area import ScrollArea


class TrayControlPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TrayControlPage")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()

        self.container = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(30, 20, 30, 36)
        self.vBoxLayout.setSpacing(20)
        self.vBoxLayout.addWidget(TitleLabel("自定义托盘控件", self.container))

        clickGroup = SettingCardGroup("点击行为", self.container)
        self.leftClickCard = ComboBoxSettingCard(
            cfg.trayLeftClickAction,
            FluentIcon.MENU,
            "左键单击",
            "选择打开主窗口或显示托盘菜单",
            texts=["打开主窗口", "显示托盘菜单"],
        )
        clickGroup.addSettingCard(self.leftClickCard)
        self.vBoxLayout.addWidget(clickGroup)

        menuGroup = SettingCardGroup("菜单控件", self.container)
        self.menuCards = [
            SwitchSettingCard(
                FluentIcon.PLAY,
                "显示播报总开关",
                "在托盘菜单中开启或关闭全部定时播报",
                cfg.showBroadcastTrayAction,
            ),
            SwitchSettingCard(
                FluentIcon.POWER_BUTTON,
                "显示关机总开关",
                "在托盘菜单中开启或关闭全部定时关机",
                cfg.showShutdownTrayAction,
            ),
            SwitchSettingCard(
                FluentIcon.FOLDER,
                "放入二级菜单",
                "将已选主页卡片统一收进“主页卡片”菜单",
                cfg.trayHomeCardsInSubmenu,
            ),
        ]
        menuGroup.addSettingCards(self.menuCards)
        self.vBoxLayout.addWidget(menuGroup)

        self._homeCards = []
        self.homeCardSwitches = {}
        self.homeCardGroup = self._createHomeCardGroup()
        self.vBoxLayout.addWidget(self.homeCardGroup)
        self.vBoxLayout.addStretch(1)
        self.setWidget(self.container)

        cfg.trayHomeCardKeys.valueChanged.connect(self._syncHomeCardSwitches)

    def setHomeCards(self, entries) -> None:
        self._homeCards = []
        keys = set()
        for entry in entries or []:
            key = entry.get("key") if isinstance(entry, dict) else None
            if not isinstance(key, str) or not key or key in keys:
                continue
            keys.add(key)
            self._homeCards.append(entry)

        oldGroup = self.homeCardGroup
        self.homeCardGroup = self._createHomeCardGroup()
        self.vBoxLayout.replaceWidget(oldGroup, self.homeCardGroup)
        oldGroup.deleteLater()

    def _createHomeCardGroup(self) -> SettingCardGroup:
        group = SettingCardGroup("主页卡片", self.container)
        self.homeCardSwitches = {}
        if not self._homeCards:
            group.addSettingCard(
                SettingCard(
                    FluentIcon.INFO,
                    "暂无主页卡片",
                    "请先在主页添加或恢复卡片",
                )
            )
            return group

        selected = (
            {
                value
                for value in cfg.trayHomeCardKeys.value
                if isinstance(value, str)
            }
            if isinstance(cfg.trayHomeCardKeys.value, list)
            else set()
        )
        for entry in self._homeCards:
            key = entry["key"]
            card = SwitchSettingCard(
                entry["icon"],
                entry["title"],
                entry.get("description", ""),
            )
            card.setChecked(key in selected)
            card.checkedChanged.connect(
                lambda checked, cardKey=key: self._setHomeCardEnabled(
                    cardKey, checked
                )
            )
            self.homeCardSwitches[key] = card
            group.addSettingCard(card)
        return group

    def _setHomeCardEnabled(self, key: str, enabled: bool) -> None:
        selected = (
            {
                value
                for value in cfg.trayHomeCardKeys.value
                if isinstance(value, str)
            }
            if isinstance(cfg.trayHomeCardKeys.value, list)
            else set()
        )
        if enabled:
            selected.add(key)
        else:
            selected.discard(key)
        cfg.set(
            cfg.trayHomeCardKeys,
            [entry["key"] for entry in self._homeCards if entry["key"] in selected],
        )

    def _syncHomeCardSwitches(self, keys) -> None:
        selected = (
            {key for key in keys if isinstance(key, str)}
            if isinstance(keys, list)
            else set()
        )
        for key, card in self.homeCardSwitches.items():
            with QSignalBlocker(card.switchButton):
                card.setChecked(key in selected)
