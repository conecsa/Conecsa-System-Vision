# Webcam Server (Rust)

Captures MJPEG directly via V4L2 (`/dev/video0`). Supports native MJPEG
cameras (zero-CPU passthrough), bilinear debayering of RGGB8 Bayer frames
and a YUYV fallback. Configuration (index, resolution, framerate,
automatic/manual exposure) can be changed in real time via shared memory
with no restart. When no camera is available it serves an animated test
pattern, and it **re-attempts the real camera every few seconds** so a
re-plugged / re-powered camera self-heals without restarting the container.
It is `privileged` (no static `/dev/video0` mapping — that would block startup
when the camera is unplugged), so it sees `/dev/video*` including hot-plug.

Captured frames are published to a POSIX shared memory segment (`SHM_NAME`),
with a Protocol Buffers header describing the frame. The SHM slot is sized for
the largest frame the camera can deliver (`SHM_SLOT_MIN_BYTES`, code default
8 MB; compose raises it to 16 MB so the stereo camera's native 3840×1080 RAW
fallback fits).
The container runs with `ipc: shareable` so the inference-service, api-gateway
and training-service share the same IPC namespace.

## Reference

- Rust API: `cargo doc` → `webcam_server` crate (see the Rust API link in the
  nav, or run `scripts/build-docs.sh`)
- SHM header schema: [`proto/shm.proto`](../reference/proto.md)
- Configuration: [webcam-server env vars](../configuration.md#webcam-server)
