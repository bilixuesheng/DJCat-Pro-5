import os
import sys
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPainterPath, QLinearGradient
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from qfluentwidgets import (CardWidget, TitleLabel, BodyLabel, FlowLayout, IconWidget, qconfig)
from qfluentwidgets import FluentIcon as FIF

if sys.platform != "darwin":
    from qfluentwidgets import SmoothScrollArea as ScrollArea
else:
    from qfluentwidgets import ScrollArea

from app.common.config import cfg

class ActionCard(CardWidget):
    def __init__(self, icon, title, content, parent=None):
        super().__init__(parent)
        self.setFixedSize(210, 120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # === 动态跟随主题色 ===
        self._updateStyle()
        qconfig.themeColor.valueChanged.connect(self._updateStyle)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        top_layout = QHBoxLayout()
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(18, 18)
        title_label = TitleLabel(title, self)
        top_layout.addWidget(icon_widget)
        top_layout.addWidget(title_label)
        top_layout.addStretch(1)
        content_label = BodyLabel(content, self)
        content_label.setWordWrap(True)
        layout.addLayout(top_layout)
        layout.addWidget(content_label)
        layout.addStretch(1)

    def _updateStyle(self):
        """ 边框颜色跟随主题色动态变化 """
        theme_color = qconfig.themeColor.value.name()
        self.setStyleSheet(f"""
            ActionCard {{ border: 1px solid {theme_color}; border-radius: 8px; }}
            ActionCard:hover {{ border: 2px solid {theme_color}; }}
        """)

class BannerWidget(QWidget):
    """ 主页横幅画板 (支持真Alpha渐变透明) - 已优化性能 """
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(300)
        
        # === 【性能优化】引入缓存机制 ===
        self._cached_pixmap = None  # 预渲染的最终图片
        self._cache_size = None     # 缓存对应的窗口尺寸
        
        self.vBoxLayout = QVBoxLayout(self)
        self.galleryLabel = QLabel('主页', self)
        self.galleryLabel.setStyleSheet("font-size: 32px; font-weight: bold; color: white;")
        self.vBoxLayout.setContentsMargins(30, 40, 30, 0)
        self.vBoxLayout.addWidget(self.galleryLabel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        cfg.bannerImageSource.valueChanged.connect(self._onConfigChanged)
        cfg.bannerImagePath.valueChanged.connect(self._onConfigChanged)
        cfg.bannerBrightness.valueChanged.connect(self._onConfigChanged)
        cfg.bannerScaleMode.valueChanged.connect(self._onConfigChanged)
    
    def _onConfigChanged(self):
        """当任何设置改变时触发重新渲染"""
        self._invalidate_cache()
        self.update()  # 触发布局重绘
    
    def get_image_path(self):
        preset_path = os.path.join(os.path.dirname(__file__), 'home.png')
        if cfg.bannerImageSource.value == "预设: 学校门口":
            return preset_path
        else:
            path = cfg.bannerImagePath.value
            if not path or not os.path.exists(path):
                return preset_path
            return path
    
    def _invalidate_cache(self):
        """使当前缓存失效"""
        self._cached_pixmap = None
        self._cache_size = None
    
    def _create_cached_pixmap(self, width, height):
        """一次性预渲染完整效果，后续直接绘制缓存图"""
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
        
        # 图片缩放
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
        
        # 绘制原图
        painter.drawPixmap(draw_x, draw_y, source_pix)
        
        # 亮度遮罩
        brightness = cfg.bannerBrightness.value
        if brightness < 100:
            alpha = int(255 * (100 - brightness) / 100)
            painter.fillRect(0, 0, w, h, QColor(0, 0, 0, alpha))
        
        # Alpha渐变蒙版
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
        
        # === 【圆角处理】必须保留！===
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 10, 10)
        painter.setClipPath(path)
        
        # === 【性能优化】检测窗口是否变化 ===
        if (self._cached_pixmap is None or 
            self._cache_size != (w, h) or 
            self.isConfigurationChanged()):
            
            self._cached_pixmap = self._create_cached_pixmap(w, h)
            self._cache_size = (w, h)
        
        # 绘制缓存后的图片（仅此一次！）
        if self._cached_pixmap:
            painter.drawPixmap(0, 0, self._cached_pixmap)
        else:
            # 备用背景色也跟随主题色
            painter.fillPath(path, qconfig.themeColor.value)
    
    def resizeEvent(self, event):
        # 窗口大小变化时使缓存失效
        self._invalidate_cache()
        super().resizeEvent(event)
    
    def isConfigurationChanged(self):
        # 可以添加更细粒度的配置变化检测
        return False  # 简化处理，依赖_updateCache调用触发


class HomePage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("HomePage")
        
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 36)
        self.vBoxLayout.setSpacing(10)
        
        self.titleWidget = QWidget(self.container)
        self.titleLayout = QVBoxLayout(self.titleWidget)
        self.titleLayout.setContentsMargins(30, 30, 30, 10)
        self.normalTitle = TitleLabel("主页", self.titleWidget)
        self.titleLayout.addWidget(self.normalTitle)
        self.vBoxLayout.addWidget(self.titleWidget)

        self.banner = BannerWidget(self.container)
        self.vBoxLayout.addWidget(self.banner)
        
        cfg.showBanner.valueChanged.connect(self.updateBannerVisibility)
        self.updateBannerVisibility()
        
        self.cardsWidget = QWidget(self.container)
        self.flowLayout = FlowLayout(self.cardsWidget)
        self.flowLayout.setContentsMargins(20, 20, 20, 20)
        self.cardsWidget.setStyleSheet("background: transparent;")
        
        self.flowLayout.addWidget(ActionCard(FIF.FULL_SCREEN, "全屏投送", "将当前画面全屏投送到目标设备", self.cardsWidget))
        self.flowLayout.addWidget(ActionCard(FIF.CALENDAR, "考试倒计时", "设定考试时间并在屏幕上显示倒计时", self.cardsWidget))
        self.flowLayout.addWidget(ActionCard(FIF.POWER_BUTTON, "定时关机", "设置指定时间自动关闭计算机", self.cardsWidget))

        self.vBoxLayout.addWidget(self.cardsWidget)
        self.vBoxLayout.addStretch(1)

        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.enableTransparentBackground()
        self.container.setStyleSheet("QWidget{background: transparent;}")

    def updateBannerVisibility(self):
        if cfg.showBanner.value:
            self.titleWidget.hide()
            self.banner.show()
        else:
            self.banner.hide()
            self.titleWidget.show()
