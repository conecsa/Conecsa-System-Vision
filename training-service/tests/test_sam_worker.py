"""Unit tests for the pure SAM worker box helpers and load-path plumbing."""
from types import SimpleNamespace

import numpy as np
import pytest

from service import _sam_worker
from service._sam_worker import (
    _INIT_FNS,
    _mask_to_xyxy,
    _skip_param_init,
    _start_cache_warmer,
    _to_list,
    _warm_page_cache,
    _xyxy_to_yolo,
)


class TestToList:
    def test_none_returns_empty(self):
        assert _to_list(None) == []

    def test_numpy_array_uses_tolist(self):
        assert _to_list(np.array([1, 2, 3])) == [1, 2, 3]

    def test_plain_iterable(self):
        assert _to_list((1, 2)) == [1, 2]


class TestMaskToXyxy:
    def test_empty_mask_returns_none(self):
        assert _mask_to_xyxy(np.zeros((10, 10))) is None

    def test_bounding_box_of_blob(self):
        mask = np.zeros((10, 10))
        mask[2:5, 3:7] = 1.0  # rows 2..4, cols 3..6
        assert _mask_to_xyxy(mask) == [3.0, 2.0, 6.0, 4.0]

    def test_threshold_at_half(self):
        mask = np.zeros((5, 5))
        mask[1, 1] = 0.6  # above 0.5
        mask[3, 3] = 0.4  # below 0.5 -> ignored
        assert _mask_to_xyxy(mask) == [1.0, 1.0, 1.0, 1.0]


class TestXyxyToYolo:
    def test_centered_box(self):
        # box (20,40)-(60,80) in a 100x200 image
        out = _xyxy_to_yolo([20, 40, 60, 80], width=100, height=200)
        assert out["cx"] == pytest.approx(0.4)
        assert out["cy"] == pytest.approx(0.3)
        assert out["w"] == pytest.approx(0.4)
        assert out["h"] == pytest.approx(0.2)

    def test_values_are_clamped_to_unit_range(self):
        out = _xyxy_to_yolo([-50, -50, 200, 400], width=100, height=200)
        assert 0.0 <= out["cx"] <= 1.0
        assert 0.0 <= out["cy"] <= 1.0
        assert out["w"] == 1.0
        assert out["h"] == 1.0

    def test_ignores_extra_coordinates(self):
        # Only the first four values are used.
        out = _xyxy_to_yolo([0, 0, 100, 200, 999], width=100, height=200)
        assert out["cx"] == pytest.approx(0.5)


def _torch_stub():
    """A torch lookalike exposing the nn.init fillers (host venv has no torch,
    which is why _skip_param_init takes the module as a parameter)."""
    def _filler(tensor, *args, **kwargs):
        raise AssertionError("real init filler must not run inside the block")

    init = SimpleNamespace(**{name: _filler for name in _INIT_FNS})
    return SimpleNamespace(nn=SimpleNamespace(init=init))


class TestSkipParamInit:
    def test_fillers_are_noops_inside_and_restored_after(self):
        torch = _torch_stub()
        originals = {n: getattr(torch.nn.init, n) for n in _INIT_FNS}
        sentinel = object()
        with _skip_param_init(torch):
            for name in _INIT_FNS:
                # No-op: returns the tensor unchanged instead of raising.
                assert getattr(torch.nn.init, name)(sentinel, 0.02) is sentinel
        for name in _INIT_FNS:
            assert getattr(torch.nn.init, name) is originals[name]

    def test_restores_even_when_the_body_raises(self):
        torch = _torch_stub()
        originals = {n: getattr(torch.nn.init, n) for n in _INIT_FNS}
        with pytest.raises(RuntimeError):
            with _skip_param_init(torch):
                raise RuntimeError("build failed")
        for name in _INIT_FNS:
            assert getattr(torch.nn.init, name) is originals[name]

    def test_missing_fillers_are_tolerated(self):
        # Older torch builds may lack some fillers; only patch what exists.
        torch = _torch_stub()
        del torch.nn.init.sparse_
        with _skip_param_init(torch):
            pass
        assert not hasattr(torch.nn.init, "sparse_")


class TestWarmPageCache:
    def test_reads_the_whole_file(self, tmp_path):
        path = tmp_path / "ckpt.pt"
        path.write_bytes(b"x" * 1024)
        _warm_page_cache(str(path))  # must not raise

    def test_missing_file_is_harmless(self, tmp_path):
        _warm_page_cache(str(tmp_path / "absent.pt"))  # logs, no raise


class TestStartCacheWarmer:
    def test_disabled_by_env(self, monkeypatch, tmp_path):
        spawned = []
        monkeypatch.setattr(
            _sam_worker, "threading",
            SimpleNamespace(Thread=lambda **kw: spawned.append(kw)))
        monkeypatch.setenv("SAM3_WARM_CACHE", "0")
        _start_cache_warmer(str(tmp_path / "ckpt.pt"))
        assert spawned == []

    def test_enabled_by_default(self, monkeypatch, tmp_path):
        started = []

        class FakeThread:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def start(self):
                started.append(self.kwargs)

        monkeypatch.setattr(_sam_worker, "threading",
                            SimpleNamespace(Thread=FakeThread))
        monkeypatch.delenv("SAM3_WARM_CACHE", raising=False)
        _start_cache_warmer(str(tmp_path / "ckpt.pt"))
        assert len(started) == 1
        assert started[0]["daemon"] is True
