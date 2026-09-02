"""Tests for conecsa_common.tiling — SAHI-style tile geometry and NMS merge.

Pure host-side: numpy only, no GPU, no cv2. The grid tests brute-force a
coverage mask so that the guarantee "every pixel is seen by at least one
tile, and no tile leaves the frame" holds for the frame sizes the device
actually produces.
"""
import numpy as np
import pytest
from conecsa_common.tiling import (
    Tile,
    auto_tile,
    clip_box,
    iou_matrix,
    merge_tiles,
    shift_boxes,
    tile_crop,
    tile_grid,
    tile_label_rows,
)

FRAME_SIZES = [(1280, 720), (640, 360), (1920, 1080), (500, 500)]
TILE = 640


def _coverage(tiles: list[Tile], width: int, height: int) -> np.ndarray:
    mask = np.zeros((height, width), dtype=np.int32)
    for t in tiles:
        mask[t.y0:t.y1, t.x0:t.x1] += 1
    return mask


class TestTile:
    def test_width_and_height(self):
        t = Tile(10, 20, 50, 80)
        assert (t.width, t.height) == (40, 60)

    def test_rejects_degenerate_boxes(self):
        with pytest.raises(ValueError):
            Tile(0, 0, 0, 10)
        with pytest.raises(ValueError):
            Tile(5, 0, 4, 10)
        with pytest.raises(ValueError):
            Tile(-1, 0, 10, 10)

    def test_is_frozen(self):
        t = Tile(0, 0, 1, 1)
        with pytest.raises(AttributeError):
            t.x0 = 3  # type: ignore[misc]


class TestTileGrid:
    @pytest.mark.parametrize(("width", "height"), FRAME_SIZES)
    def test_every_pixel_is_covered_and_tiles_stay_inside(self, width, height):
        tiles = tile_grid(width, height, TILE, overlap=0.2)
        assert tiles
        for t in tiles:
            assert 0 <= t.x0 < t.x1 <= width
            assert 0 <= t.y0 < t.y1 <= height
        assert (_coverage(tiles, width, height) >= 1).all()

    @pytest.mark.parametrize(("width", "height"), FRAME_SIZES)
    def test_tile_sides_equal_tile_unless_frame_is_smaller(self, width, height):
        for t in tile_grid(width, height, TILE):
            assert t.width == min(TILE, width)
            assert t.height == min(TILE, height)

    def test_small_frame_yields_a_single_tile(self):
        assert tile_grid(500, 500, TILE) == [Tile(0, 0, 500, 500)]
        # Smaller in one axis only: one row, several columns.
        tiles = tile_grid(1280, 360, TILE, overlap=0.0)
        assert tiles == [Tile(0, 0, 640, 360), Tile(640, 0, 1280, 360)]

    @pytest.mark.parametrize("overlap", [0.1, 0.2, 0.25, 0.5])
    def test_adjacent_tiles_overlap_by_at_least_the_requested_fraction(self, overlap):
        width, height = 1920, 1080
        tiles = tile_grid(width, height, TILE, overlap=overlap)
        xs = sorted({t.x0 for t in tiles})
        ys = sorted({t.y0 for t in tiles})
        wanted = overlap * TILE - 1  # allow rounding
        for a, b in zip(xs, xs[1:], strict=False):
            assert (a + TILE) - b >= wanted
        for a, b in zip(ys, ys[1:], strict=False):
            assert (a + TILE) - b >= wanted

    def test_zero_overlap_tiles_do_not_overlap_when_the_frame_divides_evenly(self):
        tiles = tile_grid(1280, 1280, TILE, overlap=0.0)
        assert len(tiles) == 4
        assert (_coverage(tiles, 1280, 1280) == 1).all()

    def test_zero_overlap_only_overlaps_where_the_edge_tile_is_shifted_back(self):
        # 1920 / 640 = 3 columns exactly; 1080 needs a second row shifted up
        # to 440 so it ends flush with the frame — that row overlaps the first.
        tiles = tile_grid(1920, 1080, TILE, overlap=0.0)
        assert sorted({t.x0 for t in tiles}) == [0, 640, 1280]
        assert sorted({t.y0 for t in tiles}) == [0, 440]
        assert len(tiles) == 6

    def test_include_full_appends_the_full_frame_tile_last(self):
        without = tile_grid(1280, 720, TILE)
        with_full = tile_grid(1280, 720, TILE, include_full=True)
        assert with_full[:-1] == without
        assert with_full[-1] == Tile(0, 0, 1280, 720)

    def test_order_is_row_major_and_deterministic(self):
        tiles = tile_grid(1280, 720, TILE, overlap=0.2)
        assert tiles == tile_grid(1280, 720, TILE, overlap=0.2)
        keys = [(t.y0, t.x0) for t in tiles]
        assert keys == sorted(keys)
        # 640 with 20 % overlap strides 512: x = 0, 512, then 640 flush with
        # the right edge; y = 0, then 80 flush with the bottom.
        assert [t.x0 for t in tiles] == [0, 512, 640, 0, 512, 640]
        assert [t.y0 for t in tiles] == [0, 0, 0, 80, 80, 80]

    @pytest.mark.parametrize(
        ("width", "height", "tile", "overlap"),
        [
            (0, 720, TILE, 0.2),
            (1280, 0, TILE, 0.2),
            (-1, 720, TILE, 0.2),
            (1280, 720, 0, 0.2),
            (1280, 720, -640, 0.2),
            (1280, 720, TILE, -0.1),
            (1280, 720, TILE, 1.0),
            (1280, 720, TILE, 1.5),
        ],
    )
    def test_rejects_bad_arguments(self, width, height, tile, overlap):
        with pytest.raises(ValueError):
            tile_grid(width, height, tile, overlap=overlap)


