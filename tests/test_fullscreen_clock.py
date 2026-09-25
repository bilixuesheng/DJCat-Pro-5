from unittest import TestCase

from PySide6.QtCore import QTime
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Flyout, PushButton

from app.config.cfg import HOME_CARD_SCHEMA_VERSION, cfg, migrateConfig
from app.view.pages.fullscreen_clock import FullscreenClockWindow
from tests.support import isolateCfg


class FullscreenClockTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

    def setUp(self):
        isolateCfg(self)
        self.window = FullscreenClockWindow()
        self.window.resize(720, 240)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()

    def testDisplaysCurrentSystemTimeWithoutCountdownControls(self):
        self.window._refreshTime()

        self.assertEqual(self.window.titleLabel.text(), "当前时间")
        self.assertRegex(self.window.timeLabel.text(), r"^\d{2} : \d{2} : \d{2}$")
        displayed = QTime.fromString(self.window.timeLabel.text(), "HH : mm : ss")
        difference = abs(displayed.secsTo(QTime.currentTime()))
        self.assertLessEqual(min(difference, 86400 - difference), 1)
        self.assertFalse(hasattr(self.window, "btnPause"))
        self.assertFalse(hasattr(self.window, "btnReset"))
        self.assertEqual(
            [self.window.btnWin.text(), self.window.btnClose.text()],
            ["窗口化", "关闭"],
        )

    def testWindowUsesIndependentConfigurationDefaults(self):
        self.assertEqual(
            cfg.fullscreenClockActionButtonPosition.defaultValue,
            "右下角",
        )
        self.assertTrue(cfg.showMainWindowAfterFullscreenClock.defaultValue)
        self.assertTrue(cfg.confirmBeforeCloseFullscreenClock.defaultValue)
        self.assertFalse(cfg.fullscreenClockStartWindowed.defaultValue)
        self.assertIsNot(
            cfg.fullscreenClockBackgroundMode,
            cfg.countdownBackgroundMode,
        )

    def testStartClockUsesConfiguredWindowMode(self):
        value = cfg.fullscreenClockStartWindowed.value
        try:
            for startWindowed in (False, True):
                with self.subTest(startWindowed=startWindowed):
                    cfg.set(
                        cfg.fullscreenClockStartWindowed,
                        startWindowed,
                        save=False,
                    )
                    self.window.startClock()
                    self.app.processEvents()

                    self.assertEqual(self.window.isWindowed, startWindowed)
                    self.assertEqual(
                        self.window.titleLabel.isHidden(),
                        startWindowed,
                    )
        finally:
            cfg.set(cfg.fullscreenClockStartWindowed, value, save=False)

    def testWindowedModeKeepsOnlyTimeAndCornerButtons(self):
        self.window.isWindowed = False
        self.window._setupCornerButtons()

        self.window.toggleWindowMode()
        self.app.processEvents()

        self.assertTrue(self.window.isWindowed)
        self.assertTrue(self.window.titleLabel.isHidden())
        self.assertFalse(self.window.timeLabel.isHidden())
        self.assertEqual(self.window.contentsRect().size().toTuple(), (600, 190))
        self.assertEqual(self.window.timeLabel.font().pixelSize(), 85)
        self.assertRegex(
            self.window.timeLabel.text(),
            r"^\d{2}\u2009:\u2009\d{2}\u2009:\u2009\d{2}$",
        )

    def testTimeFontFitsNarrowFullscreenWidth(self):
        self.window.resize(320, 240)
        self.window.timeLabel.setText("23 : 59 : 59")

        self.window._applyFonts(self.window.height())

        margins = self.window.vBoxLayout.contentsMargins()
        available = self.window.width() - margins.left() - margins.right()
        width = QFontMetrics(self.window.timeLabel.font()).horizontalAdvance(
            self.window.timeLabel.text()
        )
        self.assertLessEqual(width, available)

    def testCloseButtonUsesClockConfirmationSetting(self):
        value = cfg.confirmBeforeCloseFullscreenClock.value
        try:
            cfg.set(cfg.confirmBeforeCloseFullscreenClock, True)
            self.window._setupCornerButtons()
            self.window.btnClose.click()
            self.app.processEvents()

            flyout = next(
                child
                for child in self.window.findChildren(Flyout)
                if child.isVisible()
            )
            self.assertEqual(
                flyout.view.contentLabel.text(),
                "关闭当前的全屏时钟？",
            )
            cancelButton = next(
                button
                for button in flyout.findChildren(PushButton)
                if button.text() == "取消"
            )
            cancelButton.click()
            self.app.processEvents()
            self.assertTrue(self.window.isVisible())
        finally:
            cfg.set(cfg.confirmBeforeCloseFullscreenClock, value)


class FullscreenClockMigrationTest(TestCase):
    def testExistingHomeCardsGainClockOnceAfterCountdown(self):
        legacy = ["全屏投送", "考试倒计时", "定时关机", "定时播报"]
        cfg.set(cfg.homeCardOrder, legacy, save=False)
        cfg.set(cfg.visibleDefaultHomeCards, legacy, save=False)
        cfg.set(cfg.homeCardSchemaVersion, 0, save=False)

        migrateConfig()

        expected = [
            "全屏投送",
            "考试倒计时",
            "全屏时钟",
            "定时关机",
            "定时播报",
            "自动任务",
        ]
        self.assertEqual(cfg.homeCardOrder.value, expected)
        self.assertEqual(cfg.visibleDefaultHomeCards.value, expected)
        self.assertEqual(
            cfg.homeCardSchemaVersion.value,
            HOME_CARD_SCHEMA_VERSION,
        )

        cfg.set(
            cfg.visibleDefaultHomeCards,
            [name for name in expected if name != "全屏时钟"],
            save=False,
        )
        migrateConfig()
        self.assertNotIn("全屏时钟", cfg.visibleDefaultHomeCards.value)

    def testVersionOneHomeCardsGainScheduledTaskAfterBroadcast(self):
        legacy = [
            "考试倒计时",
            "定时播报",
            "全屏投送",
            "全屏时钟",
            "定时关机",
        ]
        cfg.set(cfg.homeCardOrder, legacy, save=False)
        cfg.set(cfg.visibleDefaultHomeCards, legacy, save=False)
        cfg.set(cfg.homeCardSchemaVersion, 1, save=False)

        migrateConfig()

        expected = [
            "考试倒计时",
            "定时播报",
            "自动任务",
            "全屏投送",
            "全屏时钟",
            "定时关机",
        ]
        self.assertEqual(cfg.homeCardOrder.value, expected)
        self.assertEqual(cfg.visibleDefaultHomeCards.value, expected)
        self.assertEqual(
            cfg.homeCardSchemaVersion.value,
            HOME_CARD_SCHEMA_VERSION,
        )

        migrateConfig()
        self.assertEqual(cfg.homeCardOrder.value, expected)
