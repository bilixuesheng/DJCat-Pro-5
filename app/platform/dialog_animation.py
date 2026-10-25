from __future__ import annotations

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QEvent,
    QPoint,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QDialog, QGraphicsDropShadowEffect, QWidget
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

from app.platform.backing_store import paintedImage
from app.platform.shadow_effect import SilhouetteShadowEffect

_FADE_IN_MS = 200
_FADE_OUT_MS = 100
_SHADOW_FADE_MS = 150
# 与 QFluentWidgets 对话框 #centerWidget 的 border-radius 一致。
DIALOG_CARD_RADIUS = 10


def _findCardShadow(widget):
    """The shadow on the enclosing MaskDialogBase's card, or None.

    Deliberately not "the first drop shadow up the parent chain": that would let a
    caller outside a dialog seize an unrelated shadow, such as WindowBackground's.
    """
    node = widget
    while node is not None:
        if isinstance(node, MaskDialogBase):
            effect = node.widget.graphicsEffect()
            return effect if isinstance(effect, QGraphicsDropShadowEffect) else None
        node = node.parentWidget()
    return None


def fadeDialogShadow(widget, visible):
    """Fade the mask dialog card shadow above `widget` in or out.

    A QGraphicsEffect re-rasterises its whole subtree whenever any descendant repaints,
    so a lit card shadow would re-run its blur on every frame of a long-running child
    animation. Returns None when there is no card shadow to fade.
    """
    effect = _findCardShadow(widget)
    if effect is None:
        return None

    target = getattr(effect, "_djcatShadowColor", None)
    if target is None:
        target = QColor(effect.color())
        effect._djcatShadowColor = target

    end = QColor(target)
    if not visible:
        end.setAlpha(0)

    animation = QPropertyAnimation(effect, b"color", effect)
    animation.setStartValue(QColor(effect.color()))
    animation.setEndValue(end)
    animation.setDuration(_SHADOW_FADE_MS)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return animation


def _setDialogShadow(
    dialog,
    blurRadius=60,
    offset=(0, 10),
    color=QColor(0, 0, 0, 100),
):
    # 原版阴影每次重绘都把整张卡片离屏重画再模糊一遍，叠在上层弹窗下面时，上层的任何
    # 重绘都会让下层卡片再模糊一次。轮廓阴影只在卡片尺寸变化时模糊一次。
    shadow = dialog.widget.graphicsEffect()
    if not isinstance(shadow, SilhouetteShadowEffect):
        shadow = SilhouetteShadowEffect(DIALOG_CARD_RADIUS, dialog.widget)
        dialog.widget.setGraphicsEffect(shadow)

    shadow.setBlurRadius(blurRadius)
    shadow.setOffset(*offset)
    shadow.setColor(color)


def _blankPixmap(size, ratio) -> QPixmap:
    pixmap = QPixmap(size * ratio)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    return pixmap


def _copyBeneath(dialog) -> QPixmap | None:
    """Copy what the window shows under a dialog that has not been painted yet."""
    image = paintedImage(dialog)
    if image is None:
        return None
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(image.devicePixelRatio())
    return pixmap


def _renderBeneath(dialog) -> QPixmap:
    """Render what lies under a dialog: each ancestor's own paint and the siblings below.

    The dialog may sit on a transparent page rather than on the window, so rendering
    its parent alone would leave out the window background behind the page.
    """
    pixmap = _blankPixmap(dialog.size(), dialog.devicePixelRatioF())
    painter = QPainter(pixmap)
    chain = []
    child = dialog
    while not child.isWindow():
        chain.append((child.parentWidget(), child))
        child = child.parentWidget()
    for parent, child in reversed(chain):
        origin = dialog.mapTo(parent, QPoint())
        area = QRect(origin, dialog.size())
        # 只取各层自己画的，系统给窗口铺的底不算：主窗口自己画整窗底色，挂了 Background
        # Effect 时画成全透明。
        parent.render(painter, QPoint(), QRegion(area), QWidget.RenderFlag(0))
        siblings = [widget for widget in parent.children() if isinstance(widget, QWidget)]
        # 先加的子控件在下面；盖在弹窗上面的（InfoBar）照常由 Qt 画在动画上面。
        for sibling in siblings[: siblings.index(child)]:
            if sibling.isWindow() or not sibling.isVisible():
                continue
            visible = sibling.geometry().intersected(area)
            if visible.isEmpty():
                continue
            sibling.render(
                painter,
                visible.topLeft() - origin,
                QRegion(visible.translated(-sibling.pos())),
                QWidget.RenderFlag.DrawChildren,
            )
    painter.end()
    return pixmap