class TestTileCrop:
    def test_returns_a_view_of_the_requested_region(self):
        frame = np.arange(6 * 8 * 3, dtype=np.uint8).reshape(6, 8, 3)
        crop = tile_crop(frame, Tile(2, 1, 5, 4))
        assert crop.shape == (3, 3, 3)
        assert np.shares_memory(crop, frame)
        np.testing.assert_array_equal(crop, frame[1:4, 2:5])


class TestShiftBoxes:
    def test_adds_offsets_and_preserves_shape(self):
        boxes = np.array([[0.0, 0.0, 10.0, 10.0], [5.0, 6.0, 7.0, 8.0]])
        out = shift_boxes(boxes, 100, 200)
        assert out.shape == boxes.shape
        np.testing.assert_allclose(out, [[100, 200, 110, 210], [105, 206, 107, 208]])

    def test_returns_a_new_array(self):
        boxes = np.array([[0.0, 0.0, 10.0, 10.0]])
        out = shift_boxes(boxes, 1, 1)
        assert out is not boxes
        np.testing.assert_allclose(boxes, [[0, 0, 10, 10]])

    def test_empty_input(self):
        out = shift_boxes(np.empty((0, 4)), 10, 10)
        assert out.shape == (0, 4)

    def test_rejects_wrong_shape(self):
        with pytest.raises(ValueError):
            shift_boxes(np.zeros((3, 5)), 0, 0)


class TestIouMatrix:
    def test_known_values(self):
        a = np.array([[0.0, 0.0, 10.0, 10.0]])
        b = np.array(
            [
                [0.0, 0.0, 10.0, 10.0],  # identical
                [20.0, 20.0, 30.0, 30.0],  # disjoint
                [5.0, 0.0, 15.0, 10.0],  # half overlap: inter 50, union 150
                [0.0, 0.0, 5.0, 10.0],  # fully inside, half the area
            ]
        )
        ious = iou_matrix(a, b)
        assert ious.shape == (1, 4)
        np.testing.assert_allclose(ious[0], [1.0, 0.0, 50 / 150, 0.5])

    def test_shape_is_n_by_m(self):
        a = np.zeros((3, 4))
        b = np.zeros((5, 4))
        assert iou_matrix(a, b).shape == (3, 5)

    def test_zero_area_boxes_give_zero_not_nan(self):
        a = np.array([[1.0, 1.0, 1.0, 1.0]])
        ious = iou_matrix(a, a)
        assert ious.shape == (1, 1)
        assert ious[0, 0] == 0.0

    def test_empty_inputs(self):
        assert iou_matrix(np.empty((0, 4)), np.zeros((3, 4))).shape == (0, 3)
        assert iou_matrix(np.zeros((2, 4)), np.empty((0, 4))).shape == (2, 0)


