"""Shared plain-Python helpers for every FROM-base service.

Unlike ``conecsa_shm`` (which pulls numpy/cv2 at import), this package has no
third-party dependencies, so lightweight consumers — notably the api-gateway's
audit trail — can import it without growing their footprint.

Modules:

- ``atomic``: power-cut-safe file persistence (write-fsync-rename) and JSON
  loading that reports corruption instead of silently defaulting.
- ``bounded_sqlite``: the bounded SQLite ring queue shared by the detection
  buffer and the audit trail.
- ``tiling``: SAHI-style tile grid + cross-tile merge for small-object
  detection. It needs numpy, so it is deliberately NOT re-exported here —
  import ``conecsa_common.tiling`` explicitly to keep the package root
  dependency-free.
"""

from .atomic import atomic_write_bytes, atomic_write_json, read_json
from .bounded_sqlite import BoundedSqliteQueue

__all__ = ["BoundedSqliteQueue", "atomic_write_bytes", "atomic_write_json",
           "read_json"]
