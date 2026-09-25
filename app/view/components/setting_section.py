from __future__ import annotations

from PySide6.QtCore import (
    QByteArray,
    Property,
    QEasingCurve,
    QEvent,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    IconWidget,
    StrongBodyLabel,
    themeColor,
)

from app.view.components.scroll_area import ScrollArea
from app.view.components.setting_card_group import (
    SettingCardList,
    SettingMaterialCard,
)

# 横向是 SlideNavigationTransitionInfo 的推移：进入下一级时旧页左移出场、新页自右入场，
# 两页同向同速，返回时反向。只有 FromBottom（顶层切换）才是"旧页原地淡出"。
# 位移取 Fluent 唯一公布的 150 有效像素；有效像素已按系统缩放档位换算，
# Qt 的部件坐标同样是设备无关像素，再乘 devicePixelRatio 会缩放两次。
SLIDE_DISTANCE = 150
SLIDE_DURATION_MS = 300

HIGHLIGHT_FADE_MS = 200
HIGHLIGHT_HOLD_MS = 1500
HIGHLIGHT_RADIUS = 6
HIGHLIGHT_WIDTH = 2

ROOT_SECTION_KEY = "root"


def _cubicBezierCurve(x1: float, y1: float, x2: float, y2: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(
        QPointF(x1, y1),
        QPointF(x2, y2),
        QPointF(1.0, 1.0),
    )
    return curve


def decelerateCurve() -> QEasingCurve:
    """Fluent "Fast Out, Slow In": cubic-bezier(0, 0, 0, 1)."""
    return _cubicBezierCurve(0.0, 0.0, 0.0, 1.0)


class _NavigationChevron(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.setOpacity(0.61)
        FluentIcon.CHEVRON_RIGHT_MED.render(painter, QRectF(7, 7, 12, 12))


class SettingNavigationCard(SettingMaterialCard):
    """A row that drills into a Setting Section instead of expanding in place."""

    activated = Signal()

    def __init__(self, icon, title: str, content: str = "", parent=None):
        super().__init__(parent)
        self.iconWidget = IconWidget(icon, self)
        self.titleLabel = StrongBodyLabel(title, self)
        self.contentLabel = CaptionLabel(content, self)
        self.chevron = _NavigationChevron(self)
        self.hBoxLayout = QHBoxLayout(self)
        self.titleLayout = QVBoxLayout()
        self._pressPosition = None
        self._pressCanceled = False

        self._initWidget()
        self._initLayout()

    def _initWidget(self) -> None:
        self.iconWidget.setFixedSize(24, 24)
        self.titleLabel.setFixedHeight(22)
        self.contentLabel.setFixedHeight(18)
        self.contentLabel.setVisible(bool(self.contentLabel.text()))
        self.setFixedHeight(70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _initLayout(self) -> None:
        self.hBoxLayout.setContentsMargins(16, 15, 8, 15)
        self.hBoxLayout.setSpacing(12)
        self.titleLayout.setContentsMargins(0, 0, 0, 0)
        self.titleLayout.setSpacing(0)
        self.titleLayout.addWidget(self.titleLabel)
        self.titleLayout.addWidget(self.contentLabel)
        self.hBoxLayout.addWidget(self.iconWidget)
        self.hBoxLayout.addLayout(self.titleLayout)
        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.chevron)

    # 起滑取消：CardWidget 在任何一次释放上都发 clicked，滚动手势会误触发导航。
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressPosition = event.globalPosition().toPoint()
            self._pressCanceled = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._pressPosition is not None:
            distance = (
                event.globalPosition().toPoint() - self._pressPosition
            ).manhattanLength()
            if distance >= QApplication.startDragDistance() or not self.rect().contains(
                event.position().toPoint()
            ):
                self._pressCanceled = True
                self.isPressed = False
                self._updateBackgroundColor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        shouldActivate = (
            event.button() == Qt.MouseButton.LeftButton
            and self._pressPosition is not None
            and not self._pressCanceled
            and self.rect().contains(event.position().toPoint())
        )
        self._pressPosition = None
        self._pressCanceled = False
        super().mouseReleaseEvent(event)
        if shouldActivate:
            self.activated.emit()

    def leaveEvent(self, event) -> None:
        if self._pressPosition is not None:
            self._pressCanceled = True
            self.isPressed = False
            self._updateBackgroundColor()
        super().leaveEvent(event)


class SettingCardHighlight(QWidget):
    """A themed outline drawn over the card a Setting Suggestion landed on."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fade = 0.0
        self._target = None
        self._owner = parent
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

        self.fadeAnimation = QPropertyAnimation(self, QByteArray(b"fade"), self)
        self.fadeAnimation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.holdTimer = QTimer(self)
        self.holdTimer.setSingleShot(True)
        self.holdTimer.setInterval(HIGHLIGHT_HOLD_MS)

        self.holdTimer.timeout.connect(self._fadeOut)
        self.fadeAnimation.finished.connect(self._onFadeFinished)

    def getFade(self) -> float:
        return self._fade

    def setFade(self, value: float) -> None:
        self._fade = value
        self.update()

    fade = Property(float, getFade, setFade)

    def showOn(self, card: QWidget) -> None:
        self.clear()
        self._target = card
        card.installEventFilter(self)
        self.setParent(card)
        self.setGeometry(card.rect())
        self.raise_()
        self.show()
        self.fadeAnimation.stop()
        self.fadeAnimation.setDuration(HIGHLIGHT_FADE_MS)
        self.fadeAnimation.setStartValue(self._fade)
        self.fadeAnimation.setEndValue(1.0)
        self.fadeAnimation.start()

    def clear(self) -> None:
        self.holdTimer.stop()
        self.fadeAnimation.stop()
        self.setFade(0.0)
        self.hide()
        if self._target is None:
            return
        self._target.removeEventFilter(self)
        self._target = None
        # 回到页面名下，否则卡片被销毁时会把这个长期持有的覆盖层一起带走。
        self.setParent(self._owner)

    def _fadeOut(self) -> None:
        self.fadeAnimation.stop()
        self.fadeAnimation.setDuration(HIGHLIGHT_FADE_MS)
        self.fadeAnimation.setStartValue(self._fade)
        self.fadeAnimation.setEndValue(0.0)
        self.fadeAnimation.start()

    def _onFadeFinished(self) -> None:
        if self._fade >= 1.0:
            self.holdTimer.start()
        elif self._fade <= 0.0:
            self.clear()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if obj is self._target and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._target.rect())
        return super().eventFilter(obj, event)

    def paintEvent(self, event) -> None:
        if self._fade <= 0.0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._fade)
        painter.setPen(QPen(themeColor(), HIGHLIGHT_WIDTH))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inset = HIGHLIGHT_WIDTH / 2
        painter.drawRoundedRect(
            QRectF(self.rect()).adjusted(inset, inset, -inset, -inset),
            HIGHLIGHT_RADIUS,
            HIGHLIGHT_RADIUS,
        )


class SettingSectionView(ScrollArea):
    """One node of the setting hierarchy, scrolling independently of its siblings."""

    def __init__(self, key: str, parent=None):
        # 大多数 Section 在一次会话里从不打开；首次显示时才抓触控手势。
        super().__init__(parent, grabTouch=False)
        self.key = key
        self.container = QWidget()
        self.vBoxLayout = QVBoxLayout(self.container)
        self._cardLists = []
        self._navigationCards = []

        self._initWidget()

    def _initWidget(self) -> None:
        self.setWidget(self.container)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setObjectName(f"SettingSection_{self.key.replace('.', '_')}")
        self.enableTransparentBackground()
        self.vBoxLayout.setContentsMargins(11, 4, 11, 36)
        self.vBoxLayout.setSpacing(10)
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def addPreview(self, widget: QWidget, centered: bool = False) -> QWidget:
        """``centered`` is for fixed-size previews; stretchy ones would shrink to
        their size hint under an alignment flag."""
        widget.setParent(self.container)
        if centered:
            self.vBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        else:
            self.vBoxLayout.addWidget(widget)
        return widget

    def addNavigationCard(self, card: SettingNavigationCard) -> SettingNavigationCard:
        card.setParent(self.container)
        self.vBoxLayout.addWidget(card)
        self._navigationCards.append(card)
        return card

    def addSubsectionTitle(self, text: str) -> StrongBodyLabel:
        label = StrongBodyLabel(text, self.container)
        label.setContentsMargins(6, 12, 0, 0)
        self.vBoxLayout.addWidget(label)
        return label

    def addCardList(self, cards: list[QWidget]) -> SettingCardList:
        cardList = SettingCardList(self.container)
        cardList.addSettingCards(cards)
        self.vBoxLayout.addWidget(cardList)
        self._cardLists.append(cardList)
        return cardList

    def cardLists(self) -> tuple[SettingCardList, ...]:
        return tuple(self._cardLists)

    def navigationCards(self) -> tuple[SettingNavigationCard, ...]:
        return tuple(self._navigationCards)

    def settingCards(self) -> tuple[QWidget, ...]:
        return tuple(
            card for cardList in self._cardLists for card in cardList.settingCards()
        )

    def cardListFor(self, card: QWidget) -> SettingCardList | None:
        for cardList in self._cardLists:
            if card in cardList.settingCards():
                return cardList
        return None

    def scrollToCard(self, card: QWidget) -> None:
        top = card.mapTo(self.container, QPoint()).y()
        value = max(0, top - self.vBoxLayout.contentsMargins().top())
        delegate = getattr(self, "delegate", None)
        scrollBar = getattr(delegate, "vScrollBar", None)
        if scrollBar is None:
            self.verticalScrollBar().setValue(value)
            return
        scrollBar.scrollTo(value)


class SettingSectionStack(QWidget):
    """Drill-in container: sections slide left and right like Windows settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._views = {}
        self._currentKey = None
        self._transitions = []

    def addView(self, view: SettingSectionView) -> SettingSectionView:
        view.setParent(self)
        view.hide()
        self._views[view.key] = view
        return view

    def view(self, key: str) -> SettingSectionView | None:
        return self._views.get(key)

    def views(self) -> tuple[SettingSectionView, ...]:
        return tuple(self._views.values())

    def currentKey(self) -> str | None:
        return self._currentKey

    def currentView(self) -> SettingSectionView | None:
        return self._views.get(self._currentKey)

    def isAnimating(self) -> bool:
        return bool(self._transitions)

    def setCurrentView(
        self,
        key: str,
        isBack: bool = False,
        animated: bool = True,
    ) -> None:
        incoming = self._views.get(key)
        if incoming is None or key == self._currentKey:
            return

        self.stopAnimations()
        outgoing = self._views.get(self._currentKey)
        self._currentKey = key
        incoming.grabTouchGesture()
        incoming.setGeometry(self.rect())
        incoming.show()
        incoming.raise_()

        if not animated or outgoing is None:
            if outgoing is not None:
                outgoing.hide()
            return

        # 推移的是两页的快照，不是真页面：给整页 ScrollArea 挂不透明度效果时，
        # 每个 Animation Tick 都要把整棵子树（含设置预览）重新栅格化进离屏缓冲，
        # 两页各一遍。快照在起步时各截一次，之后每帧只贴两张图。
        outgoingSnapshot = self._snapshot(outgoing)
        incomingSnapshot = self._snapshot(incoming)
        outgoing.hide()
        incoming.hide()

        # 两页共用同一条曲线和时长，否则推移途中会彼此错开、不再像相邻的两页。
        direction = 1 if isBack else -1
        self._animate(
            outgoingSnapshot,
            outgoing,
            fadeIn=False,
            slideFrom=0,
            slideTo=direction * SLIDE_DISTANCE,
        )
        self._animate(
            incomingSnapshot,
            incoming,
            fadeIn=True,
            slideFrom=-direction * SLIDE_DISTANCE,
            slideTo=0,
        )

    def stopAnimations(self) -> None:
        # 打断时直接落到末态：QAbstractAnimation.stop() 不会发 finished。
        for transition in tuple(self._transitions):
            transition.group.stop()
            self._finishTransition(transition)

    def _snapshot(self, view: SettingSectionView) -> "_SectionSnapshot":
        snapshot = _SectionSnapshot(view.grab(), self)
        snapshot.setGeometry(self.rect())
        snapshot.show()
        snapshot.raise_()
        return snapshot

    def _animate(
        self,
        snapshot: "_SectionSnapshot",
        view: SettingSectionView,
        *,
        fadeIn: bool,
        slideFrom: int,
        slideTo: int,
    ) -> None:
        curve = decelerateCurve()
        group = QParallelAnimationGroup(self)

        snapshot.setOpacity(0.0 if fadeIn else 1.0)
        opacity = QPropertyAnimation(snapshot, QByteArray(b"opacity"), group)
        opacity.setDuration(SLIDE_DURATION_MS)
        opacity.setEasingCurve(curve)
        opacity.setStartValue(0.0 if fadeIn else 1.0)
        opacity.setEndValue(1.0 if fadeIn else 0.0)
        group.addAnimation(opacity)

        snapshot.move(slideFrom, 0)
        # 只动 pos 和 opacity：1 ms 的 Animation Tick 下逐帧重排会把开销放大十几倍。
        move = QPropertyAnimation(snapshot, QByteArray(b"pos"), group)
        move.setDuration(SLIDE_DURATION_MS)
        move.setEasingCurve(curve)
        move.setStartValue(QPoint(slideFrom, 0))
        move.setEndValue(QPoint(slideTo, 0))
        group.addAnimation(move)

        transition = _Transition(group, snapshot, view, showOnFinish=fadeIn)
        group.finished.connect(
            lambda: self._finishTransition(transition)
        )
        self._transitions.append(transition)
        group.start()

    def _finishTransition(self, transition: "_Transition") -> None:
        if transition not in self._transitions:
            return
        self._transitions.remove(transition)
        transition.settle()

    def resizeEvent(self, event) -> None:
        # 快照按起步时的尺寸截取，尺寸变了就直接落到末态，让真页面按新尺寸排版。
        self.stopAnimations()
        for view in self._views.values():
            if not view.isHidden():
                view.resize(self.size())
        super().resizeEvent(event)


class _SectionSnapshot(QWidget):
    """A frozen image of a section that slides and fades in the section's place."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._opacity = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def getOpacity(self) -> float:
        return self._opacity

    def setOpacity(self, value: float) -> None:
        self._opacity = value
        self.update()

    opacity = Property(float, getOpacity, setOpacity)

    def paintEvent(self, event) -> None:
        if self._opacity <= 0.0:
            return
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._pixmap)


class _Transition:
    """A running section transition and the end state it must settle into."""

    def __init__(
        self,
        group: QParallelAnimationGroup,
        snapshot: _SectionSnapshot,
        view: SettingSectionView,
        showOnFinish: bool,
    ):
        self.group = group
        self.snapshot = snapshot
        self.view = view
        self.showOnFinish = showOnFinish

    def settle(self) -> None:
        self.snapshot.hide()
        self.snapshot.deleteLater()
        self.view.move(0, 0)
        if self.showOnFinish:
            self.view.show()
            self.view.raise_()
        else:
            self.view.hide()
        # 动画组挂在 stack 名下，不主动释放就会随每次下钻和返回一直累积。
        self.group.deleteLater()
