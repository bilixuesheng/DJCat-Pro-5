import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import InfoBarPosition

from app.config.cfg import cfg
from app.view.pages.app_store_page import AppStorePage, StoreAppCard
from app.view.pages.home_page import HomePage


def application(index, recommended=False):
    return {
        "id": index,
        "name": f"应用 {index:02d}",
        "developer": "开发者",
        "description": f"第 {index} 个测试应用",
        "version": "2" if index == 1 else "1",
        "download_url": f"https://example.com/{index}.zip",
        "icon_url": f"https://example.com/{index}.png",
        "install_dir": f"app-{index}",
        "recommended": recommended,
        "open_action": {
            "type": "program",
            "target": "App.exe",
            "arguments": [],
        },
        "components": [
            {
                "id": index,
                "title": f"卡片 {index}",
                "description": "主页操作",
                "action": {
                    "type": "url",
                    "target": "https://example.com/action",
                    "arguments": [],
                },
            }
        ],
    }


class AppStorePageTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tempDir = tempfile.TemporaryDirectory()
        self.configFile = cfg.file
        self.pinnedCards = list(cfg.pinnedHomeCards.value)
        self.cardOrder = list(cfg.homeCardOrder.value)
        cfg.file = Path(self.tempDir.name) / "config.json"
        cfg.set(cfg.pinnedHomeCards, [])
        cfg.set(cfg.homeCardOrder, list(cfg.homeCardOrder.defaultValue))
        self.catalog = {
            "apps": [application(index, index <= 2) for index in range(1, 17)],
            "ads": [],
        }
        self.fetchPatch = patch(
            "app.view.pages.app_store_page.fetchCatalog", return_value=self.catalog
        )
        self.imagePatch = patch(
            "app.view.pages.app_store_page.fetchCachedImage", return_value=None
        )
        self.installPatch = patch(
            "app.view.pages.app_store_page.installedApplications",
            return_value=[{**application(1, True), "version": "1"}],
        )
        self.fetchCatalog = self.fetchPatch.start()
        self.imagePatch.start()
        self.installPatch.start()
        self.page = AppStorePage()
        self.page.resize(900, 650)

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.fetchPatch.stop()
        self.imagePatch.stop()
        self.installPatch.stop()
        cfg.set(cfg.pinnedHomeCards, self.pinnedCards)
        cfg.set(cfg.homeCardOrder, self.cardOrder)
        cfg.file = self.configFile
        self.tempDir.cleanup()

    def test_page_loads_once_and_defaults_to_installed_with_update_state(self):
        self.assertFalse(self.page.isLoaded)

        self.page.show()
        QTest.qWait(100)

        self.assertTrue(self.page.isLoaded)
        self.assertEqual(self.page.topPivot.currentRouteKey(), "installed")
        cardsWidget = self.page.installedLayout.itemAt(0).widget()
        cards = cardsWidget.findChildren(StoreAppCard)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].primaryButton.text(), "更新")

    def test_market_cards_and_details_expose_clear_information_hierarchy(self):
        self.page.show()
        QTest.qWait(100)

        self.assertIn("已安装 1", self.page.marketSummaryLabel.text())
        cardsWidget = self.page.installedLayout.itemAt(0).widget()
        card = cardsWidget.findChild(StoreAppCard)
        self.assertEqual(card.metaLabel.text(), "开发者 · 版本 2")

        self.page.showDetails(card.application)

        self.assertTrue(self.page.detailInfoCard.isVisible())
        self.assertTrue(self.page.detailComponentsCard.isVisible())

    def test_refined_market_cards_do_not_overlap_in_the_flow_layout(self):
        self.page.resize(1180, 760)
        self.page.show()
        QTest.qWait(100)
        self.page.topPivot.setCurrentItem("all")
        QTest.qWait(50)
        cardsWidget = self.page.catalogCardsSlot.itemAt(0).widget()
        cards = cardsWidget.findChildren(StoreAppCard)

        for index, card in enumerate(cards):
            for other in cards[index + 1 :]:
                self.assertFalse(card.geometry().intersects(other.geometry()))

    def test_failed_catalog_load_retries_without_rebuilding_the_page(self):
        self.fetchCatalog.side_effect = [None, self.catalog]

        self.page.show()
        QTest.qWait(100)
        overview = self.page.overview
        self.page.ensureLoaded()
        QTest.qWait(100)

        self.assertEqual(self.fetchCatalog.call_count, 2)
        self.assertIs(self.page.overview, overview)
        self.assertEqual(len(self.page._catalog["apps"]), 16)

    def test_notifications_are_shown_at_the_bottom_right(self):
        with patch("app.view.pages.app_store_page.InfoBar.error") as showError:
            self.page._showInfo("无法获取应用目录", "网络错误", error=True)

        self.assertEqual(
            showError.call_args.kwargs["position"],
            InfoBarPosition.BOTTOM_RIGHT,
        )

    def test_update_keeps_the_installed_action_until_install_completes(self):
        self.catalog["apps"][0]["open_action"] = {
            "type": "program",
            "target": "NewVersion.exe",
            "arguments": [],
        }

        self.page.show()
        QTest.qWait(100)

        application = self.page._mergedInstalled()[0]
        self.assertEqual(application["open_action"]["target"], "App.exe")

    def test_all_category_paginates_fifteen_and_search_resets_the_page(self):
        self.page.show()
        QTest.qWait(100)
        self.page.topPivot.setCurrentItem("all")
        self.page.categoryPivot.setCurrentItem("all")

        cardsWidget = self.page.catalogCardsSlot.itemAt(0).widget()
        self.assertEqual(len(cardsWidget.findChildren(StoreAppCard)), 15)
        self.page._setPage(2)
        cardsWidget = self.page.catalogCardsSlot.itemAt(0).widget()
        self.assertEqual(len(cardsWidget.findChildren(StoreAppCard)), 1)

        self.page.setSearchText("应用 16")

        self.assertEqual(self.page._page, 1)
        cardsWidget = self.page.catalogCardsSlot.itemAt(0).widget()
        cards = cardsWidget.findChildren(StoreAppCard)
        self.assertEqual([card.application["id"] for card in cards], [16])

    def test_installed_component_can_be_pinned_and_appears_on_home(self):
        self.page.show()
        QTest.qWait(100)
        app = self.catalog["apps"][0]

        self.page._pinComponent(app, app["components"][0])
        home = HomePage()
        try:
            self.assertIn("app:1:component:1", home.all_cards)
            self.assertTrue(home.all_cards["app:1:component:1"].deleteButton.isEnabled())
        finally:
            home.close()

    def test_multiple_advertisements_rotate_and_open_the_bound_application(self):
        self.page.show()
        QTest.qWait(100)
        catalog = {
            **self.catalog,
            "ads": [
                {
                    "id": 1,
                    "title": "广告 1",
                    "description": "介绍 1",
                    "image_url": "https://example.com/ad-1.png",
                    "app_id": 1,
                    "sort_order": 1,
                },
                {
                    "id": 2,
                    "title": "广告 2",
                    "description": "介绍 2",
                    "image_url": "https://example.com/ad-2.png",
                    "app_id": 2,
                    "sort_order": 2,
                },
            ],
        }
        self.page._onCatalogReceived(catalog)

        self.assertTrue(self.page.carousel.timer.isActive())
        self.page.carousel._next()
        self.assertEqual(self.page.carousel.flipView.currentIndex(), 1)
        opened = []
        self.page.carousel.appRequested.connect(opened.append)
        QTest.mouseClick(
            self.page.carousel.overlay.button,
            Qt.MouseButton.LeftButton,
        )
        self.assertEqual(opened, [2])


if __name__ == "__main__":
    import unittest

    unittest.main()
