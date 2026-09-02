"""Host-side tests for ModelManager preprocessing (no TensorRT interpreter).

``ModelManager.__init__`` creates a TensorRT interpreter (and, with
TENSORRT_CONTEXTS>1, worker subprocesses), so the manager is built with
``__new__`` + ``_configure_preprocessing`` and fake ``input_details``, which is
all ``preprocess_image`` depends on.
"""
import cv2
import numpy as np
import pytest
from api.model_manager import (
    ModelManager,
    input_size_from_shape,
    letterbox_pad_from_env,
    letterbox_to_square,
    resize_interp_from_env,
    tiling_mode_from_env,
    tiling_overlap_from_env,
    tiling_tile_from_env,
)


def _manager(size: int, dtype: type = np.float32):
    mm = ModelManager.__new__(ModelManager)
    mm._configure_preprocessing()
    mm.input_details = [{"index": 0, "name": "images", "shape": (1, 3, size, size),
                         "dtype": dtype}]
    mm.input_size = input_size_from_shape(mm.input_details[0]["shape"])
    return mm


def _frame(h, w, value=200):
    return np.full((h, w, 3), value, dtype=np.uint8)


class TestEnvKnobs:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("INFER_LETTERBOX_PAD", raising=False)
        monkeypatch.delenv("INFER_RESIZE_INTERP", raising=False)
        assert letterbox_pad_from_env() == 0
        assert resize_interp_from_env() == cv2.INTER_NEAREST

    def test_pad_and_interp_are_read(self, monkeypatch):
        monkeypatch.setenv("INFER_LETTERBOX_PAD", "114")
        monkeypatch.setenv("INFER_RESIZE_INTERP", "area")
        assert letterbox_pad_from_env() == 114
        assert resize_interp_from_env() == cv2.INTER_AREA
        monkeypatch.setenv("INFER_RESIZE_INTERP", "Linear")
        assert resize_interp_from_env() == cv2.INTER_LINEAR

    @pytest.mark.parametrize("raw", ["abc", "-1", "256", ""])
    def test_invalid_pad_falls_back(self, monkeypatch, raw):
        monkeypatch.setenv("INFER_LETTERBOX_PAD", raw)
        assert letterbox_pad_from_env() == 0

    @pytest.mark.parametrize("raw", ["cubic", "", "2"])
    def test_invalid_interp_falls_back(self, monkeypatch, raw):
        monkeypatch.setenv("INFER_RESIZE_INTERP", raw)
        assert resize_interp_from_env() == cv2.INTER_NEAREST


class TestInputSizeFromShape:
    @pytest.mark.parametrize("size", [640, 1280])
    def test_channels_first_uses_spatial_dim(self, size):
        # The old code read shape[1] and reported 3 for every NCHW engine.
        assert input_size_from_shape((1, 3, size, size)) == size

    def test_channels_last_keeps_index_one(self):
        assert input_size_from_shape((1, 320, 320, 3)) == 320

    @pytest.mark.parametrize("size", [640, 1280])
    def test_finalize_interpreter_setup_reports_size(self, size):
        class FakeInterpreter:
            """Only the two detail getters are exercised by the setup step."""

            def get_input_details(self):
                return [{"index": 0, "name": "images", "shape": (1, 3, size, size),
                         "dtype": np.float32}]

            def get_output_details(self):
                return [{"index": 1, "name": "output0", "shape": (1, 300, 6),
                         "dtype": np.float32}]

            def allocate_tensors(self) -> None:
                raise AssertionError("not expected during setup")

            def set_tensor(self, tensor_index: int, value: np.ndarray) -> None:
                raise AssertionError("not expected during setup")

            def invoke(self) -> None:
                raise AssertionError("not expected during setup")

            def get_tensor(self, tensor_index: int) -> np.ndarray:
                raise AssertionError("not expected during setup")

        mm = ModelManager.__new__(ModelManager)
        mm._finalize_interpreter_setup(FakeInterpreter())
        assert mm.input_size == size


class TestLetterboxToSquare:
    @pytest.mark.parametrize("size,frame_hw,expected_top", [
        (640, (720, 1280), 140),
        (640, (480, 640), 80),
        (1280, (720, 1280), 280),
        (1280, (480, 640), 160),
    ])
    def test_geometry(self, size, frame_hw, expected_top):
        h, w = frame_hw
        img, scale, top = letterbox_to_square(_frame(h, w), size)
        assert img.shape == (size, size, 3)
        assert top == expected_top
        resized_h = int(size * h / w)
        assert scale == pytest.approx(h / resized_h)

    def test_pad_rows_take_the_pad_value(self):
        img, _, top = letterbox_to_square(_frame(720, 1280), 640, pad_value=114)
        assert np.all(img[:top] == 114)
        assert np.all(img[-top:] == 114)
        assert np.all(img[top:-top] == 200)


