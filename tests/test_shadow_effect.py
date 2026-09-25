import os
from unittest import TestCase
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from app.platform import shadow_effect
from app.platform.shadow_effect import SilhouetteShadowEffect


class _RoundedCard(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(QRectF(self.rect()), 10, 10)


class SilhouetteShadowEffectTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def render(self, effect):
        host = QWidget()
        host.resize(400, 320)
        host.setStyleSheet("background: rgb(200, 220, 240);")
        card = _RoundedCard(host)
        card.setGeometry(100, 80, 200, 150)
        effect.setParent(card)
        effect.setBlurRadius(60)
        effect.setOffset(0, 10)
        effect.setColor(QColor(0, 0, 0, 100))
        card.setGraphicsEffect(effect)
        host.show()
        self.app.processEvents()
        self.addCleanup(host.deleteLater)
        return host, card

    def testLooksLikeQtsDropShadow(self):
        expected = self.render(QGraphicsDropShadowEffect())[0].grab().toImage()
        actual = self.render(SilhouetteShadowEffect(10))[0].grab().toImage()

        worst = 0
        for y in range(expected.height()):
            for x in range(expected.width()):
                a, b = expected.pixelColor(x, y), actual.pixelColor(x, y)
                worst = max(
                    worst,
                    abs(a.red() - b.red()),
                    abs(a.green() - b.green()),
                    abs(a.blue() - b.blue()),
                )
        self.assertLessEqual(worst, 3)

    def testBlursOncePerSizeAndSharesTheResult(self):
        shadow_effect._blurCache.clear()
        with patch.object(
            shadow_effect,
            "_blurredSilhouette",
            wraps=shadow_effect._blurredSilhouette,
        ) as blur:
            host, card = self.render(SilhouetteShadowEffect(10))
            for _ in range(5):
                card.update()
                host.grab()
            # 另一张同尺寸的卡（下一次打开的同一个菜单）直接用缓存。
            self.render(SilhouetteShadowEffect(10))[0].grab()
            self.assertEqual(blur.call_count, 1)

            # 阴影淡入只改颜色，不该重新模糊。
            card.graphicsEffect().setColor(QColor(0, 0, 0, 30))
            host.grab()
            self.assertEqual(blur.call_count, 1)

            card.resize(220, 150)
            host.grab()
            self.assertEqual(blur.call_count, 2)

    def testSharedCacheStaysWithinItsByteBudget(self):
        shadow_effect._blurCache.clear()
        for width in range(400, 1400, 20):
            shadow_effect._cachedSilhouette(width, 600, 8, 12)
        total = sum(image.sizeInBytes() for image in shadow_effect._blurCache.values())
        self.assertLessEqual(total, shadow_effect._BLUR_CACHE_BYTES)
