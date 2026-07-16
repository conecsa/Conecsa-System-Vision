"""Unit tests for YOLODetector confidence filtering and output decoding."""
import numpy as np

from api.config import Config
from api.yolo_detector import YOLODetector


def make_detector(threshold):
    cfg = Config()
    cfg.CONFIDENCE_THRESHOLD = threshold
    return YOLODetector(["CLASS1"], cfg)


class TestConfidenceMask:
    def test_threshold_one_filters_everything(self):
        # Regression: the old relaxed-threshold fallback re-admitted every
        # detection above 0.4 whenever nothing passed the configured
        # threshold, so threshold=1.0 still recorded ~0.5 detections.
        detector = make_detector(1.0)
        mask = detector._confidence_mask(np.array([0.5, 0.95]))
        assert not mask.any()

    def test_only_detections_above_threshold_pass(self):
        detector = make_detector(0.75)
        mask = detector._confidence_mask(np.array([0.5, 0.8]))
        assert mask.tolist() == [False, True]

    def test_no_relaxed_readmission_when_all_below_threshold(self):
        detector = make_detector(0.9)
        mask = detector._confidence_mask(np.array([0.5, 0.6]))
        assert not mask.any()

    def test_threshold_updates_apply_to_next_frame(self):
        detector = make_detector(0.9)
        confidences = np.array([0.5, 0.6])
        assert not detector._confidence_mask(confidences).any()
        detector.config.CONFIDENCE_THRESHOLD = 0.4
        assert detector._confidence_mask(confidences).all()


class TestNormalizeOutputFormats:
    def test_e2e_shape_detected_and_not_transposed(self):
        detector = make_detector(0.5)
        output = np.zeros((1, 300, 6), dtype=np.float32)
        output[0, 7] = [1.0, 2.0, 3.0, 4.0, 0.5, 5.0]  # sentinel row
        rows = detector._normalize_output(output)
        assert rows is not None
        assert detector.output_format == "end_to_end"
        assert rows.shape == (300, 6)
        assert rows[7].tolist() == [1.0, 2.0, 3.0, 4.0, 0.5, 5.0]

    def test_two_class_features_first_is_not_e2e(self):
        # The critical disambiguation: a 2-class one-to-many model emits
        # [1, 6, 8400] (features-first) — must stay on the legacy path.
        detector = make_detector(0.5)
        rows = detector._normalize_output(np.zeros((1, 6, 8400), dtype=np.float32))
        assert rows is not None
        assert detector.output_format == "multiclass"
        assert detector.num_classes_detected == 2
        assert rows.shape == (8400, 6)

    def test_two_class_detections_first_is_not_e2e(self):
        # Detections-first legacy export: anchor count far exceeds 300.
        detector = make_detector(0.5)
        rows = detector._normalize_output(np.zeros((1, 8400, 6), dtype=np.float32))
        assert rows is not None
        assert detector.output_format == "multiclass"
        assert detector.num_classes_detected == 2
        assert rows.shape == (8400, 6)

    def test_multiclass_80_classes(self):
        detector = make_detector(0.5)
        rows = detector._normalize_output(np.zeros((1, 84, 8400), dtype=np.float32))
        assert rows is not None
        assert detector.output_format == "multiclass"
        assert detector.num_classes_detected == 80
        assert rows.shape == (8400, 84)

    def test_single_class(self):
        detector = make_detector(0.5)
        rows = detector._normalize_output(np.zeros((1, 5, 8400), dtype=np.float32))
        assert rows is not None
        assert detector.output_format == "single_class"
        assert rows.shape == (8400, 5)

    def test_adopted_format_is_sticky(self):
        detector = make_detector(0.5)
        detector._normalize_output(np.zeros((1, 300, 6), dtype=np.float32))
        assert detector.output_format == "end_to_end"
        detector._normalize_output(np.zeros((1, 84, 8400), dtype=np.float32))
        assert detector.output_format == "end_to_end"


class TestEndToEndProcess:
    """process_detections with e2e [1, N, 6] rows: [x1, y1, x2, y2, conf, cls].

    Frame is 640x480 with a 640x640 model input: preprocess resizes the width
    to 640 (height 480) and letterboxes 80px top/bottom, so scale=1.0 and
    border_top=80.
    """

    @classmethod
    def process(cls, detector, output):
        return detector.process_detections(
            output, cls.frame(), scale=1.0, border_top=80, actual_input_size=640
        )

    @staticmethod
    def make_output(rows):
        output = np.zeros((1, 300, 6), dtype=np.float32)
        for i, row in enumerate(rows):
            output[0, i] = row
        return output

    @staticmethod
    def frame():
        return np.zeros((480, 640, 3), dtype=np.uint8)

    def test_pixel_corners_are_deletterboxed(self):
        detector = make_detector(0.5)
        output = self.make_output([[64, 160, 320, 400, 0.9, 0]])
        _, count, detections = self.process(detector, output)
        assert count == 1
        det = detections[0]
        # X passes through (frame_w == model input width); Y drops border_top.
        assert det.bbox == (64, 80, 320, 320)
        assert det.class_id == 0
        assert det.class_name == "CLASS1"
        assert abs(det.confidence - 0.9) < 1e-6

    def test_below_threshold_rows_dropped(self):
        detector = make_detector(0.5)
        output = self.make_output([
            [64, 160, 320, 400, 0.9, 0],
            [10, 100, 200, 300, 0.2, 0],
        ])
        _, count, detections = self.process(detector, output)
        assert count == 1
        assert detections[0].bbox == (64, 80, 320, 320)

    def test_overlapping_duplicate_suppressed_by_nms(self):
        # The one-to-one head rarely emits near-duplicates, but the
        # user-adjustable overlay threshold must keep suppressing them.
        detector = make_detector(0.5)
        detector.config.OVERLAY_THRESHOLD = 0.45
        output = self.make_output([
            [64, 160, 320, 400, 0.9, 0],
            [66, 162, 318, 398, 0.8, 0],
        ])
        _, count, _ = self.process(detector, output)
        assert count == 1

    def test_class_id_beyond_labels_falls_back(self):
        detector = make_detector(0.5)
        output = self.make_output([[400, 300, 500, 460, 0.8, 7]])
        _, count, detections = self.process(detector, output)
        assert count == 1
        det = detections[0]
        assert det.class_id == 7
        assert det.class_name == "Class-7"
        assert det.bbox == (400, 220, 500, 380)

    def test_no_detections_above_threshold(self):
        detector = make_detector(0.5)
        img, count, detections = self.process(detector, self.make_output([]))
        assert count == 0
        assert detections == []
        assert img.shape == (480, 640, 3)
