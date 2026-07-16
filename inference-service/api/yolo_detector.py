"""
YOLO detections processor.
"""
import logging
import os
from typing import Optional

# noinspection PyPackageRequirements
import numpy as np # Package is included on os build.

# noinspection PyPackageRequirements
import cv2 # Package is included on os build.

from .models.detection_models import Detection
from .utils import bgr_to_hex, generate_colors, resolve_class_colors
from .views.area_overlay import draw_areas
from .views.detection_boxes import (
    apply_nms, calculate_box_from_center, corners_from_normalized,
    corners_from_pixel, extract_class_info, sigmoid,
)

logger = logging.getLogger(__name__)

# End-to-end (YOLO26) heads emit at most 300 rows (ultralytics max_det
# default). Deliberately a constant and not YOLO_MAX_CANDIDATES: that knob is
# env-tunable and must not change how the output layout is classified.
_E2E_MAX_DET = 300


class YOLODetector:
    """Class to process detections from custom YOLO model."""

    def __init__(self, class_labels, config):
        self.class_labels = []
        self.class_colors = []
        self.config = config
        self.num_classes_detected: Optional[int] = None  # Detected dynamically from the model
        self.output_format: Optional[str] = None  # Detected from model output shape
        self.max_candidates = int(os.environ.get("YOLO_MAX_CANDIDATES", "300"))
        self.nms_top_k = int(os.environ.get("YOLO_NMS_TOPK", "120"))
        # Per-frame snapshot of active detection areas (normalized [0,1]).
        # Updated by DetectionService.prepare before each inference.
        self._areas = []

        self._set_class_metadata(class_labels)

    # ------------------------------------------------------------------
    # Class metadata (labels + colors)
    # ------------------------------------------------------------------

    def _set_class_metadata(self, class_labels):
        """
        Parse class labels and optional custom colors.
        """
        self.class_labels, self.class_colors = resolve_class_colors(class_labels)

    def _adopt_output_format(self, output_format, num_classes):
        """First-run sync of the format + label/color tables to the model output."""
        self.output_format = output_format
        self.num_classes_detected = num_classes

        # Adjust class_labels if necessary
        if len(self.class_labels) != num_classes:
            if output_format == "single_class":
                # For single class, use first label or generic
                self.class_labels = [self.class_labels[0] if self.class_labels else "Object"]
            else:
                # Add generic classes if necessary
                while len(self.class_labels) < num_classes:
                    self.class_labels.append(f"Class-{len(self.class_labels)}")

            fallback_colors = generate_colors(len(self.class_labels))
            while len(self.class_colors) < len(self.class_labels):
                self.class_colors.append(fallback_colors[len(self.class_colors)])

        # Ensure color table matches label table size
        if len(self.class_colors) != len(self.class_labels):
            fallback_colors = generate_colors(len(self.class_labels))
            self.class_colors = [
                self.class_colors[i] if i < len(self.class_colors) else fallback_colors[i]
                for i in range(len(self.class_labels))
            ]

    def _get_class_label(self, class_id, confidence):
        """Format the label text ("name: 0.87") for a detection."""
        if class_id < len(self.class_labels):
            return f"{self.class_labels[class_id]}: {confidence:.2f}"
        return f"Class {class_id}: {confidence:.2f}"

    def _get_class_color(self, class_id):
        """Return the BGR color tuple for a class ID."""
        if not self.class_colors:
            return 255, 255, 255
        return self.class_colors[class_id % len(self.class_colors)]

    # ------------------------------------------------------------------
    # Detection areas (spatial filter + editing overlay)
    # ------------------------------------------------------------------

    def set_areas(self, areas):
        """Update the active detection-area snapshot for this frame."""
        self._areas = list(areas) if areas else []

    @staticmethod
    def _first_area_containing(cx, cy, areas, frame_w, frame_h):
        """Return the first area whose shape contains the pixel-space center.

        Returns None when the center falls outside every area. Overlapping
        areas resolve to the first match in ``areas`` order.
        """
        for a in areas:
            x1 = int(a.x * frame_w)
            y1 = int(a.y * frame_h)
            x2 = int((a.x + a.width) * frame_w)
            y2 = int((a.y + a.height) * frame_h)
            shape = getattr(a, "shape", "rectangle")
            if shape == "circle":
                # Ellipse inscribed in the (x1...x2, y1...y2) bbox.
                ex = (x1 + x2) / 2.0
                ey = (y1 + y2) / 2.0
                rx = max(1.0, (x2 - x1) / 2.0)
                ry = max(1.0, (y2 - y1) / 2.0)
                if ((cx - ex) ** 2) / (rx * rx) + ((cy - ey) ** 2) / (ry * ry) <= 1.0:
                    return a
            else:
                if x1 <= cx <= x2 and y1 <= cy <= y2:
                    return a
        return None

    @staticmethod
    def _area_summary(area):
        """Compact, JSON-friendly view of an area for per-detection tagging."""
        return {
            "id": area.id,
            "label": getattr(area, "label", ""),
            "shape": getattr(area, "shape", "rectangle"),
        }

    def _filter_detections_by_areas(self, detections, frame_w, frame_h):
        """Return only detections whose center lies inside a saved area.

        Each kept detection is tagged with the saved area that contains its
        center (``Detection.area``); the first match wins for overlaps.

        - No areas at all → no filtering (current behavior).
        - Only editing areas (none saved) → no filtering (user is still
          positioning); they'll see all detections to help calibrate.
        - At least one saved area → keep only detections inside saved areas.
        """
        if not self._areas:
            return detections
        saved = [a for a in self._areas if not a.is_editing]
        if not saved:
            return detections
        kept = []
        for d in detections:
            area = self._first_area_containing(d.center[0], d.center[1], saved, frame_w, frame_h)
            if area is not None:
                d.area = self._area_summary(area)
                kept.append(d)
        return kept

    def _draw_areas(self, img):
        """Render the editing-areas overlay (see views.area_overlay)."""
        return draw_areas(img, self._areas)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw_detection_box(self, img, x1, y1, x2, y2, class_id, confidence,
                           line_thickness=3, font_scale=0.6, draw_center=False):
        """
        Draw bounding box and label on image.

        Args:
            img: Image to draw on
            x1: Top-left x of the bounding box.
            y1: Top-left y of the bounding box.
            x2: Bottom-right x of the bounding box.
            y2: Bottom-right y of the bounding box.
            class_id: Class ID
            confidence: Detection confidence
            line_thickness: Box line thickness
            font_scale: Label font scale
            draw_center: Whether to draw a circle at the center
        """
        color = self._get_class_color(class_id)

        # Draw bounding box
        cv2.rectangle(img, (x1, y1), (x2, y2), color, line_thickness)

        # Draw center circle if requested
        if draw_center:
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2
            cv2.circle(img, (center_x, center_y), 3, color, -1)

        # Draw label
        label = self._get_class_label(class_id, confidence)
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 2)[0]

        # Draw label background
        cv2.rectangle(img, (x1, y1 - label_size[1] - 15),
                     (x1 + label_size[0] + 10, y1), color, -1)

        # Draw label text
        cv2.putText(img, label, (x1 + 5, y1 - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 2)

    # ------------------------------------------------------------------
    # Main pipeline: normalize → score → filter → decode → NMS → draw
    # ------------------------------------------------------------------

    def process_detections(self, output_data, image_original, scale=1.0, border_top=0, actual_input_size=None):
        """
        Processes detections from the YOLO model.

        Args:
            output_data: Model output data
            image_original: Original image
            scale: Scale factor for resizing coordinates
            border_top: Letterbox border size on top (in pixels)
            actual_input_size: Actual input size of the model (if different from capture resolution)

        Returns:
            tuple: (image with detections drawn, number of detections, Detection list)
        """
        detections = self._normalize_output(output_data)
        if detections is None:
            return self._draw_areas(image_original.copy()), 0, []

        if self.output_format == "end_to_end":
            return self._process_detections_end2end(
                detections, image_original,
                scale=scale, border_top=border_top, actual_input_size=actual_input_size,
            )

        img = image_original.copy()
        frame_h, frame_w = img.shape[:2]

        boxes = detections[:, :4]  # [x_center, y_center, width, height]

        # Detect coordinate mode automatically:
        # - normalized: values typically in [0, 1]
        # - pixel: values in model/input pixel space (e.g. 256, 320, 640)
        coord_sample_max = float(np.max(np.abs(boxes))) if boxes.size > 0 else 0.0
        use_normalized_coords = coord_sample_max <= 2.0

        class_ids, confidences = self._extract_scores(detections)
        valid_detections = self._confidence_mask(confidences)

        if np.any(valid_detections):
            valid_boxes, valid_confidences, valid_class_ids = self._top_candidates(
                boxes[valid_detections],
                confidences[valid_detections],
                class_ids[valid_detections],
            )

            # If ANY detection has invalid width/height, use alternative method
            if any(box[2] <= 0 or box[3] <= 0 for box in valid_boxes):
                return self._process_detections_alternative(
                    detections, image_original, valid_detections,
                    scale=scale, border_top=border_top, actual_input_size=actual_input_size,
                )

            boxes_for_nms, confidences_for_nms, class_ids_for_nms = self._decode_candidate_boxes(
                valid_boxes, valid_confidences, valid_class_ids,
                frame_w, frame_h, use_normalized_coords, scale, border_top, actual_input_size,
            )

            if boxes_for_nms:
                detection_objects = self._suppress_and_build(
                    boxes_for_nms, confidences_for_nms, class_ids_for_nms
                )
                # Filter by detection areas before drawing so that
                # filtered-out boxes never appear on the rendered frame.
                detection_objects = self._filter_detections_by_areas(detection_objects, frame_w, frame_h)

                for det in detection_objects:
                    x1, y1, x2, y2 = det.bbox
                    self._draw_detection_box(img, x1, y1, x2, y2, det.class_id, det.confidence)

                return self._draw_areas(img), len(detection_objects), detection_objects

        return self._draw_areas(img), 0, []

    def _normalize_output(self, output_data):
        """Validate + normalize the raw model output to detection rows.

        Accepts ``[1, features, detections]`` or ``[1, detections, features]``
        layouts, detects the output format (single-class vs multiclass vs
        end-to-end) on first run and returns a ``[detections, features]``
        array — or None when the shape is not a recognizable YOLO output.
        """
        if len(output_data.shape) != 3:
            return None

        # End-to-end (YOLO26) output: [1, N<=300, 6] rows of
        # [x1, y1, x2, y2, conf, cls] — already decoded, keep row order.
        # One-to-many outputs never match this: features-first is [1, 6, N]
        # and detections-first legacy exports carry thousands of anchor rows.
        if output_data.shape[2] == 6 and 6 < output_data.shape[1] <= _E2E_MAX_DET:
            if self.num_classes_detected is None:
                self._adopt_output_format("end_to_end", max(len(self.class_labels), 1))
            return output_data[0].copy()

        # Normalize layout to [1, features, detections]; some runtimes return
        # [1, detections, features] (e.g. [1, 25200, 85]).
        if output_data.shape[1] > output_data.shape[2]:
            output_data = np.transpose(output_data, (0, 2, 1))

        num_features = output_data.shape[1]
        if num_features == 5:
            # Format: [x, y, w, h, confidence] - single class or objectness only
            output_format, num_classes = "single_class", 1
        elif num_features >= 6:
            # YOLOv8/YOLO11 one-to-many format: [x, y, w, h, cls0, cls1, ..., clsN] — no objectness column
            output_format, num_classes = "multiclass", num_features - 4
        else:
            return None

        # Update the detected format and classes on first run
        if self.num_classes_detected is None:
            self._adopt_output_format(output_format, num_classes)

        # Drop the batch dimension and transpose to [detections, features].
        # IMPORTANT: use .copy() to avoid keeping a reference to runtime-owned
        # output memory.
        return output_data[0].copy().T

    def _process_detections_end2end(self, detections, image_original,
                                    scale=1.0, border_top=0, actual_input_size=None):
        """Decode end-to-end (YOLO26) rows: [x1, y1, x2, y2, conf, cls].

        Boxes arrive as already-decoded corners in model-input pixel space
        with final confidences, so there is no score extraction and no
        center→corner conversion. NMS still runs so the user-adjustable
        overlay threshold keeps suppressing near-duplicates.
        """
        img = image_original.copy()
        frame_h, frame_w = img.shape[:2]

        boxes = detections[:, :4]
        confidences = detections[:, 4]
        class_ids = detections[:, 5].astype(int)

        valid = self._confidence_mask(confidences)
        if not np.any(valid):
            return self._draw_areas(img), 0, []
        boxes = boxes[valid]
        confidences = confidences[valid]
        class_ids = class_ids[valid]

        # Detect coordinate mode automatically (parity with the main path).
        coord_sample_max = float(np.max(np.abs(boxes))) if boxes.size > 0 else 0.0
        use_normalized_coords = coord_sample_max <= 2.0

        # Pixel-space corners are in model-input space (width unpadded, Y
        # letterboxed — corners_from_pixel removes border_top and rescales).
        if actual_input_size and actual_input_size > 0:
            scale_x = frame_w / float(actual_input_size)
            scale_y = 1.0
        else:
            model_w = getattr(self.config, 'CAPTURE_RESOLUTION_X', frame_w) or frame_w
            model_h = getattr(self.config, 'CAPTURE_RESOLUTION_Y', frame_h) or frame_h
            scale_x = frame_w / float(model_w) if model_w > 0 else 1.0
            scale_y = frame_h / float(model_h) if model_h > 0 else 1.0

        boxes_for_nms = []
        confidences_for_nms = []
        class_ids_for_nms = []
        for box, confidence, class_id in zip(boxes, confidences, class_ids):
            x_min, y_min, x_max, y_max = box
            if not (x_min < x_max and y_min < y_max):
                continue
            if use_normalized_coords:
                corners = corners_from_normalized(
                    x_min, y_min, x_max, y_max, frame_w, frame_h,
                    scale, border_top, actual_input_size,
                )
                if corners is None:  # collapsed after clamping to [0, 1]
                    continue
            else:
                corners = corners_from_pixel(
                    x_min, y_min, x_max, y_max, scale_x, scale_y,
                    scale, border_top, actual_input_size,
                )
            x1, y1, x2, y2 = corners

            # Ensure within bounds
            x1 = max(0, min(x1, frame_w))
            y1 = max(0, min(y1, frame_h))
            x2 = max(0, min(x2, frame_w))
            y2 = max(0, min(y2, frame_h))

            # Check if box is large enough
            if (x2 - x1) > 5 and (y2 - y1) > 5:
                boxes_for_nms.append([x1, y1, x2, y2])
                confidences_for_nms.append(float(confidence))
                class_ids_for_nms.append(int(class_id))

        if not boxes_for_nms:
            return self._draw_areas(img), 0, []

        detection_objects = self._suppress_and_build(
            boxes_for_nms, confidences_for_nms, class_ids_for_nms
        )
        detection_objects = self._filter_detections_by_areas(detection_objects, frame_w, frame_h)

        for det in detection_objects:
            x1, y1, x2, y2 = det.bbox
            self._draw_detection_box(img, x1, y1, x2, y2, det.class_id, det.confidence)

        return self._draw_areas(img), len(detection_objects), detection_objects

    def _extract_scores(self, detections):
        """Split detection rows into per-detection class ids + confidences.

        Returns ``(class_ids, confidences)``.
        """
        if self.output_format == "single_class":
            # Single class format: [x, y, w, h, confidence]
            confidences = detections[:, 4]
            class_ids = np.zeros(len(detections), dtype=int)  # All detections are class 0
            return class_ids, confidences

        # YOLOv8/YOLO11 one-to-many format: [x, y, w, h, cls0, cls1, ..., clsN] — no objectness
        class_scores = detections[:, 4:]

        if class_scores.shape[1] > 0 and (np.max(class_scores) > 1.0 or np.min(class_scores) < 0.0):
            class_scores = sigmoid(class_scores)

        if class_scores.shape[1] > 0:
            class_ids = np.argmax(class_scores, axis=1)
            confidences = np.max(class_scores, axis=1)
            return class_ids, confidences

        class_ids = np.zeros(len(detections), dtype=int)
        confidences = np.zeros(len(detections))
        return class_ids, confidences

    def _confidence_mask(self, confidences):
        """Mask of detections above the configured confidence threshold."""
        return confidences > self.config.CONFIDENCE_THRESHOLD

    def _top_candidates(self, boxes, confidences, class_ids):
        """Limit candidate volume to keep post-processing fast on CPU."""
        if len(confidences) > self.max_candidates:
            top_idx = np.argpartition(confidences, -self.max_candidates)[-self.max_candidates:]
            return boxes[top_idx], confidences[top_idx], class_ids[top_idx]
        return boxes, confidences, class_ids

    def _decode_candidate_boxes(self, valid_boxes, valid_confidences, valid_class_ids,
                                frame_w, frame_h, use_normalized_coords,
                                scale, border_top, actual_input_size):
        """Convert center-format candidate boxes to clamped pixel corners.

        Returns the parallel lists ``(boxes, confidences, class_ids)`` ready
        for NMS. Boxes that collapse after clamping are dropped; boxes with
        unusable corners fall back to a small debug box around the center.
        """
        # In pixel mode, coordinates may be in model input resolution.
        # Scale to current frame resolution using configured capture size as reference.
        scale_x = 1.0
        scale_y = 1.0
        if not use_normalized_coords:
            model_w = getattr(self.config, 'CAPTURE_RESOLUTION_X', frame_w) or frame_w
            model_h = getattr(self.config, 'CAPTURE_RESOLUTION_Y', frame_h) or frame_h
            if model_w > 0 and model_h > 0:
                scale_x = frame_w / float(model_w)
                scale_y = frame_h / float(model_h)

        boxes_for_nms = []
        confidences_for_nms = []
        class_ids_for_nms = []

        for i, (box, confidence, class_id) in enumerate(zip(valid_boxes, valid_confidences, valid_class_ids)):
            x_center, y_center, width, height = box

            # Invalid width/height: try alternative interpretation (absolute
            # values, or a 5%-of-image fallback) before converting.
            if width <= 0 or height <= 0:
                width = abs(width) if width != 0 else 0.05
                height = abs(height) if height != 0 else 0.05

            # Convert from center format to corner format
            x_min = x_center - width / 2
            y_min = y_center - height / 2
            x_max = x_center + width / 2
            y_max = y_center + height / 2

            if x_min < x_max and y_min < y_max:
                if use_normalized_coords:
                    corners = corners_from_normalized(
                        x_min, y_min, x_max, y_max, frame_w, frame_h,
                        scale, border_top, actual_input_size,
                    )
                    if corners is None:  # collapsed after clamping to [0, 1]
                        continue
                else:
                    corners = corners_from_pixel(
                        x_min, y_min, x_max, y_max, scale_x, scale_y,
                        scale, border_top, actual_input_size,
                    )
                x1, y1, x2, y2 = corners

                # Ensure within bounds
                x1 = max(0, min(x1, frame_w))
                y1 = max(0, min(y1, frame_h))
                x2 = max(0, min(x2, frame_w))
                y2 = max(0, min(y2, frame_h))

                # Check if box is large enough
                if (x2 - x1) > 5 and (y2 - y1) > 5:
                    boxes_for_nms.append([x1, y1, x2, y2])
                    confidences_for_nms.append(float(confidence))
                    class_ids_for_nms.append(int(class_id))
            else:
                # FALLBACK: try to draw a small box around the center for debug
                if use_normalized_coords and 0 <= x_center <= 1 and 0 <= y_center <= 1:
                    logger.warning(f"Warning: Detection {i} has invalid normalized coordinates - using fallback")
                    center_x = int(x_center * frame_w)
                    if actual_input_size and actual_input_size > 0:
                        center_y = int((y_center * actual_input_size - border_top) * scale)
                    else:
                        center_y = int(y_center * frame_h)
                    center_y = max(0, min(center_y, frame_h))

                    x1, y1, x2, y2 = calculate_box_from_center(center_x, center_y, 20, frame_w, frame_h)
                    boxes_for_nms.append([x1, y1, x2, y2])
                    confidences_for_nms.append(float(confidence))
                    class_ids_for_nms.append(int(class_id))

        return boxes_for_nms, confidences_for_nms, class_ids_for_nms

    def _suppress_and_build(self, boxes, confidences, class_ids):
        """Cap to top-K, apply NMS and build the ``Detection`` objects."""
        if len(confidences) > self.nms_top_k:
            conf_arr = np.asarray(confidences)
            top_idx = np.argpartition(conf_arr, -self.nms_top_k)[-self.nms_top_k:]
            boxes = [boxes[i] for i in top_idx]
            confidences = [confidences[i] for i in top_idx]
            class_ids = [class_ids[i] for i in top_idx]

        filtered_boxes, filtered_confidences, filtered_class_ids = apply_nms(
            boxes, confidences, class_ids, self.config.OVERLAY_THRESHOLD
        )

        detection_objects = []
        for box, confidence, class_id in zip(filtered_boxes, filtered_confidences, filtered_class_ids):
            x1, y1, x2, y2 = box
            class_name = self.class_labels[class_id] if class_id < len(self.class_labels) else f"Class-{class_id}"
            detection_objects.append(Detection(
                class_id=int(class_id),
                class_name=class_name,
                confidence=float(confidence),
                bbox=(int(x1), int(y1), int(x2), int(y2)),
                center=((int(x1) + int(x2)) // 2, (int(y1) + int(y2)) // 2),
                color=bgr_to_hex(self._get_class_color(class_id)),
            ))
        return detection_objects

    # ------------------------------------------------------------------
    # Alternative pipeline (when main coordinates fail)
    # ------------------------------------------------------------------

    def _process_detections_alternative(self, detections, image_original, valid_detections,
                                        scale=1.0, border_top=0, actual_input_size=None):
        """
        Alternative method to process detections when main coordinates fail.
        Tries different interpretations of output data.
        """
        img = image_original.copy()
        frame_h, frame_w = img.shape[:2]
        valid_rows = detections[valid_detections]

        # Method 1: Using only valid x,y positions with fixed size boxes
        detections_found = self._draw_alt_normalized_centers(
            img, valid_rows, frame_w, frame_h, scale, border_top, actual_input_size
        )

        # If method 1 didn't work, try method 2
        if detections_found == 0:
            detections_found = self._draw_alt_scaled_centers(
                img, valid_rows, frame_w, frame_h, scale, border_top, actual_input_size
            )

        return self._draw_areas(img), detections_found, []

    def _draw_alt_normalized_centers(self, img, rows, frame_w, frame_h,
                                     scale, border_top, actual_input_size):
        """Draw confidence-sized boxes around rows whose x,y look normalized."""
        detections_found = 0
        for detection in rows:
            x_pos, y_pos = detection[0], detection[1]  # Positions that seem valid
            class_id, confidence = extract_class_info(detection, self.output_format)

            # If we have valid positions, draw a fixed-size box
            if not (0 <= x_pos <= 1 and 0 <= y_pos <= 1):
                continue

            # Convert to pixels
            center_x = int(x_pos * frame_w)
            if actual_input_size and actual_input_size > 0:
                center_y = int((y_pos * actual_input_size - border_top) * scale)
            else:
                center_y = int(y_pos * frame_h)
            center_y = max(0, min(center_y, frame_h - 1))

            # Define a fixed box size based on confidence (between 30 and 80 pixels)
            box_size = max(30, int(confidence * 80))
            x1, y1, x2, y2 = calculate_box_from_center(center_x, center_y, box_size, frame_w, frame_h)

            # Draw detection with center point
            self._draw_detection_box(img, x1, y1, x2, y2, class_id, confidence, draw_center=True)
            detections_found += 1
        return detections_found

    def _draw_alt_scaled_centers(self, img, rows, frame_w, frame_h,
                                 scale, border_top, actual_input_size):
        """Interpret x,y as model-input pixels, trying common YOLO input sizes."""
        detections_found = 0
        for detection in rows:
            # Try interpreting as absolute pixel coordinates (multiplied by a factor)
            x_pos, y_pos = detection[0], detection[1]
            class_id, confidence = extract_class_info(detection, self.output_format)

            # Try different model input sizes
            for try_size in [640, 416, 320]:  # Common YOLO input sizes
                scaled_x = int(x_pos * try_size)
                if actual_input_size and actual_input_size > 0:
                    scaled_y = int((y_pos * try_size - border_top) * scale)
                else:
                    scaled_y = int(y_pos * try_size)

                if 0 <= scaled_x < frame_w and 0 <= scaled_y < frame_h:
                    # Draw a small box
                    box_size = 40
                    x1, y1, x2, y2 = calculate_box_from_center(scaled_x, scaled_y, box_size, frame_w, frame_h)

                    color = (255, 0, 255)  # Magenta for method 2
                    cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                    cv2.circle(img, (scaled_x, scaled_y), 2, color, -1)

                    label = f"M2-{confidence:.2f}"
                    cv2.putText(img, label, (x1, y1 - 5),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

                    detections_found += 1
                    break  # Use the first scale that works
        return detections_found
