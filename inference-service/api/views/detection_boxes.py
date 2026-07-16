"""
Pure box-decoding helpers for YOLO output post-processing.

Stateless numeric functions used by ``YOLODetector``: score extraction,
center→corner conversion (letterbox-aware), debug boxes and NMS. No detector
state and no drawing here.
"""
from typing import Optional

# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

# noinspection PyPackageRequirements
import cv2  # Package is included on os build.


def sigmoid(x):
    """Element-wise logistic sigmoid ``1 / (1 + e**-x)``."""
    return 1.0 / (1.0 + np.exp(-x))


def extract_class_info(detection, output_format: Optional[str] = "multiclass"):
    """
    Extract class ID and confidence from detection.

    Args:
        detection: Single detection array
        output_format: Format type ("multiclass" or "single_class"). ``None`` means
            the detector has not yet inferred the format from the model output; it
            takes the multiclass path, as any non-"single_class" value does.

    Returns:
        tuple: (class_id, confidence)
    """
    if output_format == "single_class":
        # Format: [x, y, w, h, confidence] - single class or objectness
        confidence = detection[4]
        class_id = 0  # Default to class 0 for single-class models
        return class_id, confidence
    else:
        # YOLOv8/YOLO11 one-to-many format: [x, y, w, h, cls0, cls1, ..., clsN] — no objectness
        class_scores = detection[4:]
        if len(class_scores) > 0:
            class_id = int(np.argmax(class_scores))
            confidence = float(np.max(class_scores))
        else:
            class_id = 0
            confidence = 0.0
        return class_id, confidence


def calculate_box_from_center(center_x, center_y, box_size, img_width, img_height):
    """
    Calculate bounding box coordinates from center point and size.

    Args:
        center_x: Center X coordinate in pixels
        center_y: Center Y coordinate in pixels
        box_size: Box size in pixels
        img_width: Image width
        img_height: Image height

    Returns:
        tuple: (x1, y1, x2, y2) coordinates
    """
    x1 = max(0, center_x - box_size // 2)
    y1 = max(0, center_y - box_size // 2)
    x2 = min(img_width, center_x + box_size // 2)
    y2 = min(img_height, center_y + box_size // 2)
    return x1, y1, x2, y2


def corners_from_normalized(x_min, y_min, x_max, y_max, frame_w, frame_h,
                            scale, border_top, actual_input_size):
    """Map normalized [0, 1] corners to pixel space (letterbox-aware on Y).

    Returns None when the box collapses after clamping to [0, 1].
    """
    x_min = max(0.0, min(1.0, x_min))
    y_min = max(0.0, min(1.0, y_min))
    x_max = max(0.0, min(1.0, x_max))
    y_max = max(0.0, min(1.0, y_max))
    if not (x_min < x_max and y_min < y_max):
        return None

    # X-axis: no letterbox padding (width fills the full model input).
    x1 = int(x_min * frame_w)
    x2 = int(x_max * frame_w)
    # Y-axis: account for letterbox padding added during preprocessing.
    # Formula: y_pixel = (y_norm * model_height - border_top) * scale
    if actual_input_size and actual_input_size > 0:
        y1 = int((y_min * actual_input_size - border_top) * scale)
        y2 = int((y_max * actual_input_size - border_top) * scale)
    else:
        y1 = int(y_min * frame_h)
        y2 = int(y_max * frame_h)
    return x1, y1, x2, y2


def corners_from_pixel(x_min, y_min, x_max, y_max, scale_x, scale_y,
                       scale, border_top, actual_input_size):
    """Map model-pixel-space corners to frame pixels (letterbox-aware on Y)."""
    # X: no padding on x-axis.
    x1 = int(x_min * scale_x)
    x2 = int(x_max * scale_x)
    # Y: remove letterbox offset before scaling to original frame.
    if actual_input_size and actual_input_size > 0:
        y1 = int((y_min - border_top) * scale)
        y2 = int((y_max - border_top) * scale)
    else:
        y1 = int(y_min * scale_y)
        y2 = int(y_max * scale_y)
    return x1, y1, x2, y2


def apply_nms(boxes, confidences, class_ids, overlay_threshold=0.45):
    """
    Apply Non-Maximum Suppression to filter overlapping boxes.

    Args:
        boxes: List of boxes as [x1, y1, x2, y2]
        confidences: List of confidence scores
        class_ids: List of class IDs
        overlay_threshold: IoU threshold for suppression

    Returns:
        tuple: (filtered_boxes, filtered_confidences, filtered_class_ids)
    """
    if len(boxes) == 0:
        return [], [], []

    boxes_np = np.asarray(boxes, dtype=np.int32)
    confidences_np = np.asarray(confidences, dtype=np.float32)
    class_ids_np = np.asarray(class_ids, dtype=np.int32)

    # OpenCV NMSBoxes expects [x, y, w, h]
    bboxes_xywh = []
    for x1, y1, x2, y2 in boxes_np:
        bboxes_xywh.append([int(x1), int(y1), int(max(1, x2 - x1)), int(max(1, y2 - y1))])

    # Confidence filtering already happened upstream (CONFIDENCE_THRESHOLD in
    # YOLODetector); here NMS must only suppress by IoU, so keep every box.
    score_threshold = 0.0
    indices = cv2.dnn.NMSBoxes(bboxes_xywh, confidences_np.tolist(), score_threshold, float(overlay_threshold))

    if indices is None or len(indices) == 0:
        return [], [], []

    keep = np.array(indices).reshape(-1)
    return (
        boxes_np[keep].tolist(),
        confidences_np[keep].astype(float).tolist(),
        class_ids_np[keep].astype(int).tolist(),
    )
