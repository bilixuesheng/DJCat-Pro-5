from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ComboBox, LineEdit, RoundMenu
from qfluentwidgets.components.widgets.menu import (
    LineEditMenu,
    MenuAnimationManager,
    MenuAnimationType,
)

from app.platform.menu_animation import (
    MENU_ANIMATION_DURATION_MS,
    MENU_ANIMATION_OFFSET,
    _SmoothDropDownMenuAnimation,
    _SmoothPullUpMenuAnimation,
    optimizeFluentMenus,
)


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def optimizedMenus(monkeypatch):
    for animationType in (
        MenuAnimationType.DROP_DOWN,
        MenuAnimationType.PULL_UP,
    ):
        monkeypatch.setitem(
            MenuAnimationManager.managers,
            animationType,
            MenuAnimationManager.managers[animationType],
        )
    optimizeFluentMenus()


def test_menu_optimization_preserves_other_animation_types(optimizedMenus):
    managers = MenuAnimationManager.managers

    assert managers[MenuAnimationType.DROP_DOWN] is _SmoothDropDownMenuAnimation
    assert managers[MenuAnimationType.PULL_UP] is _SmoothPullUpMenuAnimation
    assert managers[MenuAnimationType.NONE] is not _SmoothDropDownMenuAnimation
    assert managers[MenuAnimationType.FADE_IN_DROP_DOWN] is not (
        _SmoothDropDownMenuAnimation
    )

    optimizeFluentMenus()

    assert managers[MenuAnimationType.DROP_DOWN] is _SmoothDropDownMenuAnimation
    assert managers[MenuAnimationType.PULL_UP] is _SmoothPullUpMenuAnimation


@pytest.mark.parametrize("menuKind", ["combo", "context"])
def test_common_menus_animate_without_rebuilding_masks(
    application,
    optimizedMenus,
    menuKind,
):
    application.clipboard().setText("example")

    if menuKind == "combo":
        widget = ComboBox()
        widget.addItems(["A", "B", "C", "D", "E", "F"])
    else:
        widget = LineEdit()
        widget.setText("example")

    widget.show()

    with patch.object(
        MenuAnimationManager,
        "_updateMenuViewport",
        autospec=True,
    ) as updateViewport:
        if menuKind == "combo":
            widget._showComboMenu()
            menu = widget.dropMenu
        else:
            menu = LineEditMenu(widget)
            menu.exec(QPoint(100, 100))

        manager = menu.aniManager
        finished = QSignalSpy(manager.ani.finished)
        shadow = menu.view.graphicsEffect()

        QTest.qWait(MENU_ANIMATION_DURATION_MS + 40)

        assert finished.count() == 1
        assert isinstance(manager, _SmoothDropDownMenuAnimation)
        assert manager.ani.duration() == MENU_ANIMATION_DURATION_MS
        assert manager.ani.endValue().y() - manager.ani.startValue().y() == (
            MENU_ANIMATION_OFFSET
        )
        assert menu.mask().isEmpty()
        assert shadow is not None
        assert menu.view.graphicsEffect() is shadow
        updateViewport.assert_called_once_with(manager)

    menu.close()
    widget.close()
    application.processEvents()


def test_pull_up_menu_keeps_its_direction(application, optimizedMenus):
    menu = RoundMenu()
    menu.addAction(QAction("example", menu))

    manager = MenuAnimationManager.make(menu, MenuAnimationType.PULL_UP)
    manager.exec(QPoint(100, 200))

    assert isinstance(manager, _SmoothPullUpMenuAnimation)
    assert manager.ani.startValue().y() - manager.ani.endValue().y() == (
        MENU_ANIMATION_OFFSET
    )
    assert menu.mask().isEmpty()

    manager.ani.stop()
    menu.close()
