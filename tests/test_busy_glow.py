from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from app.view.components.busy_glow import (
    BREATH_AMPLITUDE,
    CORNER_RADIUS,
    ENTRANCE_MS,
    TAPER_FRACTION,
    GLOW_MARGIN,
    BusyGlowOverlay,
    _arcWindow,
    _bandColor,
    _haloAlpha,
    _perimeter,
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance()


@pytest.fixture
def host(app):
    parent = QWidget()
    parent.resize(700, 400)
    layout = QVBoxLayout(parent)
    target = QWidget(parent)
    target.resize(600, 200)
    layout.addWidget(target)
    parent.show()
    yield parent, target
    parent.deleteLater()


def _rect():
    from PySide6.QtCore import QRectF

    return QRectF(0, 0, 600, 200)


class TestPerimeterParameterisation:
    def test_fractions_run_monotonically_from_zero_to_one(self):
        _, fractions = _perimeter(_rect(), CORNER_RADIUS)
        assert fractions[0] == pytest.approx(0.0)
        assert fractions[-1] == pytest.approx(1.0)
        assert all(b >= a for a, b in zip(fractions, fractions[1:]))

    def test_walk_starts_at_the_bottom_edge_midpoint(self):
        points, _ = _perimeter(_rect(), CORNER_RADIUS)
        start = points[0]
        assert start.x() == pytest.approx(300, abs=2)
        assert start.y() == pytest.approx(200, abs=2)

    def test_right_edge_midpoint_sits_at_a_quarter_of_the_perimeter(self):
        """By arc length it is exactly 0.25; by raw angle it would be 0.0.

        This is the property that keeps colour moving at a constant speed instead of
        racing along the short edges of a wide box.
        """
        points, fractions = _perimeter(_rect(), CORNER_RADIUS)
        index = min(
            range(len(points)),
            key=lambda i: (points[i].x() - 600) ** 2 + (points[i].y() - 100) ** 2,
        )
        assert fractions[index] == pytest.approx(0.25, abs=0.01)

    def test_gradient_colours_a_point_by_its_arc_length_not_its_angle(self, app):
        overlay = BusyGlowOverlay(QWidget())
        overlay.resize(600 + 2 * GLOW_MARGIN, 200 + 2 * GLOW_MARGIN)
        _, gradient = overlay._gradients(overlay._state(0), 0)
        # The right-edge midpoint lies at angle 0, i.e. gradient position 0. Under angle
        # parameterisation that stop would carry the colour of arc fraction 0.0 instead.
        from qfluentwidgets import isDarkTheme

        dark = isDarkTheme()
        first = min(gradient.stops(), key=lambda stop: stop[0])
        assert first[1].getRgb()[:3] == pytest.approx(
            _bandColor(0.25, dark).getRgb()[:3], abs=12
        )
        assert first[1].getRgb()[:3] != pytest.approx(
            _bandColor(0.0, dark).getRgb()[:3], abs=12
        )


class TestGrownArc:
    def test_partial_growth_is_a_single_arc_not_two_arms(self):
        """Two arms would overlap at the bottom seam and stack alpha into a bright blob.

        A single arc centred on the bottom midpoint only ever gets dimmer away from it.
        """
        samples = [_arcWindow(i / 400, 0.4) for i in range(201)]
        assert samples[0] == 1.0
        assert all(b <= a for a, b in zip(samples, samples[1:]))

    def test_growth_is_centred_on_the_bottom_edge(self):
        for fraction in (0.02, 0.08, 0.15, 0.3):
            assert _arcWindow(fraction, 0.3) == pytest.approx(
                _arcWindow(1 - fraction, 0.3)
            )
        assert _arcWindow(0.5, 0.3) == 0.0, "a 30% arc must not have reached the top edge yet"

    def test_full_growth_closes_the_ring(self):
        assert all(_arcWindow(i / 100, 1.0) == 1.0 for i in range(101))

    def test_growing_ends_are_dimmer_than_the_middle_of_the_arc(self, app):
        """Strokes are additive, so a taper painted over the core brightens the ends
        instead of fading them. Guard the direction, not just the presence, of the fade.
        """
        from PySide6.QtGui import QImage, QPainter

        overlay = BusyGlowOverlay(QWidget())
        overlay.resize(600 + 2 * GLOW_MARGIN, 200 + 2 * GLOW_MARGIN)
        image = QImage(overlay.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        overlay._paintGlow(painter, 260)
        painter.end()

        _, fractions = overlay._points, overlay._fractions
        progress = overlay._state(260)[0]
        tip = overlay._points[
            min(
                range(len(fractions)),
                # The middle of the fading end: half-way along the taper.
                key=lambda i: abs(
                    fractions[i]
                    - (progress * (0.5 + TAPER_FRACTION) - TAPER_FRACTION * progress / 2)
                ),
            )
        ]
        middle = overlay._points[
            min(
                range(len(fractions)),
                key=lambda i: abs(fractions[i] - progress * 0.2),
            )
        ]

        def alphaAt(point):
            return QColor.fromRgba(
                image.pixel(round(point.x()), round(point.y()))
            ).alpha()

        assert alphaAt(tip) < alphaAt(middle)

    def test_the_two_ends_close_gradually_instead_of_snapping_shut(self):
        """The fading ends used to leave a dim gap at the top until the very last frame,
        which then filled the whole gap at once."""
        def dimmest(progress):
            return min(_arcWindow(i / 400, progress) for i in range(401))

        previous = 0.0
        for step in range(900, 1000):
            current = dimmest(step / 1000)
            assert current >= previous
            previous = current
        assert dimmest(0.995) > 0.9
        # The frame right before the entrance ends is already (almost) a full ring.
        overlay = BusyGlowOverlay(QWidget())
        lastProgress = overlay._state(ENTRANCE_MS - 16).progress
        assert dimmest(lastProgress) > 0.95

    def test_zero_growth_draws_nothing(self):
        assert all(_arcWindow(i / 100, 0.0) == 0.0 for i in range(101))


class TestThemeRecipes:
    def test_light_theme_is_darker_and_more_saturated_than_dark_theme(self):
        """Glow reads as light on a dark background; on a near-white one it cannot,
        so the light recipe shows up by being darker than its background instead."""
        for position in (0.0, 0.2, 0.45, 0.7, 0.95):
            dark = _bandColor(position, dark=True)
            light = _bandColor(position, dark=False)
            assert light.value() < dark.value()
            assert light.saturation() >= dark.saturation()

    def test_palette_wraps_without_a_seam(self):
        start, end = _bandColor(0.0, dark=True), _bandColor(0.9999, dark=True)
        for a, b in zip(start.getRgb(), end.getRgb()):
            assert abs(a - b) <= 3


class TestOverlayLifecycle:
    def test_overlay_covers_the_target_expanded_by_the_glow_margin(self, host):
        _, target = host
        overlay = BusyGlowOverlay(target)
        expected = target.geometry().adjusted(
            -GLOW_MARGIN, -GLOW_MARGIN, GLOW_MARGIN, GLOW_MARGIN
        )
        assert overlay.geometry() == expected

    def test_overlay_follows_the_target_when_it_is_resized(self, host):
        parent, target = host
        overlay = BusyGlowOverlay(target)
        target.setGeometry(10, 10, 300, 120)
        QApplication.processEvents()
        assert overlay.geometry() == target.geometry().adjusted(
            -GLOW_MARGIN, -GLOW_MARGIN, GLOW_MARGIN, GLOW_MARGIN
        )

    def test_overlay_never_swallows_input(self, host):
        from PySide6.QtCore import Qt

        _, target = host
        overlay = BusyGlowOverlay(target)
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def test_start_shows_and_animates_stop_hides(self, host):
        _, target = host
        overlay = BusyGlowOverlay(target)
        assert not overlay.isRunning()

        overlay.start()
        assert overlay.isRunning()
        assert overlay.isVisible()

        overlay.stop(immediate=True)
        assert not overlay.isRunning()
        assert not overlay.isVisible()

    def test_start_is_idempotent(self, host):
        _, target = host
        overlay = BusyGlowOverlay(target)
        overlay.start()
        first = overlay._elapsed.elapsed()
        overlay.start()
        assert overlay._elapsed.elapsed() >= first
        assert overlay.isRunning()
        overlay.stop(immediate=True)

    def test_restarting_during_the_fade_out_keeps_the_glow_alive(self, host):
        """A conversion retried right after a failure must not inherit the pending fade,
        which would hide the new run a few frames in."""
        _, target = host
        overlay = BusyGlowOverlay(target)
        overlay.start()
        overlay.stop()
        assert overlay._stopAtMs is not None

        overlay.start()
        assert overlay._stopAtMs is None
        assert overlay.isRunning()
        assert overlay.isVisible()
        assert overlay._state(0).fade == 1.0
        overlay.stop(immediate=True)

    def test_halo_fades_to_nothing_before_the_overlay_edge_at_peak_breath(self):
        """Otherwise the outermost bloom is clipped square by the overlay's own rect."""
        peak = 1 + BREATH_AMPLITUDE
        assert _haloAlpha(GLOW_MARGIN - 1, peak) == 0.0
        assert _haloAlpha(GLOW_MARGIN - 3, peak) * 255 < 1
        assert _haloAlpha(-(GLOW_MARGIN - 1), peak) == 0.0

    def test_halo_falls_off_smoothly_without_steps(self):
        """The old six stacked strokes left visible rings on a light background."""
        samples = [_haloAlpha(d / 4, 1.0) for d in range(0, 4 * GLOW_MARGIN)]
        assert all(b <= a for a, b in zip(samples, samples[1:]))
        jumps = [a - b for a, b in zip(samples, samples[1:])]
        # A step shows up as one jump surrounded by flat neighbours; a smooth curve's
        # neighbouring jumps are always about the same size.
        for before, jump, after in zip(jumps, jumps[1:], jumps[2:]):
            assert jump <= 2 * max(before, after) + 1 / 255

    def test_halo_reaches_less_far_into_the_box_than_out_of_it(self):
        """Text right against the edge of the input must stay readable."""
        for distance in (4, 8, 12):
            assert _haloAlpha(-distance, 1.0) < _haloAlpha(distance, 1.0)

    def test_paints_without_error_across_the_whole_lifecycle(self, host):
        from PySide6.QtGui import QImage, QPainter

        _, target = host
        overlay = BusyGlowOverlay(target)
        overlay.start()
        for ms in (0, 1, 120, 400, 700, 2000, 5000):
            image = QImage(overlay.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(QColor(0, 0, 0, 0))
            painter = QPainter(image)
            overlay._paintGlow(painter, ms)
            painter.end()
        overlay.stop(immediate=True)

    def test_fade_out_eventually_draws_nothing(self, host):
        from PySide6.QtGui import QImage, QPainter

        _, target = host
        overlay = BusyGlowOverlay(target)
        overlay.start()
        overlay.stop()
        assert overlay._stopAtMs is not None

        image = QImage(overlay.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        overlay._paintGlow(painter, overlay._stopAtMs + 400)
        painter.end()
        assert not any(
            QColor.fromRgba(image.pixel(x, y)).alpha()
            for x in range(0, image.width(), 17)
            for y in range(0, image.height(), 17)
        )
        overlay.stop(immediate=True)


class TestDialogShadow:
    def test_glow_fades_the_mask_dialog_card_shadow_out_and_back(self, app):
        """A card-level drop shadow re-blurs the whole card on every child repaint,
        so it cannot stay lit while the glow repaints at 60 Hz."""
        from app.platform.dialog_animation import fadeDialogShadow

        from qfluentwidgets.components.dialog_box.mask_dialog_base import MaskDialogBase

        window = QWidget()
        window.resize(800, 600)
        dialog = MaskDialogBase(window)
        shadow = QGraphicsDropShadowEffect(dialog.widget)
        shadow.setBlurRadius(60)
        shadow.setColor(QColor(0, 0, 0, 100))
        dialog.widget.setGraphicsEffect(shadow)
        child = QWidget(dialog.widget)

        out = fadeDialogShadow(child, visible=False)
        assert out is not None
        assert out.endValue().alpha() == 0

        back = fadeDialogShadow(child, visible=True)
        assert back is not None
        assert back.endValue().alpha() == 100

    def test_widget_without_a_card_shadow_is_a_no_op(self, app):
        from app.platform.dialog_animation import fadeDialogShadow

        assert fadeDialogShadow(QWidget(), visible=False) is None

    def test_an_unrelated_ancestor_shadow_is_never_seized(self, app):
        """A page outside any dialog must not reach up and dim, say, WindowBackground."""
        from app.platform.dialog_animation import fadeDialogShadow

        page = QWidget()
        page.resize(400, 300)
        shadow = QGraphicsDropShadowEffect(page)
        shadow.setColor(QColor(0, 0, 0, 100))
        page.setGraphicsEffect(shadow)
        child = QWidget(page)

        assert fadeDialogShadow(child, visible=False) is None
        assert shadow.color().alpha() == 100


class TestDialogIntegration:
    def test_the_dialog_glow_reaches_the_card_shadow(self, app):
        """The overlay sits inside MaskDialogBase.widget, so the walk up from it must
        land on the card's shadow - that is the whole point of fading it."""
        from qfluentwidgets import MessageBoxBase

        from app.platform.dialog_animation import _findCardShadow, _setDialogShadow

        window = QWidget()
        window.resize(800, 600)
        dialog = MessageBoxBase(window)
        _setDialogShadow(dialog)

        target = QWidget(dialog.widget)
        dialog.viewLayout.addWidget(target)
        overlay = BusyGlowOverlay(target)

        assert _findCardShadow(overlay) is dialog.widget.graphicsEffect()


class TestOldImplementationIsGone:
    def test_the_qss_busy_border_helper_no_longer_exists(self):
        from app.view.pages import broadcast_page

        assert not hasattr(broadcast_page, "_busyTextEditStyle")

    def test_conversion_no_longer_rewrites_the_input_stylesheet(self, app):
        """Rewriting the widget stylesheet dropped the whole QFluentWidgets TextEdit
        look, including its scrollbars, for the duration of a conversion."""
        from app.view.pages.broadcast_page import AIMarkdownDialog

        window = QWidget()
        window.resize(800, 600)
        with patch(
            "app.view.pages.broadcast_page.fetchQuota", return_value=(9, 15, 1, False, "DJ-1")
        ), patch("app.view.pages.broadcast_page._streamAIMarkdown"):
            dialog = AIMarkdownDialog("作业", window)
            before = dialog.inputEdit.styleSheet()
            dialog._startConversion()
            try:
                assert dialog.inputEdit.styleSheet() == before
                assert dialog._glow.isRunning()
            finally:
                dialog._cancelConversion()
                dialog._stopTimers()
                assert not dialog._glow.isRunning()
                dialog.deleteLater()
                window.deleteLater()
