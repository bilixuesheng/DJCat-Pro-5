import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.view.components.setting_card_group import (
    CollapsibleSettingCardGroup,
    SettingMaterialCard,
)
from app.view.pages.schedule_page import TaskCard
from app.view.pages.shutdown_page import ShutdownTaskCard


class TaskCardMaterialTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def testTaskCardsReuseSettingPageMaterial(self):
        self.assertTrue(
            issubclass(CollapsibleSettingCardGroup, SettingMaterialCard)
        )
        self.assertTrue(issubclass(TaskCard, SettingMaterialCard))
        self.assertTrue(issubclass(ShutdownTaskCard, SettingMaterialCard))

    def testMaterialKeepsSettingPageTransparencyInBothThemes(self):
        with patch(
            "app.view.components.setting_card_group.isDarkTheme",
            return_value=False,
        ):
            lightColor = SettingMaterialCard._normalBackgroundColor(None)

        with patch(
            "app.view.components.setting_card_group.isDarkTheme",
            return_value=True,
        ):
            darkColor = SettingMaterialCard._normalBackgroundColor(None)

        self.assertEqual(lightColor.getRgb(), (255, 255, 255, 170))
        self.assertEqual(darkColor.getRgb(), (255, 255, 255, 13))

    def testExpandCardSurfacesExposeOuterMaterial(self):
        cards = (
            TaskCard(
                {
                    "name": "午间播报",
                    "time": "12:30:00",
                    "weeks": list(range(7)),
                    "type": "预设: 12:30报时",
                    "content": "",
                    "file": "",
                    "repeat": 3,
                    "volume": 100,
                    "enabled": True,
                }
            ),
            ShutdownTaskCard(
                {
                    "name": "晚间关机",
                    "time": "22:30:00",
                    "weeks": list(range(7)),
                    "notify": True,
                    "promptTitle": "Windows 即将关闭你的计算机",
                    "promptMessage": "请保存工作",
                    "allowSkip": True,
                    "waitSeconds": 30,
                    "enabled": True,
                }
            ),
        )

        for card in cards:
            surfaces = (
                card.expandCard,
                card.expandCard.viewport(),
                card.expandCard.scrollWidget,
                card.expandCard.view,
                card.expandCard.card,
            )

            with self.subTest(card=type(card).__name__):
                for surface in surfaces:
                    self.assertFalse(surface.autoFillBackground())
                    self.assertTrue(
                        surface.testAttribute(
                            Qt.WidgetAttribute.WA_TranslucentBackground
                        )
                    )

            card.close()
