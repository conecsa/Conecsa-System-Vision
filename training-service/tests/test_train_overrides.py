"""Unit tests for TRAIN_OVERRIDES parsing (allowlist, typing, reserved keys)."""
import pytest
from service.train_overrides import (
    ALLOWED_KEYS,
    RESERVED_KEYS,
    OverrideError,
    format_overrides,
    parse_overrides,
)


class TestParse:
    def test_empty_spec_gives_no_overrides(self):
        assert parse_overrides("") == {}
        assert parse_overrides("   ") == {}

    def test_types_are_coerced(self):
        parsed = parse_overrides("freeze=10 lr0=0.002 cos_lr=True optimizer=AdamW")
        assert parsed == {"freeze": 10, "lr0": 0.002, "cos_lr": True, "optimizer": "AdamW"}
        assert isinstance(parsed["freeze"], int)
        assert isinstance(parsed["lr0"], float)

    def test_numeric_bool_spellings_stay_numeric(self):
        # ultralytics takes ints where it documents bools (mosaic=1.0, rect=0);
        # only textual spellings become Python bools.
        parsed = parse_overrides("rect=0 mosaic=1.0 multi_scale=false")
        assert parsed == {"rect": 0, "mosaic": 1.0, "multi_scale": False}

    def test_last_duplicate_wins(self):
        assert parse_overrides("freeze=5 freeze=12") == {"freeze": 12}

    @pytest.mark.parametrize("spec", ["freeze", "=5", "freeze=", "lr0 0.01"])
    def test_malformed_token_rejected(self, spec):
        with pytest.raises(OverrideError):
            parse_overrides(spec)

    @pytest.mark.parametrize("key", sorted(RESERVED_KEYS))
    def test_reserved_keys_rejected(self, key):
        with pytest.raises(OverrideError, match="owned by the training service"):
            parse_overrides(f"{key}=1")

    def test_unknown_key_rejected(self):
        with pytest.raises(OverrideError, match="not an allowed"):
            parse_overrides("dropout_rate=0.1")

    def test_allowlist_and_reserved_are_disjoint(self):
        assert not (ALLOWED_KEYS & RESERVED_KEYS)


class TestFormat:
    def test_round_trip(self):
        spec = "close_mosaic=5 freeze=10 lr0=0.002"
        assert format_overrides(parse_overrides(spec)) == spec