class TestPreprocessImage:
    @pytest.mark.parametrize("size", [640, 1280])
    @pytest.mark.parametrize("frame_hw,top_by_size", [
        ((720, 1280), {640: 140, 1280: 280}),
        ((480, 640), {640: 80, 1280: 160}),
    ])
    def test_tensor_shape_range_and_geometry(self, monkeypatch, size, frame_hw, top_by_size):
        monkeypatch.delenv("INFER_LETTERBOX_PAD", raising=False)
        monkeypatch.delenv("INFER_RESIZE_INTERP", raising=False)
        h, w = frame_hw
        mm = _manager(size)

        tensor, scale, top, actual = mm.preprocess_image(_frame(h, w))

        assert tensor.shape == (1, 3, size, size)
        assert tensor.dtype == np.float32
        assert tensor.min() >= 0.0 and tensor.max() <= 1.0
        assert actual == size
        assert top == top_by_size[size]
        assert scale == pytest.approx(h / int(size * h / w))

    def test_default_pad_is_black(self, monkeypatch):
        monkeypatch.delenv("INFER_LETTERBOX_PAD", raising=False)
        mm = _manager(640)
        tensor, _, top, _ = mm.preprocess_image(_frame(720, 1280))
        assert np.all(tensor[0, :, :top, :] == 0.0)
        assert np.all(tensor[0, :, -top:, :] == 0.0)
        assert np.all(tensor[0, :, top:-top, :] == pytest.approx(200 / 255.0))

    def test_pad_114_when_configured(self, monkeypatch):
        monkeypatch.setenv("INFER_LETTERBOX_PAD", "114")
        mm = _manager(1280)
        tensor, _, top, _ = mm.preprocess_image(_frame(720, 1280))
        assert top == 280
        assert np.all(tensor[0, :, :top, :] == pytest.approx(114 / 255.0))
        assert np.all(tensor[0, :, -top:, :] == pytest.approx(114 / 255.0))

    def test_env_is_read_once_at_configure_time(self, monkeypatch):
        monkeypatch.setenv("INFER_LETTERBOX_PAD", "114")
        mm = _manager(640)
        monkeypatch.setenv("INFER_LETTERBOX_PAD", "0")
        tensor, _, top, _ = mm.preprocess_image(_frame(720, 1280))
        assert np.all(tensor[0, :, :top, :] == pytest.approx(114 / 255.0))

    @pytest.mark.parametrize("interp", ["nearest", "linear", "area"])
    def test_interpolation_knob_is_accepted(self, monkeypatch, interp):
        monkeypatch.setenv("INFER_RESIZE_INTERP", interp)
        mm = _manager(640)
        # A frame with structure so interpolation actually has to do work.
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[:, ::2] = 255
        tensor, scale, top, actual = mm.preprocess_image(frame)
        assert tensor.shape == (1, 3, 640, 640)
        assert (top, actual) == (140, 640)
        assert scale == pytest.approx(2.0)

    def test_bgr_to_rgb_channel_order(self, monkeypatch):
        monkeypatch.delenv("INFER_LETTERBOX_PAD", raising=False)
        mm = _manager(640)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        frame[:, :, 2] = 255  # pure red in BGR
        tensor, _, top, _ = mm.preprocess_image(frame)
        assert np.all(tensor[0, 0, top:-top, :] == 1.0)  # R first in RGB
        assert np.all(tensor[0, 1, top:-top, :] == 0.0)
        assert np.all(tensor[0, 2, top:-top, :] == 0.0)

    def test_uint8_engine_keeps_raw_bytes(self):
        mm = _manager(640, dtype=np.uint8)
        tensor, _, _, _ = mm.preprocess_image(_frame(720, 1280))
        assert tensor.dtype == np.uint8
        assert tensor.max() == 200


