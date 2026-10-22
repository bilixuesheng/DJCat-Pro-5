from PySide6.QtCore import QTime

from app.common import clock
from app.config.cfg import cfg
from app.view.pages.timer_window import TimerWindow


class FullscreenClockWindow(TimerWindow):
    backgroundItems = (
        cfg.fullscreenClockBackgroundMode,
        cfg.fullscreenClockBackgroundColor,
        cfg.fullscreenClockBackgroundImagePath,
        cfg.fullscreenClockBackgroundScaleMode,
    )
    actionPositionItem = cfg.fullscreenClockActionButtonPosition
    topmostInWindowedItem = cfg.fullscreenClockTopmostInWindowed
    topmostInFullscreenItem = cfg.fullscreenClockTopmostInFullscreen
    showTaskbarItem = cfg.showTaskbarInFullscreenClock
    confirmCloseItem = cfg.confirmBeforeCloseFullscreenClock
    closeMessage = "关闭当前的全屏时钟？"

    def __init__(self):
        super().__init__()
        self.titleLabel.setText("当前时间")
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._refreshTime)

    def startClock(self):
        self.transition.cancel()
        self.timer.stop()
        self.isWindowed = cfg.fullscreenClockStartWindowed.value
        self._refreshTime()
        self._setupCornerButtons()
        self._applyWindowState()

    def _refreshTime(self):
        # 显示 Calibrated Time，从不加 Time Offset：给学生看的是标准时间。
        moment = clock.calibratedNow()
        now = QTime(moment.hour, moment.minute, moment.second, moment.microsecond // 1000)
        timeFormat = (
            "HH : mm : ss"
            if self.isWindowed
            else "HH : mm : ss"
        )
        self.timeLabel.setText(now.toString(timeFormat))
        self._applyFonts(self.contentsRect().height())
        self.timer.start(max(1, 1000 - now.msec()))
