"""SSE controllers: the stats stream and the unified invalidation-event stream."""
import json

from flask import Response, request

from ..events import event_service
from . import api_bp


@api_bp.route('/api/v1/stats/stream', methods=['GET'])
def stream_stats():
    """GET /api/v1/stats/stream — gateway relay."""
    def generate():
        """SSE generator: yield the current snapshot then stream subsequent updates."""
        track = event_service._version  # ignore invalidation churn; stats only
        stats_version, snap = event_service.stats_snapshot()
        yield f"data: {json.dumps(snap)}\n\n"
        while True:
            _v, _events, stats_version, stats, changed = event_service.wait_for_changes(
                track, stats_version, timeout=15.0
            )
            if changed and stats is not None:
                yield f"data: {json.dumps(stats)}\n\n"
            else:
                yield ": keepalive\n\n"

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@api_bp.route('/api/v1/events/stream', methods=['GET'])
def stream_events():
    """GET /api/v1/events/stream — gateway relay."""
    include_stats = request.args.get("stats") in ("1", "true", "yes")

    def _stats_envelope(version, stats):
        """Wrap a stats payload in the unified SSE envelope."""
        return {"version": version, "type": "stats", "source": "api",
                "keys": ["stats"], "data": stats}

    def generate():
        """SSE generator: yield the current snapshot then stream subsequent updates."""
        version, event = event_service.snapshot()
        yield f"data: {json.dumps(event)}\n\n"
        stats_version = None
        if include_stats:
            stats_version, stats = event_service.stats_snapshot()
            if stats:
                yield f"data: {json.dumps(_stats_envelope(stats_version, stats))}\n\n"
        while True:
            version, events, stats_version, stats, changed = event_service.wait_for_changes(
                version, stats_version, timeout=15.0
            )
            if not changed:
                yield ": keepalive\n\n"
                continue
            for item in events:
                yield f"data: {json.dumps(item)}\n\n"
            if stats is not None:
                yield f"data: {json.dumps(_stats_envelope(stats_version, stats))}\n\n"

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp
