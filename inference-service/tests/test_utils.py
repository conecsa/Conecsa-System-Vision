"""Unit tests for label/color utilities."""
from api import utils


class _FakeConfig:
    def __init__(self, classes_file_path, default_labels):
        self.CLASSES_FILE_PATH = classes_file_path
        self.DEFAULT_LABELS = default_labels


class TestLoadClassLabels:
    def test_reads_non_empty_lines(self, tmp_path):
        f = tmp_path / "weights.txt"
        f.write_text("cat\n\ndog\n  bird  \n")
        cfg = _FakeConfig(str(f), ["FALLBACK"])
        assert utils.load_class_labels(cfg) == ["cat", "dog", "bird"]

    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = _FakeConfig(str(tmp_path / "nope.txt"), ["CLASS1", "CLASS2"])
        assert utils.load_class_labels(cfg) == ["CLASS1", "CLASS2"]


class TestGenerateColors:
    def test_returns_requested_count(self):
        assert len(utils.generate_colors(5)) == 5

    def test_first_colors_are_base_palette(self):
        colors = utils.generate_colors(3)
        assert colors[0] == (0, 165, 255)
        assert colors[1] == (0, 0, 255)

    def test_beyond_base_palette_generates_extra(self):
        colors = utils.generate_colors(15)
        assert len(colors) == 15
        # Every entry is a 3-tuple of 0..255 ints.
        for bgr in colors:
            assert len(bgr) == 3
            assert all(0 <= c <= 255 for c in bgr)

    def test_zero_classes(self):
        assert utils.generate_colors(0) == []


class TestHexToBgr:
    def test_six_digit(self):
        assert utils.hex_to_bgr("#ff8800") == (0x00, 0x88, 0xFF)

    def test_three_digit_shorthand(self):
        # #f80 -> r=ff, g=88, b=00 -> bgr (00, 88, ff)
        assert utils.hex_to_bgr("#f80") == (0x00, 0x88, 0xFF)

    def test_black_and_white(self):
        assert utils.hex_to_bgr("#000000") == (0, 0, 0)
        assert utils.hex_to_bgr("#ffffff") == (255, 255, 255)


class TestBgrToHex:
    def test_round_trips_with_hex_to_bgr(self):
        for color_hex in ("#ff8800", "#000000", "#ffffff", "#16a3b6"):
            assert utils.bgr_to_hex(utils.hex_to_bgr(color_hex)) == color_hex

    def test_channels_are_not_swapped(self):
        # BGR (0, 0, 255) is red.
        assert utils.bgr_to_hex((0, 0, 255)) == "#ff0000"
        # BGR (255, 0, 0) is blue.
        assert utils.bgr_to_hex((255, 0, 0)) == "#0000ff"

    def test_generated_palette_is_hex_encodable(self):
        # The first base color is orange (BGR 0,165,255).
        assert utils.bgr_to_hex(utils.generate_colors(3)[0]) == "#ffa500"


class TestParseLabelAndColor:
    def test_label_with_hex(self):
        name, bgr = utils.parse_label_and_color("person #ff0000")
        assert name == "person"
        assert bgr == (0, 0, 255)

    def test_multiword_label_with_hex(self):
        name, bgr = utils.parse_label_and_color("delivery van #00ff00")
        assert name == "delivery van"
        assert bgr == (0, 255, 0)

    def test_label_without_hex(self):
        assert utils.parse_label_and_color("person") == ("person", None)

    def test_trailing_token_not_a_hex(self):
        assert utils.parse_label_and_color("model v2") == ("model v2", None)

    def test_empty_input(self):
        assert utils.parse_label_and_color("") == ("", None)
        assert utils.parse_label_and_color(None) == ("", None)

    def test_hex_regex_rejects_bad_length(self):
        assert utils.HEX_COLOR_RE.match("#fffff") is None


class TestResolveClassColors:
    def test_user_hex_wins_over_the_palette(self):
        names, colors = utils.resolve_class_colors(["person #ff0000", "cat"])
        assert names == ["person", "cat"]
        assert utils.bgr_to_hex(colors[0]) == "#ff0000"

    def test_uncolored_classes_fall_back_to_the_palette_by_index(self):
        names, colors = utils.resolve_class_colors(["person", "cat"])
        assert names == ["person", "cat"]
        assert colors == utils.generate_colors(2)

    def test_a_neighbours_custom_color_does_not_shift_the_palette(self):
        # The fallback is keyed by class index, not by "how many uncolored".
        _, colors = utils.resolve_class_colors(["person #123456", "cat"])
        assert colors[1] == utils.generate_colors(2)[1]

    def test_blank_entry_becomes_object(self):
        names, colors = utils.resolve_class_colors(["", "cat"])
        assert names == ["Object", "cat"]
        assert len(colors) == 2

    def test_trailing_token_that_is_not_a_hex_stays_in_the_name(self):
        names, _ = utils.resolve_class_colors(["item #3"])
        assert names == ["item #3"]

    def test_empty_class_list(self):
        assert utils.resolve_class_colors([]) == ([], [])
        assert utils.HEX_COLOR_RE.match("#ff") is None
        assert utils.HEX_COLOR_RE.match("#abcd") is None
