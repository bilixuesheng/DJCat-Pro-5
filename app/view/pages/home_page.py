import os

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScroller,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    IconWidget,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
    qconfig,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import cfg
from app.config.paths import ASSET_DIR
from app.view.components.scroll_area import ScrollArea


class ActionCard(CardWidget):
    dragMoved = Signal(object, QPoint)
    dragFinished = Signal()

    def __init__(self, icon, title, content, parent=None):
        # CardWidget 构造期间可能进入 event()，拖动状态需先初始化。
        self._editing = False
        self._dragging = False
        super().__init__(parent)
        self.setFixedHeight(132)
        self.setMinimumWidth(210)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setClickEnabled(True)

        qconfig.themeColor.valueChanged.connect(self.update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 14, 16)
        layout.setSpacing(10)
        top_layout = QHBoxLayout()
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(24, 24)
        title_label = SubtitleLabel(title, self)
        self.deleteButton = ToolButton(FIF.DELETE, self)
        self.deleteButton.setFixedSize(26, 26)
        self.deleteButton.setEnabled(False)
        self.deleteButton.setToolTip("系统卡片不可删除")
        self.deleteButton.setAccessibleName(f"删除{title}")
        self.deleteButton.setStyleSheet("""
            ToolButton {
                border: none;
                border-radius: 13px;
                background: #d13438;
            }
            ToolButton:disabled {
                background: rgba(128, 128, 128, 0.35);
            }
        """)
        self.deleteButton.hide()
        top_layout.addWidget(icon_widget)
        top_layout.addSpacing(4)
        top_layout.addWidget(title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.deleteButton)
        content_label = BodyLabel(content, self)
        content_label.setWordWrap(True)
        layout.addLayout(top_layout)
        layout.addWidget(content_label)
        layout.addStretch(1)

    def setEditing(self, editing):
        self._editing = editing
        self._dragging = False
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, editing)
        self.deleteButton.setVisible(editing)
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if editing
            else Qt.CursorShape.PointingHandCursor
        )
        self.update()

    def _start_dragging(self):
        self._dragging = True
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _finish_dragging(self):
        if not self._dragging:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.dragFinished.emit()

    def event(self, event):
        if self._editing and event.type() == QEvent.Type.TouchBegin:
            self._start_dragging()
            event.accept()
            return True
        if self._editing and event.type() == QEvent.Type.TouchUpdate:
            if self._dragging and event.points():
                self.dragMoved.emit(
                    self,
                    event.points()[0].globalPosition().toPoint(),
                )
            event.accept()
            return True
        if self._editing and event.type() in (
            QEvent.Type.TouchEnd,
            QEvent.Type.TouchCancel,
        ):
            self._finish_dragging()
            event.accept()
            return True
        return super().event(event)

    def mousePressEvent(self, event):
        if self._editing and event.button() == Qt.MouseButton.LeftButton:
            self._start_dragging()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.dragMoved.emit(self, event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._editing:
            self._finish_dragging()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = (
            qconfig.themeColor.value
            if self._editing or self.isHover
            else QColor(128, 128, 128, 55)
        )
        width = 2 if self._editing or self.isHover else 1
        painter.setPen(QPen(color, width))
        inset = width / 2 + 1
        painter.drawRoundedRect(
            QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2),
            10,
            10,
        )

class BannerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(300)

        self._cached_pixmap = None  # 预渲染的最终图片
        self._cache_size = None     # 缓存对应的窗口尺寸

        self.vBoxLayout = QVBoxLayout(self)
        self.galleryLabel = QLabel('主页', self)
        self.galleryLabel.setStyleSheet("font-size: 32px; font-weight: bold; color: white;")
        self.vBoxLayout.setContentsMargins(30, 20, 30, 0)
        self.vBoxLayout.addWidget(self.galleryLabel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        cfg.bannerImageSource.valueChanged.connect(self._onConfigChanged)
        cfg.bannerImagePath.valueChanged.connect(self._onConfigChanged)
        cfg.bannerBrightness.valueChanged.connect(self._onConfigChanged)
        cfg.bannerScaleMode.valueChanged.connect(self._onConfigChanged)

    def _onConfigChanged(self):
        self._invalidate_cache()
        self.update()  # 触发布局重绘

    def get_image_path(self):
        preset_path = str(ASSET_DIR / "home.png")
        if cfg.bannerImageSource.value == "预设: 树人门":
            return preset_path
        else:
            path = cfg.bannerImagePath.value
            if not path or not os.path.exists(path):
                return preset_path
            return path

    def _invalidate_cache(self):
        self._cached_pixmap = None
        self._cache_size = None

    def _create_cached_pixmap(self, width, height):
        img_path = self.get_image_path()
        if not os.path.exists(img_path):
            return None

        pixmap = QPixmap(img_path)
        mode = cfg.bannerScaleMode.value
        w, h = width, height

        temp_pixmap = QPixmap(w, h)
        temp_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(temp_pixmap)
        painter.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform)

        if mode == "拉伸":
            source_pix = pixmap.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
            draw_x, draw_y = 0, 0
        else:
            source_pix = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                       Qt.TransformationMode.SmoothTransformation)
            draw_x = (w - source_pix.width()) // 2
            if mode == "缩放(上)": draw_y = 0
            elif mode == "缩放(下)": draw_y = h - source_pix.height()
            else: draw_y = (h - source_pix.height()) // 2

        painter.drawPixmap(draw_x, draw_y, source_pix)

        brightness = cfg.bannerBrightness.value
        if brightness < 100:
            alpha = int(255 * (100 - brightness) / 100)
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, alpha))

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        gradient = QLinearGradient(0, 0, 0, h)
        gradient.setColorAt(0.0, QColor(0, 0, 0, 255))
        gradient.setColorAt(0.6, QColor(0, 0, 0, 255))
        gradient.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, w, h, gradient)
        painter.end()

        return temp_pixmap

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 10, 10)
        painter.setClipPath(path)

        if (self._cached_pixmap is None or
            self._cache_size != (w, h) or
            self.isConfigurationChanged()):

            self._cached_pixmap = self._create_cached_pixmap(w, h)
            self._cache_size = (w, h)

        if self._cached_pixmap:
            painter.drawPixmap(0, 0, self._cached_pixmap)
        else:
            painter.fillPath(path, qconfig.themeColor.value)

    def resizeEvent(self, event):
        self._invalidate_cache()
        super().resizeEvent(event)

    def isConfigurationChanged(self):
        return False  # 简化处理，依赖_updateCache调用触发


