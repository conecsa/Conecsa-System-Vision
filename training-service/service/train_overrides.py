"""Parsing of extra ultralytics training hyperparameters.

``TRAIN_OVERRIDES`` (see :mod:`service.config`) carries space-separated
``key=value`` pairs that are forwarded verbatim to ``model.train(**overrides)``
in :mod:`service._yolo_trainer`.

The keys are allowlisted: only hyperparameters that change *how* the model
learns are accepted (schedule, optimizer, augmentation, layer freezing).
Everything the service owns — dataset path, run location, device, imgsz,
epochs, batch, workers, AMP — is rejected so an env typo can never redirect a
run or silently change the export geometry.
"""
from typing import Dict, Union

OverrideValue = Union[bool, int, float, str]

# ultralytics ``model.train`` kwargs an operator may tune. Grouped for
# readability; the parser only needs the flat set.
ALLOWED_KEYS = frozenset(
    {
        # fine-tuning / schedule
        "freeze", "lr0", "lrf", "momentum", "weight_decay", "warmup_epochs",
        "warmup_momentum", "warmup_bias_lr", "cos_lr", "optimizer", "close_mosaic",
        "nbs", "dropout", "label_smoothing",
        # loss gains
        "box", "cls", "dfl",
        # augmentation
        "mosaic", "mixup", "cutmix", "copy_paste", "copy_paste_mode", "scale",
        "degrees", "translate", "shear", "perspective", "flipud", "fliplr",
        "hsv_h", "hsv_s", "hsv_v", "erasing", "auto_augment",
        # geometry of the training batches (not of the exported model)
        "multi_scale", "rect",
        # reproducibility
        "seed", "deterministic",
    }
)

# Owned by the service; never accepted from the environment.
RESERVED_KEYS = frozenset(
    {
        "data", "project", "name", "device", "workers", "imgsz", "epochs", "batch",
        "patience", "amp", "cache", "plots", "exist_ok", "verbose", "resume",
        "model", "pretrained", "save", "save_dir", "task", "mode",
    }
)

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}


class OverrideError(ValueError):
    """Raised for a malformed or disallowed override."""


def _coerce(raw: str) -> OverrideValue:
    """Best-effort typing: bool, then int, then float, else string.

    ``"1"``/``"0"`` stay ints (ultralytics accepts ints where it documents
    bools), so only the textual spellings map to booleans.
    """
    lowered = raw.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def parse_overrides(spec: str) -> Dict[str, OverrideValue]:
    """Parse ``"key=value key2=value2"`` into typed ``model.train`` kwargs.

    Raises :class:`OverrideError` on a token without ``=``, an empty key or
    value, a reserved key, or a key outside :data:`ALLOWED_KEYS`. Duplicate
    keys keep the last value (like a shell environment would).
    """
    result: Dict[str, OverrideValue] = {}
    for token in spec.split():
        if "=" not in token:
            raise OverrideError(f"override {token!r} is not key=value")
        key, value = token.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            raise OverrideError(f"override {token!r} has an empty key or value")
        if key in RESERVED_KEYS:
            raise OverrideError(f"override {key!r} is owned by the training service")
        if key not in ALLOWED_KEYS:
            raise OverrideError(f"override {key!r} is not an allowed hyperparameter")
        result[key] = _coerce(value)
    return result


def format_overrides(overrides: Dict[str, OverrideValue]) -> str:
    """Inverse of :func:`parse_overrides` (stable key order) for logs and argv."""
    return " ".join(f"{k}={overrides[k]}" for k in sorted(overrides))
