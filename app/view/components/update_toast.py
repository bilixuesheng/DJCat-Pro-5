"""Update Toast：Client Update 下载期间主窗口右下角始终同一张的卡片。

结构借鉴 Ghost Downloader 3 的 `app/view/components/progress_toast.py`
（XiaoYouChR/Ghost-Downloader-3，commit 13b1565，与本项目同为 GPL-3.0）：继承 InfoBar，
在卡片底边画一条被圆角裁住的进度线。确定进度的动画和不确定态沿用应用市场按钮进度线的约定。
它不知道下载、版本或安装的规则，标题和正文由 MainWindow 给出。
"""

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    InfoBar,
    InfoBarIcon,
    InfoBarManager,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    isDarkTheme,
    themeColor,
)

BAR_HEIGHT = 3
CORNER_RADIUS = 6  # 与 InfoBar 样式表的 border-radius 一致
TRACK_ALPHA = 75
PROGRESS_ANIMATION_MS = 150
INDETERMINATE_INTERVAL_MS = 16
INDETERMINATE_PERIOD_MS = 1200

# 与 InfoBar 成功、错误图标的填充色一致，(浅色, 深色)
SUCCESS_COLORS = (QColor("#0F7B0F"), QColor("#6CCB5F"))
ERROR_COLORS = (QColor("#C42B1C"), QColor("#FF99A4"))

DOWNLOADING = "downloading"
COMPLETED = "completed"
FAILED = "failed"


