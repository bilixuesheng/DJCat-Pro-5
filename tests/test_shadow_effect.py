import math
from unittest import TestCase
from unittest.mock import patch

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from app.platform import shadow_effect
from app.platform.shadow_effect import SilhouetteShadowEffect
from app.view.components.window_background import WINDOW_SHADOW_ALPHA


class _RoundedCard(QWidget):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("white"))
        painter.drawRoundedRect(QRectF(self.rect()), 10, 10)


class _PaintCounter(QObject):
    def __init__(self, widget):
        super().__init__(widget)
        self.count = 0
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


class SilhouetteShadowEffectTest(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()

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

    def testBlursOncePerCornerAndSharesTheResult(self):
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

            # 换尺寸只重新拉伸：拖动缩放窗口化投送时不再逐个尺寸整张模糊。
            card.resize(220, 150)
            host.grab()
            self.assertEqual(blur.call_count, 1)

    def testWindowSizedShadowMatchesABlurOfTheWholeOutline(self):
        def onWhite(silhouette):
            image = QImage(silhouette.size(), QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(QColor("white"))
            painter = QPainter(image)
            painter.setOpacity(WINDOW_SHADOW_ALPHA / 255)
            painter.drawImage(0, 0, silhouette)
            painter.end()
            return image

        for ratio in (1.0, 1.25, 1.5, 2.0, 3.0):
            with self.subTest(ratio=ratio):
                blur = 12 * ratio
                width, height = round(600 * ratio), round(190 * ratio)
                whole = shadow_effect._blurredSilhouette(width, height, 8 * ratio, blur)
                shadow_effect._blurCache.clear()
                with patch.object(
                    shadow_effect,
                    "_blurredSilhouette",
                    wraps=shadow_effect._blurredSilhouette,
                ) as blurred:
                    stretched = shadow_effect._stretchedSilhouette(width, height, 8 * ratio, blur)
                self.assertEqual(stretched.size(), whole.size())
                self.assertLess(blurred.call_args.args[0], width // 4)

                # 卡片底下被不透明的卡片盖住，只比外面看得见的那一圈。
                expected, actual = onWhite(whole), onWhite(stretched)
                margin = math.ceil(blur)
                card = QRect(margin, margin, width, height)
                worst = 0
                for y in range(expected.height()):
                    for x in range(expected.width()):
                        if card.contains(x, y):
                            continue
                        worst = max(worst, abs(expected.pixelColor(x, y).red() - actual.pixelColor(x, y).red()))
                self.assertLessEqual(worst, 2)

    def testSnapshotCanLeaveTheShadowOutWithoutARepaint(self):
        effect = SilhouetteShadowEffect(10)
        host, card = self.render(effect)
        withShadow = host.grab().toImage()
        paints = _PaintCounter(card)

        effect.setShadowHidden(True)
        bare = host.grab().toImage()
        effect.setShadowHidden(False)
        # grab() 自己同步画一遍；之后不该再排进重画（setEnabled 来回切会排一次）。
        paints.count = 0
        self.app.processEvents()

        self.assertEqual(paints.count, 0)
        outside = (card.x() - 20, card.y() + 60)
        self.assertNotEqual(bare.pixelColor(*outside), withShadow.pixelColor(*outside))
        self.assertEqual(host.grab().toImage(), withShadow)

    def testSharedCacheStaysWithinItsByteBudget(self):
        shadow_effect._blurCache.clear()
        for width in range(400, 1400, 20):
            shadow_effect._cachedSilhouette(width, 600, 8, 12)
        total = sum(image.sizeInBytes() for image in shadow_effect._blurCache.values())
        self.assertLessEqual(total, shadow_effect._BLUR_CACHE_BYTES)

    def testNinePatchShadowMatchesABlurOfTheWholeShape(self):
        def paint(draw):
            image = QImage(360, 260, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            draw(painter)
            painter.end()
            return image

        rect = QRectF(40, 30, 280, 200)
        stretched = paint(lambda p: shadow_effect.paintSilhouetteShadow(p, rect, 8, 12, 1.0))
        whole = paint(
            lambda p: p.drawImage(
                rect.adjusted(-12, -12, 12, 12),
                shadow_effect._cachedSilhouette(280, 200, 8, 12),
            )
        )

        # 中间那块垫在形状底下，有意不画；其余部分与整块模糊一致。
        centre = rect.adjusted(20, 20, -20, -20).toRect()
        worst = 0
        for y in range(whole.height()):
            for x in range(whole.width()):
                if centre.contains(x, y):
                    continue
                worst = max(worst, abs(whole.pixelColor(x, y).alpha() - stretched.pixelColor(x, y).alpha()))
        self.assertLessEqual(worst, 3)

        blurs = len(shadow_effect._blurCache)
        paint(lambda p: shadow_effect.paintSilhouetteShadow(p, rect.adjusted(0, 0, 90, 30), 8, 12, 1.0))
        self.assertEqual(len(shadow_effect._blurCache), blurs)