class HomePage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._editing_cards = False
        self._card_order = []
        self._card_columns = 2
        self.setObjectName("HomePage")
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(10)

        self.titleWidget = QWidget(self.container)
        self.titleLayout = QVBoxLayout(self.titleWidget)
        self.titleLayout.setContentsMargins(30, 20, 30, 10)
        self.normalTitle = TitleLabel("主页", self.titleWidget)
        self.titleLayout.addWidget(self.normalTitle)
        self.vBoxLayout.addWidget(self.titleWidget)
        self.banner = BannerWidget(self.container)
        self.vBoxLayout.addWidget(self.banner)

        cfg.showBanner.valueChanged.connect(self.updateBannerVisibility)
        self.updateBannerVisibility()

        self.headerLayout = QHBoxLayout()
        self.headerLayout.setContentsMargins(30, 0, 30, 0)
        self.subTitle = SubtitleLabel("常用功能", self.container)
        self.editHint = BodyLabel("拖动卡片调整位置", self.container)
        self.editHint.hide()
        self.sortBtn = ToolButton(FIF.EDIT, self.container)
        self.sortBtn.setToolTip("调整卡片顺序")
        self.sortBtn.setAccessibleName("调整卡片顺序")
        self.sortBtn.clicked.connect(self._toggleCardEditing)
        self.headerLayout.addWidget(self.subTitle)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.editHint)
        self.headerLayout.addWidget(self.sortBtn)
        self.vBoxLayout.addLayout(self.headerLayout)

        self.cardsWidget = QWidget(self.container)
        self.cardsWidget.setMaximumWidth(820)
        self.cardsLayout = QGridLayout(self.cardsWidget)
        self.cardsLayout.setContentsMargins(30, 10, 30, 20)
        self.cardsLayout.setHorizontalSpacing(16)
        self.cardsLayout.setVerticalSpacing(16)
        self.cardsLayout.setColumnStretch(0, 1)
        self.cardsLayout.setColumnStretch(1, 1)
        self.cardsWidget.setStyleSheet("background: transparent;")
        self.vBoxLayout.addWidget(self.cardsWidget)

        self.all_cards = {
            "全屏投送": ActionCard(
                FIF.FULL_SCREEN,
                "全屏投送",
                "将信息以大字全屏展示",
                self.cardsWidget,
            ),
            "考试倒计时": ActionCard(
                FIF.CALENDAR,
                "考试倒计时",
                "设定考试时长并全屏显示倒计时",
                self.cardsWidget,
            ),
            "定时播报": ActionCard(
                FIF.MEGAPHONE,
                "定时播报",
                "设置每日定点语音播报时间或播放音频",
                self.cardsWidget,
            ),
            "定时关机": ActionCard(
                FIF.POWER_BUTTON,
                "定时关机",
                "设置指定时间提示或自动关闭计算机",
                self.cardsWidget,
            )
        }
        for card in self.all_cards.values():
            card.dragMoved.connect(self._moveCard)
            card.dragFinished.connect(self._saveCardOrder)

        self._renderCards()
        self.vBoxLayout.addStretch(1)
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self.container.setStyleSheet("QWidget{background: transparent;}")

    def _renderCards(self):
        current_order = [
            name for name in cfg.homeCardOrder.value if name in self.all_cards
        ]
        for name in self.all_cards:
            if name not in current_order:
                current_order.append(name)
        self._card_order = current_order
        self._layoutCards()

    def _layoutCards(self):
        while self.cardsLayout.count():
            self.cardsLayout.takeAt(0)
        self.cardsLayout.setColumnStretch(
            1,
            1 if self._card_columns == 2 else 0,
        )
        for index, name in enumerate(self._card_order):
            card = self.all_cards[name]
            self.cardsLayout.addWidget(
                card,
                index // self._card_columns,
                index % self._card_columns,
            )
            card.show()
        self.cardsLayout.activate()

    def _toggleCardEditing(self):
        self._editing_cards = not self._editing_cards
        self.editHint.setVisible(self._editing_cards)
        self.sortBtn.setIcon(FIF.ACCEPT if self._editing_cards else FIF.EDIT)
        self.sortBtn.setToolTip(
            "完成调整" if self._editing_cards else "调整卡片顺序"
        )
        self.sortBtn.setAccessibleName(self.sortBtn.toolTip())
        for card in self.all_cards.values():
            card.setEditing(self._editing_cards)

        if self._editing_cards:
            QScroller.scroller(self.viewport()).stop()
        else:
            self._saveCardOrder()

    def _moveCard(self, card, global_position):
        position = self.cardsWidget.mapFromGlobal(global_position)
        target = next(
            (
                other
                for other in self.all_cards.values()
                if other is not card and other.geometry().contains(position)
            ),
            None,
        )
        if target is None:
            return

        card_name = next(
            name for name, value in self.all_cards.items() if value is card
        )
        target_name = next(
            name for name, value in self.all_cards.items() if value is target
        )
        from_index = self._card_order.index(card_name)
        to_index = self._card_order.index(target_name)
        self._card_order.pop(from_index)
        self._card_order.insert(to_index, card_name)
        self._layoutCards()

    def _saveCardOrder(self):
        if cfg.homeCardOrder.value != self._card_order:
            cfg.set(cfg.homeCardOrder, list(self._card_order))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "all_cards"):
            return
        columns = 1 if self.viewport().width() < 520 else 2
        if columns != self._card_columns:
            self._card_columns = columns
            self._layoutCards()

    def updateBannerVisibility(self):
        if cfg.showBanner.value:
            self.titleWidget.hide()
            self.banner.show()
        else:
            self.banner.hide()
            self.titleWidget.show()
