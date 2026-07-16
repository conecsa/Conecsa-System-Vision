"""Unit tests for the camera gate: VideoService liveness + DetectionService.start.

The webcam-server publishes no frames at all when the camera is absent (it used
to serve a test pattern, which the model happily detected), so detection must
refuse to start unless the SHM health says "capturing".
"""
from types import SimpleNamespace

import pytest

from api.services.detection_service import DetectionService
from api.services.video_service import VideoService


class FakeConsumer:
    """ConsumerService stand-in exposing only the health read."""

    def __init__(self, status):
        self._status = status

    def read_health(self):
        return SimpleNamespace(status=self._status) if self._status else None


def _video(status):
    return VideoService(FakeConsumer(status), codec_service=SimpleNamespace())


@pytest.mark.parametrize(
    "status, connected",
    [("capturing", True), ("no_camera", False), ("starting", False), (None, False)],
)
def test_camera_connected_only_while_capturing(status, connected):
    video = _video(status)
    assert video.camera_connected() is connected


def test_camera_status_defaults_to_no_camera_without_health():
    assert _video(None).camera_status() == "no_camera"


def test_wait_for_camera_gives_up_after_timeout():
    assert _video("no_camera").wait_for_camera(timeout=0.0, interval=0.0) is False


def test_wait_for_camera_returns_immediately_when_streaming():
    assert _video("capturing").wait_for_camera(timeout=0.0, interval=0.0) is True


def test_start_refuses_without_camera():
    # SimpleNamespace stands in for Config: the camera gate short-circuits before
    # anything reads a config field.
    det = DetectionService(SimpleNamespace(), video_service=_video("no_camera"))  # pyright: ignore[reportArgumentType]

    with pytest.raises(RuntimeError, match="No camera connected"):
        det.start()

    assert det.is_running is False


def test_start_proceeds_with_camera(monkeypatch):
    det = DetectionService(SimpleNamespace(), video_service=_video("capturing"))  # pyright: ignore[reportArgumentType]
    monkeypatch.setattr(det, "initialize", lambda: True)

    assert det.start() is True
    assert det.is_running is True
