from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEasingCurve, QPoint
from PySide6.QtGui import QAction
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication
from qfluentwidgets import ComboBox, LineEdit, RoundMenu
from qfluentwidgets.components.widgets.menu import (
    DropDownMenuAnimationManager,
    LineEditMenu,
    MenuAnimationManager,
    MenuAnimationType,
    PullUpMenuAnimationManager,
)

from app.platform.menu_animation import (
    _SmoothDropDownMenuAnimation,
    _SmoothPullUpMenuAnimation,
    optimizeFluentMenus,
)


ORIGINAL_MENU_ANIMATION_DURATION_MS = 250


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
def test_common_menus_keep_original_reveal_without_redundant_refreshes(
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

        with patch.object(menu, "setMask", wraps=menu.setMask) as setMask:
            QTest.qWait(ORIGINAL_MENU_ANIMATION_DURATION_MS + 40)

        assert finished.count() == 1
        assert isinstance(manager, _SmoothDropDownMenuAnimation)
        assert manager.ani.duration() == ORIGINAL_MENU_ANIMATION_DURATION_MS
        assert manager.ani.easingCurve().type() == QEasingCurve.Type.OutQuad
        assert manager.ani.endValue().y() - manager.ani.startValue().y() == (
            (menu.height() + 5) // 2
        )
        assert setMask.call_count > 1
        assert not menu.mask().isEmpty()
        assert shadow is not None
        assert menu.view.graphicsEffect() is shadow
        updateViewport.assert_called_once_with(manager)

    menu.close()
    widget.close()
    application.processEvents()


@pytest.mark.parametrize(
    ("animationType", "originalClass", "optimizedClass"),
    [
        (
            MenuAnimationType.DROP_DOWN,
            DropDownMenuAnimationManager,
            _SmoothDropDownMenuAnimation,
        ),
        (
            MenuAnimationType.PULL_UP,
            PullUpMenuAnimationManager,
            _SmoothPullUpMenuAnimation,
        ),
    ],
)
def test_optimized_animation_matches_original_geometry_and_mask(
    application,
    optimizedMenus,
    animationType,
    originalClass,
    optimizedClass,
):
    originalMenu = RoundMenu()
    originalMenu.addAction(QAction("example", originalMenu))
    optimizedMenu = RoundMenu()
    optimizedMenu.addAction(QAction("example", optimizedMenu))

    original = originalClass(originalMenu)
    optimized = MenuAnimationManager.make(optimizedMenu, animationType)
    position = QPoint(100, 200)

    for manager in (original, optimized):
        manager.exec(position)
        manager.ani.pause()
        manager.ani.setCurrentTime(ORIGINAL_MENU_ANIMATION_DURATION_MS // 2)

    assert isinstance(optimized, optimizedClass)
    assert optimized.ani.duration() == original.ani.duration()
    assert optimized.ani.easingCurve() == original.ani.easingCurve()
    assert optimized.ani.startValue() == original.ani.startValue()
    assert optimized.ani.endValue() == original.ani.endValue()
    assert optimized.ani.currentValue() == original.ani.currentValue()
    assert optimizedMenu.mask() == originalMenu.mask()

    original.ani.stop()
    optimized.ani.stop()
    originalMenu.close()
    optimizedMenu.close()
