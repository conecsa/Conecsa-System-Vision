"""Unit tests for the pure letterbox helpers."""
import numpy as np
import pytest

from service.capture_service import corners_to_letterbox, letterbox_square

_PAD = 114


class TestLetterboxSquare:
    def test_square_input_fills_without_padding(self):
        frame = np.full((100, 100, 3), 200, dtype=np.uint8)
        out = letterbox_square(frame, 640)
        assert out.shape == (640, 640, 3)
        # A square input scales to fill the whole square (no gray border).
        assert (out == _PAD).mean() < 0.01

    def test_landscape_pads_top_and_bottom(self):
        frame = np.full((100, 200, 3), 200, dtype=np.uint8)  # 2:1 landscape
        out = letterbox_square(frame, 640)
        assert out.shape == (640, 640, 3)
        # Top and bottom rows are gray padding; middle rows contain image.
        assert np.all(out[0] == _PAD)
        assert np.all(out[-1] == _PAD)
        assert not np.all(out[320] == _PAD)

    def test_portrait_pads_left_and_right(self):
        frame = np.full((200, 100, 3), 200, dtype=np.uint8)  # 1:2 portrait
        out = letterbox_square(frame, 640)
        assert out.shape == (640, 640, 3)
        assert np.all(out[:, 0] == _PAD)
        assert np.all(out[:, -1] == _PAD)
        assert not np.all(out[:, 320] == _PAD)

    def test_output_size_is_configurable(self):
        frame = np.zeros((50, 50, 3), dtype=np.uint8)
        assert letterbox_square(frame, 320).shape == (320, 320, 3)

    def test_padding_uses_yolo_gray(self):
        frame = np.zeros((100, 300, 3), dtype=np.uint8)
        out = letterbox_square(frame, 640)
        # Corner is padding -> exactly (114, 114, 114).
        assert tuple(out[0, 0]) == (_PAD, _PAD, _PAD)


class TestCornersToLetterbox:
    def test_square_source_is_identity(self):
        cx, cy, w, h = corners_to_letterbox(0.25, 0.25, 0.75, 0.75, 100, 100, 640)
        assert (cx, cy) == (pytest.approx(0.5), pytest.approx(0.5))
        assert (w, h) == (pytest.approx(0.5), pytest.approx(0.5))

    def test_landscape_source_shrinks_and_centers_vertically(self):
        # 2:1 landscape: content occupies the middle 320 rows of the 640 square.
        cx, cy, w, h = corners_to_letterbox(0.0, 0.0, 1.0, 1.0, 200, 100, 640)
        assert (cx, cy) == (pytest.approx(0.5), pytest.approx(0.5))
        assert w == pytest.approx(1.0)
        assert h == pytest.approx(0.5)

    def test_portrait_source_shrinks_and_centers_horizontally(self):
        cx, cy, w, h = corners_to_letterbox(0.0, 0.0, 1.0, 1.0, 100, 200, 640)
        assert w == pytest.approx(0.5)
        assert h == pytest.approx(1.0)
        assert (cx, cy) == (pytest.approx(0.5), pytest.approx(0.5))

    def test_off_center_box_lands_inside_scaled_content(self):
        # Landscape 2:1 → content spans rows 160..480 of the square.
        # A box in the top-left quarter of the source stays in the top-left of
        # the content area.
        cx, cy, w, h = corners_to_letterbox(0.0, 0.0, 0.5, 0.5, 200, 100, 640)
        assert cx == pytest.approx(0.25)
        # content top = 160/640 = 0.25; the box spans rows 0.25..0.5
        assert cy == pytest.approx(0.375)
        assert w == pytest.approx(0.5)
        assert h == pytest.approx(0.25)

    def test_matches_letterbox_square_geometry(self):
        # A full-frame box must cover exactly the non-padded pixels produced
        # by letterbox_square for the same source dims.
        src_w, src_h, size = 300, 100, 640
        frame = np.full((src_h, src_w, 3), 255, dtype=np.uint8)
        out = letterbox_square(frame, size)
        rows = np.where(~np.all(out == _PAD, axis=(1, 2)))[0]
        cx, cy, w, h = corners_to_letterbox(0.0, 0.0, 1.0, 1.0, src_w, src_h, size)
        top, bottom = rows[0], rows[-1] + 1
        assert cy - h / 2 == pytest.approx(top / size, abs=1 / size)
        assert cy + h / 2 == pytest.approx(bottom / size, abs=1 / size)
        assert w == pytest.approx(1.0)

    def test_result_is_clamped(self):
        # Slightly out-of-frame corners (NMS drift) clamp into 0..1.
        cx, cy, w, h = corners_to_letterbox(-0.1, -0.1, 1.1, 1.1, 100, 100, 640)
        for v in (cx, cy, w, h):
            assert 0.0 <= v <= 1.0
