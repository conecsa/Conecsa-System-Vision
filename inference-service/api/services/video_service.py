"""
Video service - owns the camera configuration exchanged with the webcam-server.

Frame transport (SHM read/fan-out) now lives in ``ConsumerService`` and the
image operations (decode/encode/stereo/RGB) in ``FrameCodecService``; this
service is the camera-config facade used by the config/settings controllers:
it merges and writes ``CameraConfig`` into the SHM config region and reads the
producer health, and it delegates stereo settings to the codec so existing
callers keep a single entry point.
"""
import json
import logging
import os
import time

from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Health values published by the webcam-server into the SHM header (see
# proto/shm.proto). Only "capturing" means frames are actually flowing.
CAMERA_STATUS_CAPTURING = "capturing"
CAMERA_STATUS_NO_CAMERA = "no_camera"


class VideoService:
    """Camera configuration + producer health (via the shared SHM transport)."""

    def __init__(self, consumer_service, codec_service):
        """
        Args:
            consumer_service: ConsumerService owning the SHM transport.
            codec_service: FrameCodecService owning stereo/codec configuration.
        """
        self._consumer = consumer_service
        self._codec = codec_service

        # Last config successfully written to the webcam-server via SHM.
        # Used as the base when merging partial patches so we don't need to
        # round-trip config fields through HealthStatus.
        # Defaults mirror the webcam-server env vars defined in docker-compose.yml.
        _framerate = int(os.environ.get("CAPTURE_FRAMERATE", 30))
        self._current_config: Dict = {
            "camera_index":  int(os.environ.get("CAMERA_INDEX",          0)),
            "width":         int(os.environ.get("CAPTURE_WIDTH",          640)),
            "height":        int(os.environ.get("CAPTURE_HEIGHT",         640)),
            "framerate":     _framerate,
            "auto_exposure": os.environ.get("CAPTURE_AUTO_EXPOSURE", "false").lower() == "true",
            "exposure_time": int(os.environ.get("CAPTURE_EXPOSURE_TIME",  10_000 // max(_framerate, 1))),
            "rgb_red":       int(os.environ.get("CAPTURE_RGB_RED",        128)),
            "rgb_green":     int(os.environ.get("CAPTURE_RGB_GREEN",      128)),
            "rgb_blue":      int(os.environ.get("CAPTURE_RGB_BLUE",       128)),
            "gamma":         int(os.environ.get("CAPTURE_GAMMA",          100)),
            "gain":          int(os.environ.get("CAPTURE_GAIN",           0)),
        }

    # ------------------------------------------------------------------
    # Webcam-server config (via SHM)
    # ------------------------------------------------------------------

    def get_webcam_server_config(self) -> Optional[Dict]:
        """Return the webcam-server status plus the last-known config."""
        health = self._consumer.read_health()
        if health:
            return {"status": health.status, **self._current_config}
        return None

    # ------------------------------------------------------------------
    # Camera liveness (SHM health) — the gate for starting detection
    # ------------------------------------------------------------------

    def camera_status(self) -> str:
        """Return the webcam-server health status, or ``"no_camera"`` when the
        SHM segment carries no health yet (producer down / not started)."""
        health = self._consumer.read_health()
        return health.status if health else CAMERA_STATUS_NO_CAMERA

    def camera_connected(self) -> bool:
        """True only while the webcam-server is actually streaming a camera.

        The webcam-server publishes no frames at all without a camera, so any
        status other than ``"capturing"`` means detection would run blind.
        """
        return self.camera_status() == CAMERA_STATUS_CAPTURING

    def wait_for_camera(self, timeout: float = 15.0, interval: float = 0.5) -> bool:
        """Poll the SHM health until the camera streams, or ``timeout`` elapses.

        Used at startup: the webcam-server opens the device concurrently with
        the inference boot, so a plain check would race it.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self.camera_connected():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)

    def get_current_camera_config(self) -> Dict:
        """Return a copy of the last-applied camera configuration (for persistence)."""
        return dict(self._current_config)

    def rgb_levels(self) -> Tuple[int, int, int]:
        """Return the current software RGB levels ``(r, g, b)`` (128 = neutral)."""
        c = self._current_config
        return (
            int(c.get("rgb_red", 128)),
            int(c.get("rgb_green", 128)),
            int(c.get("rgb_blue", 128)),
        )

    def apply_webcam_server_config(self, patch: Dict) -> bool:
        """Write camera config into the SHM config region.

        Merges the given patch over the last-known configuration stored in
        ``self._current_config`` so that partial updates don't reset other
        fields. Returns True on success.
        """
        try:
            from ..proto import shm_pb2  # pyright: ignore[reportMissingImports]

            # Merge patch over the last-known config.
            base = {**self._current_config, **patch}

            cfg = shm_pb2.CameraConfig(
                camera_index=base["camera_index"],
                width=base["width"],
                height=base["height"],
                framerate=base["framerate"],
                auto_exposure=base["auto_exposure"],
                exposure_time=base["exposure_time"],
                rgb_red=base["rgb_red"],
                rgb_green=base["rgb_green"],
                rgb_blue=base["rgb_blue"],
                gamma=base["gamma"],
                gain=base["gain"],
            )
            self._consumer.write_config(cfg)
            self._current_config = base
            return True
        except Exception as ex:
            logger.error(f"Failed to write config to SHM: {ex}")
            return False

    # ------------------------------------------------------------------
    # Camera devices + update (business logic; controllers/gRPC are thin)
    # ------------------------------------------------------------------

    def list_camera_devices(self) -> Dict:
        """Enumerate V4L2 devices and return them with the current camera +
        stereo configuration (the payload the camera-devices endpoint serves)."""
        devices = []
        try:
            if os.path.isdir("/dev"):
                for entry in sorted(os.listdir("/dev")):
                    if not entry.startswith("video"):
                        continue
                    full = os.path.join("/dev", entry)
                    try:
                        idx = int(entry.replace("video", ""))
                        name_path = f"/sys/class/video4linux/{entry}/name"
                        name = (open(name_path).read().strip()
                                if os.path.isfile(name_path) else entry)
                        devices.append({"path": full, "index": idx, "name": name})
                    except (ValueError, OSError):
                        devices.append({"path": full, "index": -1, "name": entry})
        except Exception as ex:  # noqa: BLE001
            logger.warning("Could not enumerate camera devices: %s", ex)

        supported_formats: Dict = {}
        try:
            fp = "/dev/shm/conecsa_camera_formats.json"
            if os.path.isfile(fp):
                with open(fp) as f:
                    supported_formats = json.load(f)
        except Exception as ex:  # noqa: BLE001
            logger.warning("Could not read camera formats: %s", ex)

        wc = self.get_webcam_server_config()
        g = lambda k, d: wc.get(k, d) if wc else d  # noqa: E731
        camera_status = g("status", CAMERA_STATUS_NO_CAMERA)
        stereo = self.get_stereo_config()
        cur_index = g("camera_index", 0)
        cur_path = f"/dev/video{cur_index}"
        if cur_path not in {d["path"] for d in devices} and cur_index >= 0:
            devices.insert(0, {"path": cur_path, "index": cur_index, "name": f"video{cur_index}"})
        for d in devices:
            d["supported_formats"] = supported_formats.get(d["path"], [])

        return {
            "devices": devices, "supported_formats": supported_formats,
            "camera_status": camera_status,
            "camera_connected": camera_status == CAMERA_STATUS_CAPTURING,
            "current_device": cur_path, "current_index": cur_index,
            "current_width": g("width", 640), "current_height": g("height", 640),
            "current_framerate": g("framerate", 30),
            "current_auto_exposure": g("auto_exposure", False),
            "current_exposure_time": g("exposure_time", 333),
            "current_rgb_red": g("rgb_red", 128), "current_rgb_green": g("rgb_green", 128),
            "current_rgb_blue": g("rgb_blue", 128), "current_gamma": g("gamma", 100),
            "current_gain": g("gain", 0),
            "exposure_time_min": g("exposure_time_min", 1),
            "exposure_time_max": g("exposure_time_max", 300000),
            "current_stereo_enabled": bool(stereo.get("enabled", False)),
            "current_stereo_blend_alpha": float(stereo.get("alpha", 0.5)),
            "current_stereo_offset": float(stereo.get("offset", 0.0)),
            "current_stereo_offset_y": float(stereo.get("offset_y", 0.0)),
        }

    def apply_camera_update(self, data: Dict) -> Tuple[bool, str, int]:
        """Validate + apply a camera-config patch (webcam fields + stereo).

        Returns ``(ok, message, status)`` where status mirrors the HTTP codes
        (200 ok, 400 validation, 503 webcam unreachable) so both the REST
        controller and the gRPC servicer can stay thin.
        """
        def _bool(v):
            """Coerce a bool/str/number request value to a bool."""
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.strip().lower() in {"1", "true", "yes", "on"}
            return bool(v)

        patch: Dict = {}
        try:
            for key in ("camera_index", "width", "height"):
                if key in data:
                    patch[key] = int(data[key])
            if "framerate" in data:
                fr = int(data["framerate"])
                if not 1 <= fr <= 240:
                    return False, "framerate must be between 1 and 240", 400
                patch["framerate"] = fr
            if "auto_exposure" in data:
                patch["auto_exposure"] = _bool(data["auto_exposure"])
            for key, lo, hi in (("exposure_time", 1, 300000), ("rgb_red", 0, 255),
                                ("rgb_green", 0, 255), ("rgb_blue", 0, 255),
                                ("gamma", 1, 500), ("gain", 0, 480)):
                if key in data:
                    val = int(data[key])
                    if not lo <= val <= hi:
                        return False, f"{key} must be between {lo} and {hi}", 400
                    patch[key] = val

            stereo_enabled = _bool(data["stereo_enabled"]) if "stereo_enabled" in data else None
            stereo_alpha = stereo_offset = stereo_offset_y = None
            if "stereo_blend_alpha" in data:
                stereo_alpha = float(data["stereo_blend_alpha"])
                if not 0.0 <= stereo_alpha <= 1.0:
                    return False, "stereo_blend_alpha must be between 0.0 and 1.0", 400
            if "stereo_offset" in data:
                stereo_offset = float(data["stereo_offset"])
                if not -0.5 <= stereo_offset <= 0.5:
                    return False, "stereo_offset must be between -0.5 and 0.5", 400
            if "stereo_offset_y" in data:
                stereo_offset_y = float(data["stereo_offset_y"])
                if not -0.5 <= stereo_offset_y <= 0.5:
                    return False, "stereo_offset_y must be between -0.5 and 0.5", 400
            has_stereo = any(v is not None for v in
                             (stereo_enabled, stereo_alpha, stereo_offset, stereo_offset_y))
            if not patch and not has_stereo:
                return False, "No recognised camera fields provided", 400

            if has_stereo:
                self.set_stereo_config(stereo_enabled, stereo_alpha, stereo_offset, stereo_offset_y)
            if patch and not self.apply_webcam_server_config(patch):
                return False, "Failed to reach webcam server. Ensure it is running and shared memory is accessible.", 503
            return True, "Camera configuration applied", 200
        except Exception as ex:  # noqa: BLE001
            return False, str(ex), 500

    # ------------------------------------------------------------------
    # Stereo configuration (delegated to the codec)
    # ------------------------------------------------------------------

    def get_stereo_config(self) -> Dict:
        """Return the current stereo combine settings."""
        return self._codec.get_stereo_config()

    def set_stereo_config(
        self,
        enabled: Optional[bool] = None,
        alpha: Optional[float] = None,
        offset: Optional[float] = None,
        offset_y: Optional[float] = None,
    ) -> None:
        """Update stereo combine settings (partial; unset fields are kept)."""
        self._codec.set_stereo_config(enabled, alpha, offset, offset_y)
