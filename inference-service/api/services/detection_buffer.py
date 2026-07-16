"""
Detection buffer service - store-and-forward for hub outages.

While the hub is polling (`/detections/snapshot` ~1x/s over the gateway), this
service only tracks the last-pull time and the current detection signature.
When no snapshot pull arrives within the offline threshold, on-change
detection results (same change semantics as the hub collector: class@area
counts + total + model) are persisted to a small SQLite ring buffer on disk,
so they survive a device reboot. The hub drains them on reconnect via
``ListBacklog`` and only after it confirms persistence (``AckBacklog``) are
the local rows deleted.

Buffering never starts before the first hub contact of the device's lifetime
(persisted ``hub_seen`` flag), so a standalone device never fills its eMMC.
The pipeline must never fail because of this buffer: every public entry point
swallows database errors (one reopen/recreate attempt, then the buffer
disables itself with a log).
"""
import base64
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Page size for ListBacklog when the request does not specify one, and the
# hard upper bound (each record may carry a base64 JPEG frame).
DEFAULT_PAGE_LIMIT = 25
MAX_PAGE_LIMIT = 100
# Byte-aware page trim: after including the first record, stop adding more once
# the raw stored bytes would exceed this. This is a best-effort cap to keep
# each page's JSON size (≈4/3 after base64 frames) below typical transport
# limits; remaining rows are picked up by the next page request.
PAGE_SOFT_BYTES = 3 * 1024 * 1024

# Oldest-first eviction batch when the ring caps are exceeded.
_EVICT_BATCH = 50
# Rate limit for the "records discarded" warning during a long outage.
_DISCARD_LOG_INTERVAL_S = 60.0

_HUB_SEEN_KEY = "hub_seen"


def signature(detections: list, total: int, model: str) -> str:
    """Change signature of a detection set.

    Mirrors the hub collector's dedup signature
    (hub-vision/src/detections/mod.rs::signature): ordered counts of
    ``class_name@area_label`` (``none`` when the detection has no area),
    joined with the total and model. Confidence/bbox/color deliberately do
    not participate, so jitter on a static scene does not look like change.
    """
    counts: dict = {}
    for d in detections:
        area = d.get("area")
        label = (area or {}).get("label") if isinstance(area, dict) else None
        key = f"{d.get('class_name', '')}@{label or 'none'}"
        counts[key] = counts.get(key, 0) + 1
    # Rust Debug formatting of a BTreeMap<String, u32>: {"a": 1, "b": 2}
    counts_repr = "{" + ", ".join(
        f'"{k}": {counts[k]}' for k in sorted(counts)
    ) + "}"
    return f"{counts_repr}|{total}|{model}"


def _encode_jpeg(image) -> Optional[bytes]:
    """JPEG-encode a BGR frame (quality 80, matching the snapshot encoder)."""
    # noinspection PyPackageRequirements
    import cv2  # Package is included on os build; lazy so tests can stub this.
    ok, buf = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return None
    return buf.tobytes()


