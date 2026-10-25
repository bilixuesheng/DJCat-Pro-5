from __future__ import annotations

from unittest.mock import patch

import pytest

from PySide6.QtCore import QEvent, QObject, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QShowEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsDropShadowEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import ComboBox, MessageBox, MessageBoxBase
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase
from qfluentwidgets.components.widgets.menu import MenuAnimationManager

from app.platform.dialog_animation import (
    _SHADOW_FADE_MS,
    _FadeLayer,
    _done,
    _setDialogShadow,
    _showEvent,
    optimizeFluentDialogs,
)
from app.platform.menu_animation import _SmoothDropDownMenuAnimation, optimizeFluentMenus


FADE_IN_MS = 200
FADE_OUT_MS = 100


@pytest.fixture(scope="module")
def application():
    return QApplication.instance()


@pytest.fixture
def optimizedDialogs(monkeypatch):
    monkeypatch.setattr(MaskDialogBase, "setShadowEffect", MaskDialogBase.setShadowEffect)
    monkeypatch.setattr(MaskDialogBase, "showEvent", MaskDialogBase.showEvent)
    monkeypatch.setattr(MaskDialogBase, "done", MaskDialogBase.done)
    optimizeFluentDialogs()


@pytest.fixture
def parentWindow(application):
    parent = QWidget()
    parent.resize(1000, 800)
    parent.show()
    yield parent
    parent.close()
    application.processEvents()


def test_dialog_optimization_patches_shadow_and_transitions(optimizedDialogs):
    optimizeFluentDialogs()

    assert MaskDialogBase.setShadowEffect is _setDialogShadow
    assert MaskDialogBase.showEvent is _showEvent
    assert MaskDialogBase.done is _done


def _layer(dialog):
    layers = dialog.findChildren(_FadeLayer, options=Qt.FindChildOption.FindDirectChildrenOnly)
    assert len(layers) <= 1
    return layers[0] if layers else None


@pytest.mark.parametrize("dialogKind", ["custom", "message"])
def test_masked_dialog_really_fades(application, parentWindow, optimizedDialogs, dialogKind):
    if dialogKind == "custom":
        dialog = MessageBoxBase(parentWindow)
    else:
        dialog = MessageBox("Title", "Content", parentWindow)

    shadow = dialog.widget.graphicsEffect()
    shadowColor = shadow.color()

    assert isinstance(shadow, QGraphicsDropShadowEffect)
    assert shadow.blurRadius() == 60
    assert shadow.offset().x() == 0
    assert shadow.offset().y() == 10

    dialog.show()
    application.processEvents()
    fadeIn = _layer(dialog)

    assert fadeIn is not None and not fadeIn.closing
    assert fadeIn._animation.duration() == FADE_IN_MS
    assert fadeIn._animation.easingCurve().type() == fadeIn._animation.easingCurve().Type.InSine
    assert fadeIn._animation.currentValue() < 1.0
    assert dialog.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    assert dialog.widget.graphicsEffect() is shadow
    assert not shadow.isEnabled()

    QTest.qWait(FADE_IN_MS + _SHADOW_FADE_MS + 150)

    assert _layer(dialog) is None
    assert not dialog.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    assert dialog.widget.graphicsEffect() is shadow
    assert shadow.isEnabled()
    assert shadow.color() == shadowColor

    dialog.reject()
    fadeOut = _layer(dialog)

    assert fadeOut is not None and fadeOut.closing
    assert fadeOut._animation.duration() == FADE_OUT_MS
    assert not shadow.isEnabled()
    assert dialog.isVisible()

    QTest.qWait(FADE_OUT_MS + 150)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.isVisible()


class _PaintCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def test_page_under_a_fading_dialog_is_not_repainted(application, parentWindow, optimizedDialogs):
    page = QLabel("页面内容" * 20, parentWindow)
    page.setGeometry(parentWindow.rect())
    page.show()
    application.processEvents()
    counter = _PaintCounter()
    page.installEventFilter(counter)

    dialog = MessageBoxBase(parentWindow)
    dialog.show()
    application.processEvents()
    counter.count = 0
    QTest.qWait(FADE_IN_MS - 50)

    # 透明度效果下页面每帧都跟着重画；快照动画只贴两张图。
    assert counter.count == 0

    QTest.qWait(_SHADOW_FADE_MS + 150)
    dialog.reject()
    application.processEvents()
    counter.count = 0
    QTest.qWait(FADE_OUT_MS - 40)

    assert counter.count == 0
    QTest.qWait(150)


class _Window(QWidget):
    """Paints its own background, as MainWindow does, under a transparent page."""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(32, 96, 160))