class UpdateToast(InfoBar):
    installClicked = Signal()
    retryClicked = Signal()

    def __init__(self, parent):
        # 信息图标让样式表取 type="Info"，即中性底色；换状态只换图标，底色不跟着闪。
        super().__init__(
            icon=InfoBarIcon.INFORMATION,
            title="",
            content="",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            duration=-1,
            position=InfoBarPosition.BOTTOM_RIGHT,
            parent=parent,
        )
        self._state = DOWNLOADING
        self._progress = None
        self._displayProgress = 0.0
        self._indeterminateOffset = 0.0
        self._initWidget()
        self._initLayout()
        self._bind()

    def _initWidget(self):
        self.titleLabel.show()
        self.contentLabel.show()
        self._progressAnimation = QPropertyAnimation(self, b"displayProgress", self)
        self._progressAnimation.setDuration(PROGRESS_ANIMATION_MS)
        self._indeterminateTimer = QTimer(self)
        self._indeterminateTimer.setInterval(INDETERMINATE_INTERVAL_MS)
        # 按钮放进一个容器：下载中整个容器隐藏，布局里不留按钮之间的空隙。
        self._buttonBox = QWidget(self)
        self.installButton = PrimaryPushButton(FIF.UPDATE, "立即更新", self._buttonBox)
        self.laterButton = PushButton("稍后更新", self._buttonBox)
        self.retryButton = PushButton(FIF.SYNC, "重试", self._buttonBox)
        self._buttonBox.hide()

    def _initLayout(self):
        buttonLayout = QHBoxLayout(self._buttonBox)
        buttonLayout.setContentsMargins(16, 0, 0, 0)
        buttonLayout.setSpacing(6)
        buttonLayout.addWidget(self.installButton)
        buttonLayout.addWidget(self.laterButton)
        buttonLayout.addWidget(self.retryButton)
        self.widgetLayout.addWidget(self._buttonBox, 0, Qt.AlignmentFlag.AlignVCenter)

    def _bind(self):
        self._indeterminateTimer.timeout.connect(self._advanceIndeterminate)
        self.installButton.clicked.connect(self.installClicked)
        self.laterButton.clicked.connect(self.close)
        self.retryButton.clicked.connect(self.retryClicked)

    def startDownload(self, title, content, widestContent):
        """进入下载中：没有百分比前显示不确定线，正文宽度按最长的进度文字预留。"""
        self._state = DOWNLOADING
        self.iconWidget.icon = InfoBarIcon.INFORMATION
        self.iconWidget.update()
        self.closeButton.hide()
        self._buttonBox.hide()
        self.contentLabel.ensurePolished()
        self.contentLabel.setMinimumWidth(
            self.contentLabel.fontMetrics().horizontalAdvance(widestContent)
        )
        self.title = title
        self.content = content
        self._setProgress(None)
        self._refresh()

    def setDownloadProgress(self, content, progress=None):
        """progress 是 0–100；None 表示还没有有效百分比，显示不确定线。"""
        if self._state != DOWNLOADING:
            return
        self._setProgress(progress)
        # 宽度已按最长的进度文字预留，换文字不用重新量尺寸。
        self.content = content
        self.contentLabel.setText(content)

    def finishDownload(self, title, content):
        self._finish(
            COMPLETED,
            InfoBarIcon.SUCCESS,
            title,
            content,
            (self.installButton, self.laterButton),
        )

    def failDownload(self, title, content):
        self._finish(FAILED, InfoBarIcon.ERROR, title, content, (self.retryButton,))

    def _finish(self, state, icon, title, content, buttons):
        self._state = state
        self._progressAnimation.stop()
        self._indeterminateTimer.stop()
        self.iconWidget.icon = icon
        self.iconWidget.update()
        self.contentLabel.setMinimumWidth(0)
        self.title = title
        self.content = content
        # 容器藏着时再换按钮：容器可见时换，卡片会被换的那一刻同时可见的按钮撑宽，事后再量也缩不回去。
        self._buttonBox.hide()
        for button in (self.installButton, self.laterButton, self.retryButton):
            button.setVisible(button in buttons)
        self.closeButton.show()
        self._buttonBox.show()
        self._updateBar()
        self._refresh()

    def _setProgress(self, progress):
        if progress is None:
            self._progressAnimation.stop()
            self._progress = None
            self._displayProgress = 0.0
            if not self._indeterminateTimer.isActive():
                self._indeterminateOffset = 0.0
                self._indeterminateTimer.start()
            self._updateBar()
            return

        self._indeterminateTimer.stop()
        target = max(0.0, min(100.0, float(progress)))
        if self._progress == target:
            return
        self._progress = target
        # 从当前显示值追到最新目标值，连续更新不排队播放过时进度。
        self._progressAnimation.stop()
        self._progressAnimation.setStartValue(self._displayProgress)
        self._progressAnimation.setEndValue(target)
        self._progressAnimation.start()

    def _advanceIndeterminate(self):
        step = INDETERMINATE_INTERVAL_MS / INDETERMINATE_PERIOD_MS
        self._indeterminateOffset = (self._indeterminateOffset + step) % 1.0
        self._updateBar()

    def _getDisplayProgress(self):
        return self._displayProgress

    def _setDisplayProgress(self, progress):
        self._displayProgress = float(progress)
        self._updateBar()

    displayProgress = Property(float, _getDisplayProgress, _setDisplayProgress)

    def _updateBar(self):
        self.update(0, self.height() - BAR_HEIGHT, self.width(), BAR_HEIGHT)

    def _refresh(self):
        self._adjustText()
        # _adjustText() 里的 adjustSize() 先量尺寸、后 activate() 布局，而子布局换了按钮或文字后
        # 的尺寸缓存要到 activate() 才失效，那一次量到的是旧尺寸，所以再量一次。
        self.adjustSize()
        if self.isHidden():
            self.show()
            return
        parent = self.parentWidget()
        if parent is None or not self.isVisible():
            return
        # InfoBarManager 只在父窗口缩放时重排；卡片换状态后自己的尺寸变了，照它的规则重摆一次。
        # 滑入或下落动画还在跑时只改终点：OutQuad 提前几帧就到了终点坐标，动画却还没停，
        # 这时直接 move()，剩下的几帧会把卡片拉回按旧宽度算的位置。
        manager = InfoBarManager.make(self.position)
        for bar in manager.infoBars.get(parent, ()):
            position = manager._pos(bar)
            animations = [
                animation
                for animation in (bar.property("slideAni"), bar.property("dropAni"))
                if animation is not None
                and animation.state() == QAbstractAnimation.State.Running
            ]
            for animation in animations:
                animation.setEndValue(position)
            if not animations:
                bar.move(position)

    def closeEvent(self, event):
        self._progressAnimation.stop()
        self._indeterminateTimer.stop()
        super().closeEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        width = float(self.width())
        track = QRectF(0.0, self.height() - BAR_HEIGHT, width, BAR_HEIGHT)
        if self._state == COMPLETED:
            bars = ((track, self._themeColor(SUCCESS_COLORS)),)
        elif self._state == FAILED:
            bars = ((track, self._themeColor(ERROR_COLORS)),)
        else:
            color = QColor(themeColor())
            trackColor = QColor(color)
            trackColor.setAlpha(TRACK_ALPHA)
            if self._progress is None:
                segment = max(24.0, width * 0.28)
                x = -segment + (width + segment) * self._indeterminateOffset
                fill = QRectF(x, track.top(), segment, BAR_HEIGHT)
            else:
                fill = QRectF(
                    0.0, track.top(), width * self._displayProgress / 100.0, BAR_HEIGHT
                )
            bars = ((track, trackColor), (fill, color))

        card = QPainterPath()
        card.addRoundedRect(QRectF(self.rect()), CORNER_RADIUS, CORNER_RADIUS)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for rect, color in bars:
            if rect.width() <= 0:
                continue
            bar = QPainterPath()
            bar.addRect(rect)
            painter.fillPath(card.intersected(bar), color)

    @staticmethod
    def _themeColor(colors):
        return colors[1] if isDarkTheme() else colors[0]