class DetectionBufferService:
    """Persistent ring buffer of detection records for offline-hub periods."""

    def __init__(
        self,
        db_path: str,
        max_records: int,
        max_bytes: int,
        offline_threshold_s: float,
        clock=time.monotonic,
    ):
        self._db_path = db_path
        self._max_records = max_records
        self._max_bytes = max_bytes
        self._offline_threshold_s = offline_threshold_s
        self._clock = clock
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._disabled = False
        self._count = 0
        self._bytes = 0
        self._hub_seen = False
        self._last_sig: Optional[str] = None
        # No pull yet = offline: a device rebooting mid-outage must buffer the
        # scene it wakes up to. Booting next to a live hub is fine too — the
        # first snapshot poll (~1s) lands before the pipeline produces frames,
        # and the hub's drain dedup absorbs any overlap.
        self._last_pull: Optional[float] = None
        self._discarded_since_log = 0
        self._last_discard_log = 0.0
        with self._lock:
            try:
                self._open(recreate_on_error=True)
            except sqlite3.Error:
                logger.exception("detection buffer unavailable; disabling")
                self._disabled = True

    # ── hub-contact tracking (gRPC pool threads) ─────────────────────────────

    def note_snapshot_pull(self) -> None:
        """Record a hub snapshot pull (the hub-is-online heartbeat)."""
        with self._lock:
            self._last_pull = self._clock()
            if self._hub_seen or self._disabled:
                return
            try:
                self._db().execute(
                    "INSERT OR REPLACE INTO buffer_meta (key, value) VALUES (?, '1')",
                    (_HUB_SEEN_KEY,),
                )
                self._db().commit()
                self._hub_seen = True
                logger.info("detection buffer armed: first hub contact recorded")
            except sqlite3.Error:
                self._handle_db_error("note_snapshot_pull")

    def pending_count(self) -> int:
        """Rows currently buffered (reported as `pending_backlog` in snapshots)."""
        return 0 if self._disabled else self._count

    # ── producer (single pipeline-finish thread) ─────────────────────────────

    def observe(self, detections: list, total: int, model: str,
                raw_image, processed_image) -> None:
        """Consider one finished frame for buffering.

        Always tracks the change signature (so the first offline frame that
        equals the last state the hub saw is not re-recorded); writes a row
        only when the hub is offline, the set changed, is non-empty, and the
        hub has been seen at least once in this device's lifetime.
        """
        if self._disabled:
            return
        sig = signature(detections, total, model)
        with self._lock:
            changed = sig != self._last_sig
            self._last_sig = sig
            if not (self._hub_seen and changed and total > 0):
                return
            if not self._offline():
                return
        # Encode outside the lock: JPEG compression is the expensive step, and
        # holding the lock through it would stall the drain RPCs
        # (list_backlog/ack) behind frame processing.
        frame_is_raw = raw_image is not None
        image = raw_image if frame_is_raw else processed_image
        frame_bytes = _encode_jpeg(image) if image is not None else None
        payload = json.dumps(
            {"detections": detections, "total": total, "model": model}
        )
        size = len(payload) + len(frame_bytes or b"")
        with self._lock:
            # Re-check: a hub pull may have landed while encoding (the live
            # snapshot now covers this state), and a concurrent DB error may
            # have disabled the buffer.
            if self._disabled or not self._offline():
                return
            try:
                self._db().execute(
                    "INSERT INTO buffered_detections"
                    " (captured_at, payload, frame, frame_is_raw, size_bytes)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (time.time(), payload, frame_bytes, int(frame_is_raw), size),
                )
                self._db().commit()
                self._count += 1
                self._bytes += size
                self._evict_over_caps()
            except sqlite3.Error:
                self._handle_db_error("observe")

    # ── drain protocol (gRPC pool threads) ───────────────────────────────────

    def list_backlog(self, limit: int = 0) -> dict:
        """One page of buffered records, oldest first.

        ``device_now`` and each ``captured_at`` come from the same wall clock
        (`time.time()`), so the hub can convert them to its own timeline as
        relative offsets even when this device's absolute clock is wrong.
        """
        limit = max(1, min(int(limit) or DEFAULT_PAGE_LIMIT, MAX_PAGE_LIMIT))
        empty = {"records": [], "device_now": time.time(), "pending": 0}
        if self._disabled:
            return empty
        with self._lock:
            try:
                cursor = self._db().execute(
                    "SELECT id, captured_at, payload, frame, frame_is_raw,"
                    " size_bytes"
                    " FROM buffered_detections ORDER BY id ASC LIMIT ?",
                    (limit,),
                )
                # Stream instead of fetchall(): stop stepping the cursor once
                # the byte cap is reached so SQLite never materializes the
                # frame BLOBs of rows this page will not include.
                rows = []
                page_bytes = 0
                for row in cursor:
                    size = row[5]
                    if rows and page_bytes + size > PAGE_SOFT_BYTES:
                        break
                    page_bytes += size
                    rows.append(row)
                pending = self._count
            except sqlite3.Error:
                self._handle_db_error("list_backlog")
                return empty
        # JSON/base64 conversion happens outside the lock so drain-page
        # formatting never stalls the pipeline-finish thread's writes.
        records = []
        for rec_id, captured_at, payload, frame, frame_is_raw, _size in rows:
            record = {"id": rec_id, "captured_at": captured_at,
                      "frame": None, "raw_frame": None}
            record.update(json.loads(payload))
            if frame is not None:
                b64 = base64.b64encode(frame).decode('ascii')
                record["raw_frame" if frame_is_raw else "frame"] = b64
            records.append(record)
        return {"records": records, "device_now": time.time(), "pending": pending}

    def ack(self, ids: list) -> int:
        """Delete records the hub confirmed persisting. Idempotent."""
        ids = [int(i) for i in ids]
        if self._disabled or not ids:
            return 0
        deleted = 0
        with self._lock:
            try:
                for start in range(0, len(ids), 500):
                    chunk = ids[start:start + 500]
                    marks = ",".join("?" * len(chunk))
                    freed_bytes, freed_count = self._db().execute(
                        "SELECT COALESCE(SUM(size_bytes), 0), COUNT(*)"
                        f" FROM buffered_detections WHERE id IN ({marks})",
                        chunk,
                    ).fetchone()
                    self._db().execute(
                        f"DELETE FROM buffered_detections WHERE id IN ({marks})",
                        chunk,
                    )
                    self._count -= freed_count
                    self._bytes -= freed_bytes
                    deleted += freed_count
                self._db().commit()
            except sqlite3.Error:
                self._handle_db_error("ack")
        return deleted

    # ── internals (all called with self._lock held) ──────────────────────────

    def _offline(self) -> bool:
        """Whether the hub has gone silent past the offline threshold."""
        return self._last_pull is None or (
            self._clock() - self._last_pull) > self._offline_threshold_s

    def _open(self, recreate_on_error: bool) -> None:
        """Open (or create) the database; on corruption, recreate from scratch."""
        directory = os.path.dirname(self._db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            self._connect()
        except sqlite3.DatabaseError:
            if not recreate_on_error:
                raise
            logger.exception(
                "detection buffer at %s is unusable; recreating", self._db_path)
            self._close()
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(self._db_path + suffix)
                except OSError as exc:
                    # Best-effort cleanup: missing/locked sidecar files should not
                    # prevent a reconnect attempt during recovery.
                    logger.debug(
                        "detection buffer cleanup skipped for %s: %s",
                        self._db_path + suffix,
                        exc,
                    )
            self._connect()

    def _connect(self) -> None:
        # Single connection shared across the pipeline-finish thread (writes)
        # and the gRPC pool (reads/deletes); self._lock serializes every use.
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db().execute("PRAGMA journal_mode=WAL")
        self._db().execute("PRAGMA synchronous=NORMAL")
        self._db().execute("PRAGMA busy_timeout=5000")
        self._db().execute(
            "CREATE TABLE IF NOT EXISTS buffered_detections ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " captured_at REAL NOT NULL,"
            " payload TEXT NOT NULL,"
            " frame BLOB,"
            " frame_is_raw INTEGER NOT NULL DEFAULT 1,"
            " size_bytes INTEGER NOT NULL)"
        )
        self._db().execute(
            "CREATE TABLE IF NOT EXISTS buffer_meta"
            " (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._db().commit()
        self._count, self._bytes = self._db().execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM buffered_detections"
        ).fetchone()
        self._hub_seen = self._db().execute(
            "SELECT 1 FROM buffer_meta WHERE key = ?", (_HUB_SEEN_KEY,)
        ).fetchone() is not None

    def _db(self) -> sqlite3.Connection:
        # Invariant: every caller holds the lock and runs only while the
        # buffer is enabled, and enabled implies an open connection.
        assert self._conn is not None
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                logger.debug(
                    "ignoring sqlite error while closing detection buffer connection",
                    exc_info=True,
                )
            self._conn = None

    def _handle_db_error(self, op: str) -> None:
        """One reopen/recreate attempt; if that also fails, disable the buffer."""
        logger.exception("detection buffer %s failed; reopening database", op)
        self._close()
        try:
            self._open(recreate_on_error=True)
        except (sqlite3.Error, OSError):
            logger.exception("detection buffer reopen failed; disabling buffer")
            self._disabled = True

    def _evict_over_caps(self) -> None:
        """Drop oldest rows while over the record/byte caps (ring semantics)."""
        discarded = 0
        while self._count > 1 and (
            self._count > self._max_records or self._bytes > self._max_bytes
        ):
            rows = self._db().execute(
                "SELECT id, size_bytes FROM buffered_detections"
                " ORDER BY id ASC LIMIT ?",
                (_EVICT_BATCH,),
            ).fetchall()
            over = max(self._count - self._max_records, 0)
            for rec_id, size in rows:
                if not (self._count > 1 and (
                        over > 0 or self._bytes > self._max_bytes)):
                    break
                self._db().execute(
                    "DELETE FROM buffered_detections WHERE id = ?", (rec_id,))
                self._count -= 1
                self._bytes -= size
                over -= 1
                discarded += 1
        if discarded:
            self._db().commit()
            self._discarded_since_log += discarded
            now = self._clock()
            if now - self._last_discard_log >= _DISCARD_LOG_INTERVAL_S:
                logger.warning(
                    "detection buffer full: discarded %d oldest record(s)",
                    self._discarded_since_log,
                )
                self._discarded_since_log = 0
                self._last_discard_log = now
