import os
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import qconfig

from app.config.cfg import (
    BANNER_IMAGE_PRESETS,
    DEFAULT_BANNER_IMAGE_SOURCE,
    cfg,
)
from app.config.paths import ASSET_DIR


class BannerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(300)

        self._cached_pixmap = None  # 预渲染的最终图片
        self._cache_size = None     # 缓存对应的窗口尺寸
        self._source_key = None
        self._source_pixmap = None

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

        pixmap = self._source_image(img_path)
        if pixmap is None:
            return None
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

    def _source_image(self, path):
        try:
            stamp = Path(path).stat().st_mtime_ns
        except OSError:
            stamp = None
        key = (path, stamp)
        if key != self._source_key:
            pixmap = QPixmap(path)
            if pixmap.isNull() and path != str(
                ASSET_DIR / BANNER_IMAGE_PRESETS[DEFAULT_BANNER_IMAGE_SOURCE]
            ):
                fallback = str(
                    ASSET_DIR / BANNER_IMAGE_PRESETS[DEFAULT_BANNER_IMAGE_SOURCE]
                )
                pixmap = QPixmap(fallback)
            self._source_key = key
            self._source_pixmap = None if pixmap.isNull() else pixmap
        return self._source_pixmap

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
