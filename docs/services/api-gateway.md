# API Gateway (Python)

The thin HTTP↔gRPC/SHM interface and the **only public HTTP surface** (port
5000, Flask + Waitress). It mirrors the legacy REST/SSE/MJPEG contract
byte-for-byte so the web app and Flow need no changes:

- **Control / config / models / classes / areas / system / GPIO / network /
  training**: translated to gRPC calls (inference-service `:50061`,
  training-service `:50071`, `os-base` agent `:50051`).
- **Both MJPEG feeds** (`/api/v1/video_feed`, `/api/v1/video_feed_processed`):
  fanned out directly from the camera and processed SHM rings.
- **Unified SSE** (`/api/v1/events/stream`): invalidation events plus a
  multiplexed stats channel, fed by background relays of inference's
  `StreamEvents` / `StreamStats`.
- Keeps Protocol Buffers content-negotiation for the endpoints the frontend
  uses it on (start/stop/threshold/overlay_threshold/runtime/status/classes).

It ships no ML stack (no torch/tensorrt) — only the web layer and the compiled
proto stubs on top of `conecsa-os-base:base`.

!!! note "SSE thread budget"
    Waitress is thread-per-connection; long-lived MJPEG/SSE streams pin one
    task thread each. Size `WAITRESS_THREADS` above the worst-case number of
    concurrent streams.

## Reference

- Full endpoint catalogue: [HTTP API reference](../api-reference.md)
- Python API: [`gateway` package](../reference/python-api/index.md)
- Configuration: [api-gateway env vars](../configuration.md#api-gateway)