class TestTilingKnobs:
    def test_defaults_are_grid_with_an_auto_tile(self, monkeypatch):
        for var in ("TILING_MODE", "TILING_TILE", "TILING_OVERLAP"):
            monkeypatch.delenv(var, raising=False)
        assert tiling_mode_from_env() == "grid"
        assert tiling_tile_from_env() is None  # auto: the frame's short side
        assert tiling_overlap_from_env() == 0.2

    @pytest.mark.parametrize("raw,expected", [("auto", None), ("AUTO", None), ("720", 720)])
    def test_tile_is_auto_or_pixels(self, monkeypatch, raw, expected):
        monkeypatch.setenv("TILING_TILE", raw)
        assert tiling_tile_from_env() == expected

    def test_grid_is_read_case_insensitively(self, monkeypatch):
        monkeypatch.setenv("TILING_MODE", "Grid")
        assert tiling_mode_from_env() == "grid"

    @pytest.mark.parametrize("raw", ["on", "sahi", "1", ""])
    def test_unknown_mode_falls_back_to_grid(self, monkeypatch, raw):
        monkeypatch.setenv("TILING_MODE", raw)
        assert tiling_mode_from_env() == "grid"

    @pytest.mark.parametrize("raw", ["abc", "0", "-64", ""])
    def test_invalid_tile_falls_back_to_auto(self, monkeypatch, raw):
        monkeypatch.setenv("TILING_TILE", raw)
        assert tiling_tile_from_env() is None

    @pytest.mark.parametrize("raw", ["abc", "1.0", "-0.1", ""])
    def test_invalid_overlap_falls_back(self, monkeypatch, raw):
        monkeypatch.setenv("TILING_OVERLAP", raw)
        assert tiling_overlap_from_env() == 0.2


class TestPreprocessTiles:
    def test_off_wraps_preprocess_image_as_single_full_frame_tile(self, monkeypatch):
        monkeypatch.setenv("TILING_MODE", "off")
        mm = _manager(640)
        frame = _frame(720, 1280)
        tensors, metas = mm.preprocess_tiles(frame)
        assert not mm.tiling_active
        assert len(tensors) == 1 and len(metas) == 1
        meta = metas[0]
        assert (meta.ox, meta.oy, meta.width, meta.height) == (0, 0, 1280, 720)
        expected, scale, border_top, size = mm.preprocess_image(frame)
        assert (meta.scale, meta.border_top, meta.input_size) == (scale, border_top, size)
        np.testing.assert_array_equal(tensors[0], expected)

    @pytest.mark.parametrize("frame_hw,side,origins", [
        ((720, 1280), 720, [(0, 0), (560, 0)]),
        ((1080, 1920), 1080, [(0, 0), (840, 0)]),
        ((480, 640), 480, [(0, 0), (160, 0)]),
    ])
    def test_grid_defaults_give_two_columns_on_any_16x9_or_4x3_frame(
            self, monkeypatch, frame_hw, side, origins):
        # Default mode with the auto tile: the tile spans the frame's short
        # side, so the grid is two columns whatever the camera's pixel count
        # (the trailing tile slides back to the frame edge).
        monkeypatch.delenv("TILING_MODE", raising=False)
        monkeypatch.delenv("TILING_TILE", raising=False)
        mm = _manager(640)
        tensors, metas = mm.preprocess_tiles(_frame(*frame_hw))
        assert mm.tiling_active
        assert len(tensors) == 2
        assert [(m.ox, m.oy) for m in metas] == origins
        for tensor, meta in zip(tensors, metas, strict=True):
            assert tensor.shape == (1, 3, 640, 640)
            assert (meta.width, meta.height) == (side, side)
            assert meta.border_top == 0  # square crop: no letterbox bands
            assert meta.scale == pytest.approx(side / 640)
            assert meta.input_size == 640

    def test_explicit_pixel_tile_pins_the_grid(self, monkeypatch):
        monkeypatch.setenv("TILING_MODE", "grid")
        monkeypatch.setenv("TILING_TILE", "640")
        mm = _manager(640)
        tensors, metas = mm.preprocess_tiles(_frame(720, 1280))
        # Three columns x two rows, row-major — a pinned side ignores the aspect ratio.
        assert len(tensors) == 6
        assert [(m.ox, m.oy) for m in metas] == [
            (0, 0), (512, 0), (640, 0), (0, 80), (512, 80), (640, 80)]
        assert all((m.width, m.height) == (640, 640) for m in metas)

    def test_grid_on_a_square_frame_degenerates_to_one_tile(self, monkeypatch):
        monkeypatch.setenv("TILING_MODE", "grid")
        monkeypatch.delenv("TILING_TILE", raising=False)
        mm = _manager(640)
        tensors, metas = mm.preprocess_tiles(_frame(500, 500))
        assert len(tensors) == 1
        meta = metas[0]
        assert (meta.ox, meta.oy, meta.width, meta.height) == (0, 0, 500, 500)

    def test_pixel_tile_larger_than_the_frame_degenerates_to_one_tile(self, monkeypatch):
        monkeypatch.setenv("TILING_MODE", "grid")
        monkeypatch.setenv("TILING_TILE", "720")
        mm = _manager(640)
        tensors, metas = mm.preprocess_tiles(_frame(360, 640))
        assert len(tensors) == 1
        meta = metas[0]
        assert (meta.ox, meta.oy, meta.width, meta.height) == (0, 0, 640, 360)
