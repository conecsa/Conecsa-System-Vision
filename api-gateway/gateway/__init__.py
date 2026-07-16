"""API gateway package.

The api-gateway is a thin HTTP↔gRPC/SHM interface: it keeps the external REST /
SSE / MJPEG contract byte-compatible while the real work lives in the headless
inference-service (gRPC control + processed-frame SHM) and the `os` hardware
agent (network/Wi-Fi/GPIO over gRPC). Per-frame media never crosses gRPC — the
gateway reads the camera and processed-frame POSIX SHM rings directly.
"""
