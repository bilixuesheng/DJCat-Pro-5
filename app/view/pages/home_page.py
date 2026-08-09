import os

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QScroller,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    FlowLayout,
    IconWidget,
    SubtitleLabel,
    TitleLabel,
    ToolButton,
    qconfig,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.cfg import (
    BANNER_IMAGE_PRESETS,
    DEFAULT_BANNER_IMAGE_SOURCE,
    cfg,
)
from app.config.paths import ASSET_DIR
from app.view.components.scroll_area import ScrollArea


class ActionCard(CardWidget):
    dragStarted = Signal(object, QPoint)
    dragMoved = Signal(object, QPoint)
    dragFinished = Signal(object)

    def __init__(self, icon, title, content, parent=None):
        # CardWidget 构造期间可能进入 event()，拖动状态需先初始化。
        self._editing = False
        self._dragging = False
        self._drag_position = QPoint()
        self._press_position = None
        super().__init__(parent)
        self.setFixedSize(210, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setClickEnabled(True)

        qconfig.themeColor.valueChanged.connect(self.update)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 12, 16)
        top_layout = QHBoxLayout()
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(18, 18)
        title_label = TitleLabel(title, self)
        self.deleteButton = ToolButton(FIF.DELETE, self)
        self.deleteButton.setFixedSize(24, 24)
        self.deleteButton.setEnabled(False)
        self.deleteButton.setToolTip("系统卡片不可删除")
        self.deleteButton.setAccessibleName(f"删除{title}")
        self.deleteButton.setStyleSheet("""
            ToolButton {
                border: none;
                border-radius: 12px;
                background: #d13438;
            }
            ToolButton:disabled {
                background: rgba(128, 128, 128, 0.35);
            }
        """)
        self.deleteButton.hide()
        top_layout.addWidget(icon_widget)
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

    def _start_dragging(self, global_position):
        self._dragging = True
        self._drag_position = global_position
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.dragStarted.emit(self, global_position)

    def _finish_dragging(self):
        if not self._dragging:
            return
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.dragFinished.emit(self)

    def event(self, event):
        if self._editing and event.type() == QEvent.Type.TouchBegin:
            point = event.points()[0]
            self._start_dragging(point.globalPosition().toPoint())
            event.accept()
            return True
        if self._editing and event.type() == QEvent.Type.TouchUpdate:
            if self._dragging and event.points():
                position = event.points()[0].globalPosition().toPoint()
                if position == self._drag_position:
                    event.accept()
                    return True
                self._drag_position = position
                self.dragMoved.emit(
                    self,
                    position,
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
            self._start_dragging(event.globalPosition().toPoint())
            event.accept()
            return
        self._press_position = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            position = event.globalPosition().toPoint()
            if position != self._drag_position:
                self._drag_position = position
                self.dragMoved.emit(self, position)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._editing:
            self._finish_dragging()
            event.accept()
            return
        release_position = event.globalPosition().toPoint()
        should_click = (
            self._press_position is not None
            and self.rect().contains(event.position().toPoint())
            and (release_position - self._press_position).manhattanLength()
            < QApplication.startDragDistance()
        )
        self._press_position = None
        if not should_click:
            self.isPressed = False
            self._updateBackgroundColor()
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
        source = cfg.bannerImageSource.value
        if source in BANNER_IMAGE_PRESETS:
            return str(ASSET_DIR / BANNER_IMAGE_PRESETS[source])

        path = cfg.bannerImagePath.value
        if path and os.path.exists(path):
            return path
        return str(
            ASSET_DIR / BANNER_IMAGE_PRESETS[DEFAULT_BANNER_IMAGE_SOURCE]
        )

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
        self._drag_offset = QPoint()
        self._drag_target = None
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
        self.flowLayout = FlowLayout(self.cardsWidget, needAni=True)
        self.flowLayout.setContentsMargins(20, 10, 20, 20)
        self.flowLayout.setAnimation(180, QEasingCurve.Type.OutCubic)
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
            card.dragStarted.connect(self._startCardDrag)
            card.dragMoved.connect(self._moveCard)
            card.dragFinished.connect(self._finishCardDrag)

        self._renderCards()
        self.vBoxLayout.addStretch(1)
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()
        self.container.setStyleSheet("QWidget{background: transparent;}")
        self.dragPreview = QLabel(self.viewport())
        self.dragPreview.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.dragPreview.hide()

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
        self.flowLayout.removeAllWidgets()
        for name in self._card_order:
            card = self.all_cards[name]
            self.flowLayout.addWidget(card)
            card.show()

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

    def _startCardDrag(self, card, global_position):
        self._drag_target = None
        self._drag_offset = global_position - card.mapToGlobal(QPoint())
        self.dragPreview.setPixmap(card.grab())
        self.dragPreview.resize(card.size())
        self._moveDragPreview(global_position)
        self.dragPreview.show()
        self.dragPreview.raise_()
        effect = QGraphicsOpacityEffect(card)
        effect.setOpacity(0.2)
        card.setGraphicsEffect(effect)

    def _moveDragPreview(self, global_position):
        self.dragPreview.move(
            self.viewport().mapFromGlobal(global_position - self._drag_offset)
        )

    def _moveCard(self, card, global_position):
        self._moveDragPreview(global_position)
        position = self.cardsWidget.mapFromGlobal(global_position)
        hit_margin = 32
        target = min(
            (
                other
                for other in self.all_cards.values()
                if other is not card
                and other.geometry()
                .adjusted(-hit_margin, -hit_margin, hit_margin, hit_margin)
                .contains(position)
            ),
            key=lambda other: (
                other.geometry().center() - position
            ).manhattanLength(),
            default=None,
        )
        if target is None:
            self._drag_target = None
            return
        if target is self._drag_target:
            return
        self._drag_target = target

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
        # FlowLayout 的公开插入接口会二次移除同布局控件，需同步移动现有动画项。
        item = self.flowLayout._items.pop(from_index)
        animation = self.flowLayout._anis.pop(from_index)
        self.flowLayout._items.insert(to_index, item)
        self.flowLayout._anis.insert(to_index, animation)
        self.flowLayout.setGeometry(self.flowLayout.geometry())

    def _finishCardDrag(self, card):
        self.dragPreview.hide()
        card.setGraphicsEffect(None)
        self._saveCardOrder()

    def _saveCardOrder(self):
        if cfg.homeCardOrder.value != self._card_order:
            cfg.set(cfg.homeCardOrder, list(self._card_order))

    def updateBannerVisibility(self):
        if cfg.showBanner.value:
            self.titleWidget.hide()
            self.banner.show()
        else:
            self.banner.hide()
            self.titleWidget.show()
