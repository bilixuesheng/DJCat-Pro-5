from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QWidget,
)
from qfluentwidgets import ComboBox, MessageBox, MessageBoxBase
from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase
from qfluentwidgets.components.widgets.menu import MenuAnimationManager

from app.platform.dialog_animation import (
    _SHADOW_FADE_MS,
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
    return QApplication.instance() or QApplication([])


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


@pytest.mark.parametrize("dialogKind", ["custom", "message"])
def test_masked_dialog_really_fades(parentWindow, optimizedDialogs, dialogKind):
    if dialogKind == "custom":
        dialog = MessageBoxBase(parentWindow)
    else:
        dialog = MessageBox("Title", "Content", parentWindow)

    shadow = dialog.widget.graphicsEffect()

    assert isinstance(shadow, QGraphicsDropShadowEffect)
    assert shadow.blurRadius() == 60
    assert shadow.offset().x() == 0
    assert shadow.offset().y() == 10

    dialog.show()
    fadeIn = dialog.graphicsEffect()

    assert isinstance(fadeIn, QGraphicsOpacityEffect)
    assert fadeIn.opacity() < 1.0
    assert dialog.widget.graphicsEffect() is shadow
    assert not shadow.isEnabled()

    QTest.qWait(FADE_IN_MS + _SHADOW_FADE_MS + 150)

    assert dialog.graphicsEffect() is None
    assert dialog.widget.graphicsEffect() is shadow
    assert shadow.isEnabled()
    assert shadow.color() == QColor(0, 0, 0, 100)

    dialog.reject()
    fadeOut = dialog.graphicsEffect()

    assert isinstance(fadeOut, QGraphicsOpacityEffect)
    assert dialog.isVisible()

    QTest.qWait(FADE_OUT_MS + 150)

    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.isVisible()


def test_dialog_reuses_shadow_instead_of_recreating_it(parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    shadow = dialog.widget.graphicsEffect()

    dialog.setShadowEffect(42, (3, 7), QColor(10, 20, 30, 40))

    assert dialog.widget.graphicsEffect() is shadow
    assert shadow.blurRadius() == 42
    assert shadow.offset().x() == 3
    assert shadow.offset().y() == 7
    assert shadow.color() == QColor(10, 20, 30, 40)


def test_dialog_closed_while_opening_still_closes(parentWindow, optimizedDialogs):
    dialog = MessageBoxBase(parentWindow)
    dialog.show()
    dialog.reject()

    QTest.qWait(FADE_OUT_MS + 150)

    assert dialog.result() == QDialog.DialogCode.Rejected
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