def _windowWithPage(application):
    window = _Window()
    window.resize(640, 480)
    layout = QVBoxLayout(window)
    layout.setContentsMargins(40, 30, 40, 30)
    page = QWidget(window)
    pageLayout = QVBoxLayout(page)
    for index in range(6):
        label = QLabel(f"第 {index} 行", page)
        label.setStyleSheet("background: rgba(255, 255, 255, 90); color: white;")
        pageLayout.addWidget(label)
    layout.addWidget(page)
    window.show()
    application.processEvents()
    return window, page


def _composited(layer, opacity):
    image = QImage(layer._backdrop.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(layer._backdrop.devicePixelRatio())
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.drawPixmap(0, 0, layer._backdrop)
    painter.setOpacity(opacity)
    painter.drawPixmap(0, 0, layer._dialogPixmap)
    painter.end()
    return image


def _assertLooksLike(image, expected):
    # 弹窗先在透明图上合成再叠上去，与透明度效果的做法相同；抗锯齿的边缘会差 1 个色阶。
    expected = expected.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    assert image.size() == expected.size()
    worst = 0
    for y in range(image.height()):
        for x in range(image.width()):
            a, b = image.pixelColor(x, y), expected.pixelColor(x, y)
            if a != b:
                worst = max(worst, *(abs(p - q) for p, q in zip(a.getRgb(), b.getRgb())))
    assert worst <= 2


def test_fade_starts_and_ends_on_what_the_window_really_shows(application, optimizedDialogs):
    window, page = _windowWithPage(application)
    try:
        beneath = window.grab(QRect(page.mapTo(window, page.rect().topLeft()), page.size())).toImage()
        dialog = MessageBoxBase(page)
        dialog.show()
        layer = _layer(dialog)
        QTest.qWait(30)

        _assertLooksLike(_composited(layer, 0.0), beneath)

        QTest.qWait(FADE_IN_MS + _SHADOW_FADE_MS + 150)
        dialog.widget.graphicsEffect().setEnabled(False)
        application.processEvents()
        shown = window.grab(QRect(page.mapTo(window, page.rect().topLeft()), page.size())).toImage()

        dialog.reject()
        closing = _layer(dialog)

        # 关闭时弹窗已经画在窗口上，底下的画面要一层层渲染出来；页面透明，窗口底色也要在。
        _assertLooksLike(_composited(closing, 0.0), beneath)
        _assertLooksLike(_composited(closing, 1.0), shown)
        QTest.qWait(FADE_OUT_MS + 150)
    finally:
        window.close()
        window.deleteLater()
        application.processEvents()


def test_restoring_a_minimized_window_does_not_fade_an_open_dialog_again(
    application, parentWindow, optimizedDialogs
):
    dialog = MessageBoxBase(parentWindow)
    shadow = dialog.widget.graphicsEffect()
    dialog.show()
    QTest.qWait(FADE_IN_MS + _SHADOW_FADE_MS + 150)

    class SpontaneousShow(QShowEvent):
        def spontaneous(self):
            return True

    # 还原时 Qt 给开着的弹窗补发一个系统来的 Show；后备缓冲里已经有弹窗，再淡入只会闪一下。
    dialog.showEvent(SpontaneousShow())

    assert _layer(dialog) is None
    assert shadow.isEnabled()
    dialog.reject()
    QTest.qWait(FADE_OUT_MS + 150)


def test_resizing_the_window_mid_fade_jumps_to_the_end(application, parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    shadow = dialog.widget.graphicsEffect()
    dialog.show()
    QTest.qWait(30)

    parentWindow.resize(parentWindow.width() + 80, parentWindow.height() + 40)
    application.processEvents()

    # 截图对不上新尺寸了，不留一条旧画面：直接收掉这一层，阴影照常浮现。
    assert _layer(dialog) is None
    assert not dialog.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    QTest.qWait(_SHADOW_FADE_MS + 50)
    assert shadow.isEnabled()

    dialog.reject()
    parentWindow.resize(parentWindow.width() - 80, parentWindow.height() - 40)
    application.processEvents()

    assert _layer(dialog) is None
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_a_finished_close_leaves_no_trace_for_the_next_dialog(application, optimizedDialogs):
    window, page = _windowWithPage(application)
    try:
        area = QRect(page.mapTo(window, page.rect().topLeft()), page.size())
        beneath = window.grab(area).toImage()
        dialog = MessageBoxBase(page)
        following = MessageBoxBase(page)
        dialog.show()
        QTest.qWait(FADE_IN_MS + _SHADOW_FADE_MS + 150)
        # 关闭的同一轮事件里就打开下一个弹窗，Qt 还没来得及重画腾出来的那块。
        dialog.finished.connect(lambda _: following.show())
        dialog.reject()
        closing = _layer(dialog)
        closing._animation.pause()
        closing._animation.setCurrentTime(FADE_OUT_MS // 3)
        closing.repaint()
        closing._animation.setCurrentTime(FADE_OUT_MS)

        # 下一个弹窗从后备缓冲复制底图；关闭的最后一帧必须已经画成弹窗全透明，不留残影。
        _assertLooksLike(_layer(following)._backdrop.toImage(), beneath)
        following.reject()
        QTest.qWait(FADE_OUT_MS + 150)
    finally:
        window.close()
        window.deleteLater()
        application.processEvents()


def test_dialog_closed_twice_closes_once_with_the_first_answer(parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    dialog.show()
    QTest.qWait(FADE_IN_MS + 50)
    finished = []
    dialog.finished.connect(finished.append)

    dialog.reject()
    dialog.accept()
    QTest.qWait(FADE_OUT_MS + 150)

    assert finished == [QDialog.DialogCode.Rejected]


def test_dialog_reuses_shadow_instead_of_recreating_it(parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    shadow = dialog.widget.graphicsEffect()

    dialog.setShadowEffect(42, (3, 7), QColor(10, 20, 30, 40))

    assert dialog.widget.graphicsEffect() is shadow
    assert shadow.blurRadius() == 42
    assert shadow.offset().x() == 3
    assert shadow.offset().y() == 7
    assert shadow.color() == QColor(10, 20, 30, 40)


def test_dialog_closed_while_opening_still_closes(application, parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    shadow = dialog.widget.graphicsEffect()
    dialog.show()
    opening = _layer(dialog)
    dialog.reject()
    # 打开那一层排着的截图在它被取消之后、被删掉之前才轮到：不再白白渲染一遍弹窗。
    opening._start()
    assert opening._dialogPixmap is None
    QTest.qWait(20)

    assert dialog.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
    assert not shadow.isEnabled()

    QTest.qWait(FADE_OUT_MS + 150)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.isVisible()
    assert not shadow.isEnabled()


def test_dialog_reopened_before_the_event_loop_turns_still_closes(parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    finished = []
    dialog.finished.connect(finished.append)
    dialog.show()
    QTest.qWait(FADE_IN_MS + 50)
    dialog.reject()
    QTest.qWait(FADE_OUT_MS + 150)

    # 嵌套编辑器关掉后会在同一轮事件里再打开；上一次关闭的那一层还没被删掉。
    def reopenOnce(_):
        dialog.finished.disconnect(reopenOnce)
        dialog.show()
        dialog.accept()

    dialog.finished.connect(reopenOnce)
    dialog.show()
    QTest.qWait(FADE_IN_MS + 50)
    dialog.reject()
    QTest.qWait(FADE_OUT_MS + 150)

    assert finished == [QDialog.DialogCode.Rejected] * 2 + [QDialog.DialogCode.Accepted]
    assert not dialog.isVisible()


@pytest.mark.parametrize("dialogKind", ["generic", "broadcast", "homeCardTask"])
def test_dropdown_inside_dialog_inherits_optimized_menu(
    application,
    parentWindow,
    optimizedDialogs,
    monkeypatch,
    dialogKind,
):
    from qfluentwidgets.components.widgets.menu import MenuAnimationType

    monkeypatch.setitem(
        MenuAnimationManager.managers,
        MenuAnimationType.DROP_DOWN,
        MenuAnimationManager.managers[MenuAnimationType.DROP_DOWN],
    )
    monkeypatch.setitem(
        MenuAnimationManager.managers,
        MenuAnimationType.PULL_UP,
        MenuAnimationManager.managers[MenuAnimationType.PULL_UP],
    )
    optimizeFluentMenus()

    if dialogKind == "broadcast":
        from app.view.pages.schedule_page import AddTaskDialog

        dialog = AddTaskDialog(parentWindow)
        combo = dialog.formWidgets["typeCombo"]
    elif dialogKind == "homeCardTask":
        from app.view.pages.home_card_task_page import AddHomeCardTaskDialog

        dialog = AddHomeCardTaskDialog([], parentWindow)
        combo = dialog.formWidgets["modeCombo"]
    else:
        dialog = MessageBoxBase(parentWindow)
        combo = ComboBox(dialog.widget)
        combo.addItems(["A", "B", "C"])
        dialog.viewLayout.addWidget(combo)
    dialog.show()
    QTest.qWait(230)

    with patch.object(MenuAnimationManager, "_updateMenuViewport", autospec=True) as update:
        combo._showComboMenu()
        menu = combo.dropMenu
        QTest.qWait(290)

        assert isinstance(menu.aniManager, _SmoothDropDownMenuAnimation)
        assert menu.aniManager.ani.duration() == 250
        update.assert_called_once_with(menu.aniManager)

    menu.close()
    dialog.reject()
    QTest.qWait(130)
    application.processEvents()