def _fadeLayers(dialog):
    # 收掉的层要等回到事件循环才删；弹窗可能在这之前又打开、又关闭。
    return [
        layer
        for layer in dialog.findChildren(_FadeLayer, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if not layer._isRemoved
    ]


class _FadeLayer(QWidget):
    """Fades a mask dialog in or out from two pictures taken once.

    A QGraphicsOpacityEffect on the dialog renders the whole dialog off screen again on
    every frame, and the page under the translucent mask repaints with it. The layer
    takes what is under the dialog and the dialog itself (mask, card and controls, the
    card shadow already off) once, then each frame only draws the one and the other at
    the current opacity, which is exactly how the opacity effect composited them. The
    dialog says it is opaque meanwhile, so Qt stops repainting the page under it.
    """

    def __init__(self, dialog, closing):
        super().__init__(dialog)
        self.closing = closing
        self._dialog = dialog
        self._isRendering = False
        self._isStartPending = False
        self._isRemoved = False
        self._dialogPixmap = None
        if closing:
            self._animation = QVariantAnimation(
                self, startValue=1.0, endValue=0.0, duration=_FADE_OUT_MS
            )
        else:
            self._animation = QVariantAnimation(
                self,
                startValue=0.0,
                endValue=1.0,
                duration=_FADE_IN_MS,
                easingCurve=QEasingCurve(QEasingCurve.Type.InSine),
            )
        self.finished = self._animation.finished
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(dialog.rect())
        for layer in _fadeLayers(dialog):
            if layer is not self:
                layer.cancel()
        # 打开时弹窗还没画过，后备缓冲里那一块就是它底下的画面，直接复制最快。
        backdrop = None if closing else _copyBeneath(dialog)
        self._backdrop = backdrop if backdrop is not None else _renderBeneath(dialog)
        self._animation.valueChanged.connect(self.update)
        self._animation.finished.connect(self._onFinished)
        dialog.installEventFilter(self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        # 关闭时当场截图开始：窗口最小化时等不到绘制，弹窗也要关得掉。
        if closing:
            self._start()
        self.show()
        # polish 会清掉这个属性，所以在 show() 之后设。
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.raise_()

    def cancel(self) -> None:
        self._animation.stop()
        self._remove()

    def eventFilter(self, obj, event) -> bool:
        # 动画途中窗口改了尺寸，弹窗跟着变，两张截图就对不上了：直接走到终点。
        if obj is self._dialog and event.type() == QEvent.Type.Resize and not self._isRemoved:
            if self._animation.state() != QAbstractAnimation.State.Running:
                self._animation.start()
            self._animation.setCurrentTime(self._animation.duration())
        return False

    def _onFinished(self) -> None:
        if self.closing:
            # 最后一帧画成弹窗全透明：紧接着打开的弹窗从后备缓冲复制底图时，不会带上这一张的残影。
            self.repaint()
        self._remove()

    def _remove(self) -> None:
        self._isRemoved = True
        self._dialog.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.hide()
        self.deleteLater()

    def _start(self) -> None:
        if self._isRemoved:
            return
        pixmap = _blankPixmap(self._dialog.size(), self.devicePixelRatioF())
        # 截的是弹窗本身：这一层不画，也不能以不透明的身份挡住底下的蒙层和卡片。
        self._isRendering = True
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._dialog.render(pixmap, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._isRendering = False
        self._dialogPixmap = pixmap
        self._animation.start()

    def paintEvent(self, event) -> None:
        if self._isRendering:
            return
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawPixmap(0, 0, self._backdrop)
        if self._dialogPixmap is None:
            # 打开时等第一次绘制过后再截弹窗，这时布局已经排好；第一帧本来就只有底下的画面。
            # 不能在这里当场截：渲染弹窗会再画一遍这一层，Qt 报递归重画，这次绘制也作废。
            if not self._isStartPending:
                self._isStartPending = True
                QTimer.singleShot(0, self, self._start)
            return
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setOpacity(self._animation.currentValue())
        painter.drawPixmap(0, 0, self._dialogPixmap)


def _showEvent(self, e):
    if e.spontaneous():
        # 主窗口从最小化还原：弹窗本来就开着，后备缓冲里已经有它，再淡入一次只会闪一下。
        QDialog.showEvent(self, e)
        return
    shadow = self.widget.graphicsEffect()
    hasShadow = isinstance(shadow, QGraphicsDropShadowEffect)
    shadowColor = shadow.color() if hasShadow else None
    if hasShadow:
        shadow.setEnabled(False)

    layer = _FadeLayer(self, closing=False)

    def onFinished():
        if not hasShadow:
            return
        transparent = QColor(shadowColor)
        transparent.setAlpha(0)
        shadow.setColor(transparent)
        shadow.setEnabled(True)
        colorAni = QPropertyAnimation(shadow, b"color", self)
        colorAni.setStartValue(transparent)
        colorAni.setEndValue(shadowColor)
        colorAni.setDuration(_SHADOW_FADE_MS)
        colorAni.setEasingCurve(QEasingCurve.OutCubic)
        colorAni.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    layer.finished.connect(onFinished)
    QDialog.showEvent(self, e)


def _done(self, code):
    if any(layer.closing for layer in _fadeLayers(self)):
        return
    shadow = self.widget.graphicsEffect()
    if isinstance(shadow, QGraphicsDropShadowEffect):
        shadow.setEnabled(False)
    else:
        self.widget.setGraphicsEffect(None)
    if not self.isVisible():
        self._onDone(code)
        return

    layer = _FadeLayer(self, closing=True)
    layer.finished.connect(lambda: self._onDone(code))


def optimizeFluentDialogs() -> None:
    MaskDialogBase.setShadowEffect = _setDialogShadow
    MaskDialogBase.showEvent = _showEvent
    MaskDialogBase.done = _done
