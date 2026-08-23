from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QAbstractAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QGraphicsDropShadowEffect, QWidget
from qfluentwidgets import ComboBox, MessageBox, MessageBoxBase
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase
from qfluentwidgets.components.widgets.menu import MenuAnimationManager

from app.platform.dialog_animation import (
    _finishDialog,
    _setDialogShadow,
    _showDialog,
    optimizeFluentDialogs,
)
from app.platform.menu_animation import _SmoothDropDownMenuAnimation, optimizeFluentMenus


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def optimizedDialogs(monkeypatch):
    monkeypatch.setattr(MaskDialogBase, "showEvent", MaskDialogBase.showEvent)
    monkeypatch.setattr(MaskDialogBase, "done", MaskDialogBase.done)
    monkeypatch.setattr(MaskDialogBase, "setShadowEffect", MaskDialogBase.setShadowEffect)
    optimizeFluentDialogs()


@pytest.fixture
def parentWindow(application):
    parent = QWidget()
    parent.resize(1000, 800)
    parent.show()
    yield parent
    parent.close()
    application.processEvents()


def test_dialog_optimization_is_idempotent(optimizedDialogs):
    optimizeFluentDialogs()

    assert MaskDialogBase.showEvent is _showDialog
    assert MaskDialogBase.done is _finishDialog
    assert MaskDialogBase.setShadowEffect is _setDialogShadow


@pytest.mark.parametrize("dialogKind", ["custom", "message"])
def test_masked_dialog_keeps_original_fade_and_shadow(
    parentWindow,
    optimizedDialogs,
    dialogKind,
):
    if dialogKind == "custom":
        dialog = MessageBoxBase(parentWindow)
    else:
        dialog = MessageBox("Title", "Content", parentWindow)

    shadow = dialog.widget.graphicsEffect()

    assert isinstance(shadow, QGraphicsDropShadowEffect)
    assert shadow.blurRadius() == 60
    assert shadow.offset().x() == 0
    assert shadow.offset().y() == 10
    assert shadow.color() == QColor(0, 0, 0, 50)

    dialog.show()
    animation = dialog._dialogOpacityAnimation
    finished = QSignalSpy(animation.finished)

    assert animation.targetObject() is dialog
    assert bytes(animation.propertyName()) == b"windowOpacity"
    assert animation.duration() == 200
    assert animation.easingCurve().type() == QEasingCurve.Type.InSine
    assert animation.startValue() == 0.0
    assert animation.endValue() == 1.0
    assert dialog.graphicsEffect() is None
    assert dialog.widget.graphicsEffect() is shadow

    if not finished.count():
        assert finished.wait(1000)
    assert finished.count() == 1
    assert dialog.windowOpacity() == 1.0
    assert dialog.widget.graphicsEffect() is shadow

    dialog.reject()
    closing = dialog._dialogOpacityAnimation
    closed = QSignalSpy(closing.finished)

    assert closing.duration() == 100
    assert closing.startValue() == 1.0
    assert closing.endValue() == 0.0
    assert dialog.graphicsEffect() is None
    assert dialog.widget.graphicsEffect() is None

    if not closed.count():
        assert closed.wait(1000)
    assert closed.count() == 1
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.isVisible()


def test_dialog_reuses_shadow_instead_of_recreating_it(
    parentWindow,
    optimizedDialogs,
):
    dialog = MessageBoxBase(parentWindow)
    shadow = dialog.widget.graphicsEffect()

    dialog.setShadowEffect(42, (3, 7), QColor(10, 20, 30, 40))

    assert dialog.widget.graphicsEffect() is shadow
    assert shadow.blurRadius() == 42
    assert shadow.offset().x() == 3
    assert shadow.offset().y() == 7
    assert shadow.color() == QColor(10, 20, 30, 40)


def test_dialog_close_stops_running_open_animation(
    parentWindow,
    optimizedDialogs,
):
    dialog = MessageBoxBase(parentWindow)
    dialog.show()
    opening = dialog._dialogOpacityAnimation

    dialog.reject()

    assert opening.state() == QAbstractAnimation.State.Stopped
    assert dialog._dialogOpacityAnimation is not opening

    closed = QSignalSpy(dialog._dialogOpacityAnimation.finished)
    if not closed.count():
        assert closed.wait(1000)

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
