"""
Configuration file for object detection.
Contains all configurations and environment variables.
"""
import os

class Config:
    """Class to manage all system configurations."""

    def __init__(self):
        # Detection settings
        self.CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", default=0.75))
        self.OVERLAY_THRESHOLD = float(os.environ.get("OVERLAY_THRESHOLD", default=0.45))
        
        # Capture settings - use appropriate device for platform
        if os.name == 'nt':  # Windows
            default_capture_device = "0"  # Webcam index
        else:  # Linux/Unix
            default_capture_device = "/dev/media0"

        self.CAPTURE_DEVICE = os.environ.get("CAPTURE_DEVICE", default=default_capture_device)
        self.CAPTURE_RESOLUTION_X = int(os.environ.get("CAPTURE_RESOLUTION_X", default=640))
        self.CAPTURE_RESOLUTION_Y = int(os.environ.get("CAPTURE_RESOLUTION_Y", default=640))
        self.CAPTURE_FRAMERATE = int(os.environ.get("CAPTURE_FRAMERATE", default=30))

        # Model settings — models live in the shared volume mounted from
        # the `os` container at /data/models.
        self.MODELS_DIR = os.environ.get("MODELS_DIR", default="/data/models")
        self.MODEL_PATH = os.environ.get(
            "MODEL_PATH",
            default=os.path.join(self.MODELS_DIR, "weights.engine"),
        )

        # Label file path — sibling .txt of the active model file
        # (e.g. weights.engine -> weights.txt). Switched on model selection
        # by ModelService.select_model(). Env override stays supported for
        # legacy deployments.
        model_base, _ = os.path.splitext(self.MODEL_PATH)
        self.CLASSES_FILE_PATH = os.environ.get(
            "CLASSES_FILE_PATH",
            default=f"{model_base}.txt",
        )
        
        # Default labels
        self.DEFAULT_LABELS = ["CLASS1", "CLASS2", "CLASS3"]

        # Shared memory settings
        self.SHM_NAME = os.environ.get("SHM_NAME", "conecsa_frame_shm")

        # Offline detection buffer (store-and-forward while the hub is not
        # polling). Ring-buffer caps: whichever limit is hit first evicts the
        # oldest records. The threshold is how long without a hub snapshot
        # pull before the device considers the hub offline.
        self.DETECTION_BUFFER_MAX_RECORDS = int(
            os.environ.get("DETECTION_BUFFER_MAX_RECORDS", default=5000))
        self.DETECTION_BUFFER_MAX_BYTES = int(
            os.environ.get("DETECTION_BUFFER_MAX_BYTES", default=1_073_741_824))
        self.HUB_OFFLINE_THRESHOLD_SEC = float(
            os.environ.get("HUB_OFFLINE_THRESHOLD_SEC", default=5.0))

    def set_overlay_threshold(self, threshold: float) -> bool:
        """Set the overlay threshold value."""
        if 0.0 <= threshold <= 1.0:
            self.OVERLAY_THRESHOLD = threshold
            return True
        return False
