# Troubleshooting

- **API does not connect**: verify the `api-gateway` is up on port 5000 and can
  reach inference over gRPC (`inference-service:50061`). On a fresh start the
  gateway logs a few "connection refused" retries during the inference TensorRT
  warm-up (~60s), then self-heals
- **Stream has no video**: verify permissions on `/dev/video0` and that the
  webcam-server is publishing frames to SHM
  (`ls /dev/shm/conecsa_frame_shm`)
- **"Camera not connected" in the UI / detection refuses to start**: the
  webcam-server cannot open the device, so it publishes **no frames at all** —
  only the `no_camera` health status, which the inference-service and the UI use
  to block detection (`POST /api/v1/start` → 409). Check `CAMERA_INDEX` in
  docker-compose and that `/dev/video*` exists on the host; the server keeps
  retrying every 5s, so a re-plugged camera recovers on its own
- **Video drops out after a few seconds**: usually insufficient USB power — the
  camera resets off the bus under streaming load
  (`dmesg | grep -i "usb disconnect"`). Use a powered USB hub / shorter cable.
  webcam-server self-recovers once the camera is stable again
- **SHM not available**: confirm `ipc: shareable` on webcam-server and
  `ipc: "service:webcam-server"` on inference-service, api-gateway **and**
  training-service. Restart those together — joining a recreated IPC namespace
  requires it, so restarting webcam-server alone strands the others' `/dev/shm`
- **TensorRT not available**: the runtime requires an NVIDIA GPU + JetPack;
  since the application runs in TensorRT-only mode, detection cannot start
  without a working TensorRT
- **WASM build fails**: check `rustup target list --installed | grep wasm32`
- **Protobuf incompatibility**: run `scripts/compile-proto.sh` or rebuild
  the Docker containers (protos are compiled at build time)
- **Legacy dependencies**: the TFLite/LiteRT/PyTorch runtimes were removed;
  only TensorRT is supported
- **Flow does not open**: check `http://localhost:1880`; confirm the
  service is up with `docker compose logs flow`
- **TensorRT cold-start is slow**: normal on first use (~30s); the worker
  is pre-warmed in the background on the next startup

## Running on the custom Yocto image (Jetson Orin Nano)

When the host is the lean Yocto image (see [Yocto build](yocto-build.md) and the
flashing runbook in `yocto/FLASHING.md`), and **not** the stock
JetPack/Ubuntu, there are differences that affect `docker-compose.yml`:

- **NVIDIA libraries in `/usr/lib/`, not `/usr/lib/aarch64-linux-gnu/`**:
  Yocto is single-arch. The TensorRT/cuDNN bind-mounts in compose use
  source `/usr/lib/...` (host) → destination
  `/usr/lib/aarch64-linux-gnu/...` (container). cuDLA lives in
  `/usr/local/cuda-12.6/lib/`. Symptom if wrong:
  `libnvinfer.so.10: cannot open shared object file`.
- **Do not bind-mount `/usr/lib/aarch64-linux-gnu/{nvidia,tegra}` as
  directories**: it collides with `tegra-container-passthrough` (per-file
  injection by `runtime: nvidia`) and breaks the container with
  `read-only file system` at init. Let the runtime handle those libraries;
  only TensorRT/cuDNN/cuDLA need an explicit mount.
- **Docker at boot**: the image enables `docker.service` (via
  `conecsa-bootstrap`), so containers with `restart: unless-stopped` come
  back after reboot. On JetPack `docker.socket` (socket activation) was
  enough.
- **No `apt`**: the image uses RPM/DNF (`rpm -qa`, `dnf install`) and does
  not ship a configured remote feed.
- **Display shows the kiosk, not a console**: the DisplayPort runs the
  `hub-vision` Weston kiosk (empty compositor background until the hub binary
  is deployed with `scripts/build-hub-jetson.sh`); there is no getty on
  `tty0`. Administer via the serial console (root, no password) or SSH.
  **SSH is key-only** (no passwords) and restricted to permitted hosts — the
  root key is provisioned over serial after flashing (see "SSH hardening" in
  [Yocto build](yocto-build.md)). Until then SSH refuses logins; serial is the
  provisioning channel.
- **Kiosk troubleshooting** (blank webview, weston/seatd failures, slow boot
  from `wait-online`): see the Troubleshooting section of
  [Yocto build](yocto-build.md#troubleshooting).