class TestMergeTiles:
    def test_duplicates_across_tiles_collapse_to_the_higher_score(self):
        # One object seen by two overlapping tiles: near-identical boxes after
        # shifting back to frame space, slightly different confidences.
        boxes = np.array([[100.0, 100.0, 140.0, 140.0], [101.0, 99.0, 141.0, 139.0]])
        scores = np.array([0.6, 0.9])
        classes = np.array([3, 3])
        keep = merge_tiles(boxes, scores, classes, iou_threshold=0.5)
        assert keep.dtype == np.int64
        assert keep.tolist() == [1]

    def test_distinct_objects_survive(self):
        boxes = np.array([[0.0, 0.0, 10.0, 10.0], [50.0, 50.0, 60.0, 60.0]])
        keep = merge_tiles(boxes, np.array([0.5, 0.8]), np.array([0, 0]))
        assert keep.tolist() == [1, 0]  # sorted by descending score

    def test_class_aware_keeps_two_classes_at_the_same_location(self):
        boxes = np.array([[0.0, 0.0, 10.0, 10.0], [0.0, 0.0, 10.0, 10.0]])
        scores = np.array([0.9, 0.7])
        classes = np.array([1, 2])
        assert merge_tiles(boxes, scores, classes, class_aware=True).tolist() == [0, 1]

    def test_class_agnostic_suppresses_them(self):
        boxes = np.array([[0.0, 0.0, 10.0, 10.0], [0.0, 0.0, 10.0, 10.0]])
        scores = np.array([0.7, 0.9])
        classes = np.array([1, 2])
        assert merge_tiles(boxes, scores, classes, class_aware=False).tolist() == [1]

    def test_suppression_is_strictly_above_the_threshold(self):
        # IoU exactly 0.5 (the second box is the left half of the first) must
        # not suppress at threshold 0.5, so the boundary is stable.
        boxes = np.array([[0.0, 0.0, 10.0, 10.0], [0.0, 0.0, 5.0, 10.0]])
        keep = merge_tiles(boxes, np.array([0.9, 0.8]), np.array([0, 0]), iou_threshold=0.5)
        assert keep.tolist() == [0, 1]

    def test_is_idempotent_on_the_kept_set(self):
        rng = np.random.default_rng(7)
        n = 200
        xy = rng.uniform(0, 300, size=(n, 2))
        wh = rng.uniform(5, 60, size=(n, 2))
        boxes = np.concatenate([xy, xy + wh], axis=1)
        scores = rng.uniform(0.05, 1.0, size=n)
        classes = rng.integers(0, 3, size=n)

        keep = merge_tiles(boxes, scores, classes, iou_threshold=0.5)
        assert len(keep) < n  # random boxes do collide at this density
        assert (np.diff(scores[keep]) <= 0).all()
        again = merge_tiles(boxes[keep], scores[keep], classes[keep], iou_threshold=0.5)
        assert again.tolist() == list(range(len(keep)))

    def test_empty_input(self):
        keep = merge_tiles(np.empty((0, 4)), np.empty(0), np.empty(0, dtype=np.int64))
        assert keep.shape == (0,)
        assert keep.dtype == np.int64

    def test_rejects_mismatched_lengths_and_bad_threshold(self):
        boxes = np.zeros((2, 4))
        with pytest.raises(ValueError):
            merge_tiles(boxes, np.zeros(3), np.zeros(2))
        with pytest.raises(ValueError):
            merge_tiles(boxes, np.zeros(2), np.zeros(2), iou_threshold=1.5)

    def test_end_to_end_tile_shift_merge(self):
        # Simulate a detector that reports the same object from every tile
        # that contains it; after shifting and merging exactly one box per
        # object remains, in frame coordinates.
        width, height = 1280, 720
        objects = np.array([[600.0, 300.0, 660.0, 360.0], [20.0, 20.0, 40.0, 40.0]])
        all_boxes, all_scores, all_classes = [], [], []
        for t in tile_grid(width, height, TILE, overlap=0.2):
            local = objects - np.array([t.x0, t.y0, t.x0, t.y0])
            inside = (
                (local[:, 0] >= 0) & (local[:, 1] >= 0)
                & (local[:, 2] <= t.width) & (local[:, 3] <= t.height)
            )
            if not inside.any():
                continue
            all_boxes.append(shift_boxes(local[inside], t.x0, t.y0))
            all_scores.append(np.full(int(inside.sum()), 0.8))
            all_classes.append(np.zeros(int(inside.sum()), dtype=np.int64))
        boxes = np.concatenate(all_boxes)
        assert len(boxes) > len(objects)  # the first object sits in an overlap band
        keep = merge_tiles(boxes, np.concatenate(all_scores), np.concatenate(all_classes))
        kept = boxes[keep]
        assert len(kept) == len(objects)
        for obj in objects:
            assert any(np.allclose(k, obj) for k in kept)


