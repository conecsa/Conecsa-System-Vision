"""Unit tests for the overlay box/text placement geometry."""
import pytest

from api.views.overlay_renderer import OverlayRenderer

WIDTH, HEIGHT = 100, 80
BOX_W, BOX_H = 40, 20


class TestCalculateOverlayPosition:
    @pytest.mark.parametrize(
        "position, expected",
        [
            ("top-right", (60, 0, 100, 20, 65, 5)),
            ("top-left", (0, 0, 40, 20, 5, 5)),
            ("bottom-left", (0, 60, 40, 80, 5, 70)),
            ("bottom-right", (60, 60, 100, 80, 65, 70)),
        ],
    )
    def test_each_corner(self, position, expected):
        result = OverlayRenderer._calculate_overlay_position(
            WIDTH, HEIGHT, BOX_W, BOX_H, position
        )
        assert result == expected

    def test_unknown_position_falls_back_to_top_left(self):
        assert OverlayRenderer._calculate_overlay_position(
            WIDTH, HEIGHT, BOX_W, BOX_H, "middle"
        ) == OverlayRenderer._calculate_overlay_position(
            WIDTH, HEIGHT, BOX_W, BOX_H, "top-left"
        )

    def test_default_position_is_top_right(self):
        assert OverlayRenderer._calculate_overlay_position(
            WIDTH, HEIGHT, BOX_W, BOX_H
        ) == (60, 0, 100, 20, 65, 5)
