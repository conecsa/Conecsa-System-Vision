"""Tile crops for the training split (``service.tile_split``)."""
import os

import pytest
from service.tile_split import (
    TileSplitError,
    TileSplitStats,
    materialize_tiles,
    resolve_tile,
)

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


def _image(tmp_path, name, width=1280, height=720):
    path = tmp_path / f"{name}.jpg"
    cv2.imwrite(str(path), np.full((height, width, 3), 90, dtype=np.uint8))
    return str(path)


def _row(x1, y1, x2, y2, width=1280, height=720, class_id=0):
    return (class_id, (x1 + x2) / 2 / width, (y1 + y2) / 2 / height,
            (x2 - x1) / width, (y2 - y1) / height)


def _read(label):
    with open(label) as f:
        return [[float(v) for v in line.split()] for line in f.read().splitlines()]


def _run(tmp_path, image, rows, **kw):
    kw.setdefault("tile", "auto")
    return materialize_tiles(image, rows, str(tmp_path / "images"), str(tmp_path / "labels"),
                             os.path.splitext(os.path.basename(image))[0], **kw)


class TestResolveTile:
    def test_auto_is_the_short_side(self):
        assert resolve_tile("auto", 1280, 720) == 720
        assert resolve_tile("auto", 1920, 1080) == 1080
        assert resolve_tile("auto", 720, 1280) == 720

    def test_off_and_pixels(self):
        assert resolve_tile(None, 1280, 720) is None
        assert resolve_tile(640, 1280, 720) == 640

    def test_rejects_garbage(self):
        with pytest.raises(ValueError):
            resolve_tile("720", 1280, 720)  # pyright: ignore[reportArgumentType]
        with pytest.raises(ValueError):
            resolve_tile(0, 1280, 720)


class TestMaterializeTiles:
    def test_auto_on_1280x720_gives_the_k2_layout_and_rewrites_labels(self, tmp_path):
        image = _image(tmp_path, "a")
        rows = [_row(100, 300, 200, 400), _row(600, 300, 680, 400), _row(700, 300, 800, 400)]
        written, stats = _run(tmp_path, image, rows)
        assert [os.path.basename(p[0]) for p in written] == ["a_t0.jpg", "a_t1.jpg"]
        assert cv2.imread(written[0][0]).shape == (720, 720, 3)
        # tile 0 (x 0..720): two whole boxes; the 700..800 box is a 20 % fragment → dropped
        t0 = _read(written[0][1])
        assert len(t0) == 2
        assert t0[0][1:] == pytest.approx([150 / 720, 350 / 720, 100 / 720, 100 / 720], abs=1e-5)
        # tile 1 (x 560..1280): the overlap box shifted by 560, plus the whole 700..800 box
        t1 = _read(written[1][1])
        assert len(t1) == 2
        assert t1[0][1:] == pytest.approx([(640 - 560) / 720, 350 / 720, 80 / 720, 100 / 720],
                                          abs=1e-5)
        assert t1[1][1:] == pytest.approx([(750 - 560) / 720, 350 / 720, 100 / 720, 100 / 720],
                                          abs=1e-5)
        assert stats == TileSplitStats(tiles=2, boxes=4, fragments=1)

    def test_auto_follows_the_camera_resolution(self, tmp_path):
        image = _image(tmp_path, "hd", 1920, 1080)
        written, stats = _run(tmp_path, image, [_row(100, 100, 200, 200, 1920, 1080)])
        assert len(written) == 2 and stats.tiles == 2
        assert cv2.imread(written[1][0]).shape == (1080, 1080, 3)
        assert _read(written[0][1])[0][1:] == pytest.approx(
            [150 / 1080, 150 / 1080, 100 / 1080, 100 / 1080], abs=1e-5)

    def test_explicit_pixel_tile(self, tmp_path):
        image = _image(tmp_path, "px")
        written, stats = _run(tmp_path, image, [], tile=640)
        # 1280x720 with 640 tiles at 0.2 overlap: three columns x two rows.
        assert stats.tiles == len(written) == 6
        assert stats.background == 6

    def test_fragment_only_tile_skipped_and_background_kept(self, tmp_path):
        # only box: mostly in tile 1, a sliver in tile 0 → tile 0 must not become a negative
        written, stats = _run(tmp_path, _image(tmp_path, "b"), [_row(700, 300, 800, 400)])
        assert [os.path.basename(p[0]) for p in written] == ["b_t1.jpg"]
        assert stats.skipped == 1 and stats.fragments == 1 and stats.boxes == 1
        # no box at all in tile 0, box deep in tile 1 → tile 0 is a legitimate negative
        written, stats = _run(tmp_path, _image(tmp_path, "c"), [_row(1000, 300, 1100, 400)])
        assert [os.path.basename(p[0]) for p in written] == ["c_t0.jpg", "c_t1.jpg"]
        assert stats.background == 1 and stats.boxes == 1
        with open(written[0][1]) as f:
            assert f.read() == ""

    @pytest.mark.parametrize("size,tile", [((640, 640), "auto"), ((1280, 720), 1280),
                                           ((1280, 720), None)])
    def test_single_covering_tile_keeps_the_image_whole(self, tmp_path, size, tile):
        image = _image(tmp_path, "w", *size)
        written, stats = _run(tmp_path, image, [_row(10, 10, 20, 20, *size)], tile=tile)
        assert written == [] and stats == TileSplitStats(whole=1)
        assert not (tmp_path / "images").exists()

    def test_undecodable_image_raises(self, tmp_path):
        bad = tmp_path / "bad.jpg"
        bad.write_bytes(b"img")
        with pytest.raises(TileSplitError):
            _run(tmp_path, str(bad), [])

    def test_stats_accumulate(self):
        total = TileSplitStats(tiles=1, whole=1)
        total.add(TileSplitStats(tiles=2, boxes=3, skipped=1))
        assert total == TileSplitStats(tiles=3, boxes=3, skipped=1, whole=1)