class TestAutoTile:
    @pytest.mark.parametrize("width,height,columns", [
        (1280, 720, 2), (1920, 1080, 2), (3840, 2160, 2),   # 16:9 → K=2 at any pixel count
        (640, 480, 2), (1440, 1080, 2),                     # 4:3 → two heavily overlapping
        (1280, 640, 3), (2560, 1080, 3),                    # 2:1 and 21:9 → three
        (500, 500, 1),                                      # square → the whole frame
        (720, 1280, 2),                                     # portrait → two rows
    ])
    def test_tile_count_depends_only_on_the_aspect_ratio(self, width, height, columns):
        side = auto_tile(width, height)
        assert side == min(width, height)
        tiles = tile_grid(width, height, side, overlap=0.2)
        assert len(tiles) == columns
        assert all((t.width, t.height) == (side, side) for t in tiles)

    def test_auto_matches_a_pinned_720_tile_on_1280x720(self):
        assert tile_grid(1280, 720, auto_tile(1280, 720), 0.2) == tile_grid(1280, 720, 720, 0.2)

    @pytest.mark.parametrize("width,height", [(0, 720), (1280, 0), (-1, 5)])
    def test_rejects_bad_sizes(self, width, height):
        with pytest.raises(ValueError):
            auto_tile(width, height)


class TestClipBox:
    def test_inside_and_disjoint(self):
        tile = Tile(560, 0, 1280, 720)
        clipped, visible = clip_box([600, 100, 680, 200], tile)
        assert clipped == [40, 100, 120, 200] and visible == 1.0
        assert clip_box([100, 100, 200, 200], tile) == ([], 0.0)

    def test_partial_fraction(self):
        clipped, visible = clip_box([700, 100, 800, 200], Tile(0, 0, 720, 720))
        assert clipped == [700, 100, 720, 200] and visible == pytest.approx(0.2)

    def test_degenerate_box(self):
        assert clip_box([100, 100, 100, 200], Tile(0, 0, 720, 720)) == ([], 0.0)


class TestTileLabelRows:
    BOXES = [[100, 300, 200, 400], [600, 300, 680, 400], [700, 300, 800, 400]]

    def test_rows_are_clipped_shifted_and_normalised(self):
        rows, touched = tile_label_rows([0, 1, 0], self.BOXES, Tile(560, 0, 1280, 720))
        assert touched == 2  # the first box is entirely in the other column
        assert [r.split()[0] for r in rows] == ["1", "0"]
        cx, cy, w, h = (float(v) for v in rows[0].split()[1:])
        assert (cx, cy, w, h) == pytest.approx(
            ((640 - 560) / 720, 350 / 720, 80 / 720, 100 / 720), abs=1e-5)

    def test_fragment_below_min_visible_is_counted_but_not_kept(self):
        rows, touched = tile_label_rows([0, 0, 0], self.BOXES, Tile(0, 0, 720, 720))
        assert touched == 3 and len(rows) == 2  # the 700..800 box is a 20 % sliver

    def test_untouched_tile_is_a_clean_negative(self):
        assert tile_label_rows([0], [[1000, 300, 1100, 400]], Tile(0, 0, 720, 720)) == ([], 0)

    def test_rejects_bad_inputs(self):
        with pytest.raises(ValueError):
            tile_label_rows([0, 1], [[0, 0, 1, 1]], Tile(0, 0, 10, 10))
        with pytest.raises(ValueError):
            tile_label_rows([0], [[0, 0, 1, 1]], Tile(0, 0, 10, 10), min_visible=0.0)
