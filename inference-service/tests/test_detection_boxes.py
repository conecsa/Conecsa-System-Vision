"""Unit tests for the pure YOLO box-decoding helpers."""
import numpy as np
import pytest

from api.views import detection_boxes as db


class TestSigmoid:
    def test_zero_maps_to_half(self):
        assert db.sigmoid(np.array([0.0]))[0] == pytest.approx(0.5)

    def test_monotonic_and_bounded(self):
        xs = np.array([-10.0, -1.0, 0.0, 1.0, 10.0])
        ys = db.sigmoid(xs)
        assert np.all((ys > 0.0) & (ys < 1.0))
        assert np.all(np.diff(ys) > 0.0)

    def test_symmetry(self):
        assert db.sigmoid(np.array([2.0]))[0] == pytest.approx(
            1.0 - db.sigmoid(np.array([-2.0]))[0]
        )


class TestExtractClassInfo:
    def test_single_class_uses_index_four(self):
        det = np.array([0.1, 0.2, 0.3, 0.4, 0.9])
        class_id, conf = db.extract_class_info(det, output_format="single_class")
        assert class_id == 0
        assert conf == pytest.approx(0.9)

    def test_multiclass_picks_argmax(self):
        det = np.array([0.1, 0.2, 0.3, 0.4, 0.1, 0.7, 0.2])
        class_id, conf = db.extract_class_info(det)
        assert class_id == 1
        assert conf == pytest.approx(0.7)

    def test_multiclass_default_is_multiclass(self):
        det = np.array([0.0, 0.0, 0.0, 0.0, 0.8, 0.2])
        assert db.extract_class_info(det) == db.extract_class_info(
            det, output_format="multiclass"
        )

    def test_multiclass_without_scores_returns_zero(self):
        det = np.array([0.1, 0.2, 0.3, 0.4])
        class_id, conf = db.extract_class_info(det)
        assert class_id == 0
        assert conf == 0.0


class TestCalculateBoxFromCenter:
    def test_centered_box(self):
        assert db.calculate_box_from_center(50, 50, 20, 100, 100) == (40, 40, 60, 60)

    def test_clamps_to_image_bounds(self):
        # Box hanging off the top-left corner clamps at 0.
        assert db.calculate_box_from_center(5, 5, 20, 100, 100) == (0, 0, 15, 15)

    def test_clamps_to_far_edges(self):
        assert db.calculate_box_from_center(98, 98, 20, 100, 100) == (88, 88, 100, 100)


class TestCornersFromNormalized:
    def test_no_letterbox_scales_by_frame(self):
        # actual_input_size falsy -> plain frame scaling on both axes.
        assert db.corners_from_normalized(
            0.25, 0.25, 0.75, 0.75, 200, 100, 1.0, 0, 0
        ) == (50, 25, 150, 75)

    def test_collapsed_box_returns_none(self):
        assert (
            db.corners_from_normalized(0.5, 0.5, 0.5, 0.9, 100, 100, 1.0, 0, 0)
            is None
        )

    def test_out_of_range_is_clamped(self):
        # x beyond [0,1] clamps; y uses frame scaling (no letterbox).
        assert db.corners_from_normalized(
            -1.0, 0.0, 2.0, 1.0, 100, 100, 1.0, 0, 0
        ) == (0, 0, 100, 100)

    def test_letterbox_y_formula(self):
        # y_pixel = (y_norm * input - border_top) * scale
        res = db.corners_from_normalized(
            0.0, 0.5, 1.0, 1.0, 640, 480, 2.0, 80, 640
        )
        assert res is not None
        _, y1, _, y2 = res
        assert y1 == int((0.5 * 640 - 80) * 2.0)
        assert y2 == int((1.0 * 640 - 80) * 2.0)


class TestCornersFromPixel:
    def test_plain_scaling_without_letterbox(self):
        assert db.corners_from_pixel(
            10, 10, 50, 50, 2.0, 3.0, 1.0, 0, 0
        ) == (20, 30, 100, 150)

    def test_letterbox_y_removes_border(self):
        x1, y1, x2, y2 = db.corners_from_pixel(
            10, 100, 50, 200, 2.0, 3.0, 1.5, 40, 640
        )
        assert (x1, x2) == (20, 100)
        assert y1 == int((100 - 40) * 1.5)
        assert y2 == int((200 - 40) * 1.5)


class TestApplyNms:
    # apply_nms passes score_threshold=0.0 to cv2.dnn.NMSBoxes, so it performs
    # IoU suppression only -- confidence filtering is already done upstream by
    # YOLODetector. Every box, including the lowest-confidence one, is kept
    # unless a higher-confidence box suppresses it by IoU.

    def test_empty_input_returns_empty(self):
        assert db.apply_nms([], [], []) == ([], [], [])

    def test_single_box_survives(self):
        # A lone detection is never dropped (nothing to suppress it).
        kept_boxes, kept_confs, kept_ids = db.apply_nms([[0, 0, 10, 10]], [0.9], [3])
        assert kept_boxes == [[0, 0, 10, 10]]
        assert kept_confs == [pytest.approx(0.9)]
        assert kept_ids == [3]

    def test_lowest_confidence_disjoint_box_survives(self):
        boxes = [[0, 0, 10, 10], [100, 100, 110, 110]]
        kept_boxes, kept_confs, kept_ids = db.apply_nms(boxes, [0.9, 0.8], [0, 1])
        assert kept_boxes == [[0, 0, 10, 10], [100, 100, 110, 110]]
        assert kept_confs == [pytest.approx(0.9), pytest.approx(0.8)]
        assert kept_ids == [0, 1]

    def test_boxes_above_the_minimum_survive(self):
        boxes = [
            [0, 0, 10, 10],
            [100, 100, 110, 110],
            [200, 200, 210, 210],
        ]
        kept_boxes, _, kept_ids = db.apply_nms(boxes, [0.9, 0.85, 0.8], [0, 1, 2])
        # All three disjoint boxes survive; nothing overlaps to be suppressed.
        assert kept_boxes == boxes
        assert kept_ids == [0, 1, 2]

    def test_iou_suppresses_overlapping_higher_boxes(self):
        # A overlaps B (IoU suppresses the lower-confidence B); C is disjoint and
        # survives -> A and C remain.
        boxes = [[0, 0, 10, 10], [1, 1, 11, 11], [200, 200, 210, 210]]
        kept_boxes, _, kept_ids = db.apply_nms(
            boxes, [0.9, 0.85, 0.8], [0, 1, 2], overlay_threshold=0.3
        )
        assert kept_boxes == [[0, 0, 10, 10], [200, 200, 210, 210]]
        assert kept_ids == [0, 2]
