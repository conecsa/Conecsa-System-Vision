"""Unit tests for the FedAvg checkpoint averager math (CPU, tiny modules)."""
import pytest

torch = pytest.importorskip("torch")

from service._weights_averager import _average_state_dicts, _merge_checkpoints


def _model(fill: float):  # -> torch.nn.Module (torch is an importorskip handle, not a module symbol)
    m = torch.nn.Sequential(torch.nn.Linear(2, 2), torch.nn.BatchNorm1d(2))
    with torch.no_grad():
        for p in m.parameters():
            p.fill_(fill)
    return m.half()


class TestAverageStateDicts:
    def test_float_tensors_are_averaged(self):
        a, b = _model(1.0), _model(3.0)
        avg = _average_state_dicts([a.state_dict(), b.state_dict()])
        weight = avg["0.weight"]
        assert weight.dtype == torch.float16
        assert torch.allclose(weight.float(), torch.full((2, 2), 2.0))

    def test_non_float_buffers_come_from_first(self):
        a, b = _model(1.0), _model(1.0)
        a[1].num_batches_tracked.fill_(7)
        b[1].num_batches_tracked.fill_(99)
        avg = _average_state_dicts([a.state_dict(), b.state_dict()])
        assert avg["1.num_batches_tracked"].item() == 7

    def test_mismatched_keys_raise(self):
        a = _model(1.0)
        b = torch.nn.Linear(2, 2).half()
        with pytest.raises(RuntimeError):
            _average_state_dicts([a.state_dict(), b.state_dict()])

    def test_mismatched_shapes_raise(self):
        a = torch.nn.Linear(2, 2).half()
        b = torch.nn.Linear(2, 3).half()
        sd_b = {k.replace("weight", "weight"): v for k, v in b.state_dict().items()}
        with pytest.raises(RuntimeError):
            _average_state_dicts([a.state_dict(), sd_b])


class TestMergeCheckpoints:
    def test_model_and_ema_averaged_optimizer_dropped(self):
        ckpts = [
            {"model": _model(1.0), "ema": _model(5.0), "optimizer": {"state": 1}},
            {"model": _model(3.0), "ema": _model(7.0), "optimizer": {"state": 2}},
        ]
        merged = _merge_checkpoints(ckpts)
        model_w = merged["model"].state_dict()["0.weight"].float()
        ema_w = merged["ema"].state_dict()["0.weight"].float()
        assert torch.allclose(model_w, torch.full((2, 2), 2.0))
        assert torch.allclose(ema_w, torch.full((2, 2), 6.0))
        assert merged["optimizer"] is None

    def test_partial_ema_is_dropped(self):
        ckpts = [
            {"model": _model(1.0), "ema": _model(5.0)},
            {"model": _model(3.0), "ema": None},
        ]
        merged = _merge_checkpoints(ckpts)
        assert merged["ema"] is None

    def test_missing_model_raises(self):
        with pytest.raises(RuntimeError):
            _merge_checkpoints([{"model": None}, {"model": _model(1.0)}])
