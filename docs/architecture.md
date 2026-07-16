# Architecture

## Services

| Service | Language/Framework | Port | IPC |
|---|---|---|---|
| **os-base** | CUDA 12.6 + Python 3.10 (base image) **+ hardware gRPC agent** | gRPC `50051` | Named volumes + gRPC + GPIO SHM |
| **system-vision** | Rust + Leptos (WASM) / Tauri (desktop) | `443` (host, mTLS — the only production port) / 80 (Nginx, dev `${SYSTEM_VISION_PORT:-80}`) | HTTP |
| **api-gateway** | Python + Flask + Waitress (HTTP↔gRPC/SHM interface) | `5000` (internal; host-published in dev only) | HTTP out; gRPC + Shared Memory in |
| **inference-service** | Python (headless: gRPC + TensorRT pipeline) | gRPC `50061` | Shared Memory (camera in, processed out) |
| **training-service** | Python (headless: gRPC + child-process torch) | gRPC `50071` | Shared Memory (camera in) + gRPC |
| **webcam-server** | Rust (synchronous capture via nokhwa/v4l) | — | Shared Memory (producer) |
| **flow** | Node-RED + Conecsa custom nodes | `1880` (internal; host-published in dev only) | HTTP (→ api-gateway) |

In production only system-vision's `:443` mTLS endpoint is published; the
other host ports in the table apply to the dev stack
(`docker-compose.dev.yml`).

The **api-gateway** is the only HTTP surface: the web app and Flow talk to
it on `:5000`, and it translates each call to the headless inference-service
(gRPC `:50061`), the training-service (gRPC `:50071`) or the `os-base` hardware agent
(gRPC `:50051`), or fans the camera / processed MJPEG feeds out of shared
memory. Per-frame media never crosses gRPC.

The **`os-base`** service builds the `conecsa-os-base:base` image (CUDA + Python + ML
stack: torch, torchvision, tensorrt, pycuda, opencv, ultralytics, numpy,
etc.) which is inherited via `FROM` by the other Python services
(inference-service, api-gateway and training-service). It also owns the shared
volumes (`/data/models`, `/data/runs`).

Beyond the base image, the `os-base` container runs the **privileged hardware
agent** — see [os hardware agent](services/os-hardware-agent.md) for the full
breakdown (network/Wi-Fi/GPIO, GPIO SHM hot path, performance-clock pinning).

### Fleet hub (`hub-vision`)

The table above lists the per-device **compose** services. A separate native
(Tauri 2 + Leptos) app, **`hub-vision`**, is the single authenticated, secure
entry point to a fleet of these devices. It is **not** in the compose stack and
runs on its own host on the LAN: it discovers devices over mDNS (`_conecsa._tcp`),
pairs with each (acting as a private CA), and reaches them **only over mutual
TLS** — pulling their detection records, not receiving pushed ones. See
[Fleet hub](services/hub-vision.md).

## Communication between services

![Communication diagram](communication.png)

Two transport rules: **per-frame media** (raw + processed JPEG) crosses **POSIX
shared memory**, never gRPC; **control / config / status / events / stats** go
over **gRPC**.

- The `webcam-server` captures frames and publishes them to the **camera SHM
  ring** (`/dev/shm/conecsa_frame_shm`). Its header is defined in
  `proto/shm.proto` (frame metadata + raw/JPEG bytes). The inference-service,
  the api-gateway and the training-service all read it.
- The `inference-service` consumes the camera ring, runs the
  decode∥infer∥encode pipeline, and publishes the overlaid JPEGs to a second
  **processed SHM ring** (`/dev/shm/conecsa_processed_shm`). The api-gateway fans
  both rings out to MJPEG clients. These containers share the `ipc:`
  namespace (`ipc: shareable` on webcam-server; `ipc: "service:webcam-server"`
  on inference-service, api-gateway and training-service).
- Control/telemetry travels over gRPC: the api-gateway drives the
  inference-service's `DetectionControl` / `ModelControl` / `ManagementControl`
  (`proto/inference.proto`, `:50061`), the training-service's `TrainingControl`
  (`proto/training.proto`, `:50071`) and the hardware agent's `HardwareService`
  (`proto/hardware.proto`, `:50051` — the `os-base` container; the gateway's
  code default addresses it by the host alias `os`, compose by `os-base`),
  re-publishing inference's event/stats streams onto a single unified SSE.
- Off-device, the [Fleet hub](services/hub-vision.md) (`hub-vision`) discovers
  devices over mDNS and **pulls** their detection records over mutual TLS (it
  polls each paired device's `/api/v1/detections/snapshot`); the device exposes
  only its `:443` mTLS endpoint. This is a LAN mTLS/mDNS path, separate from the
  intra-device gRPC + SHM transports above.

See the [Protocol Buffers reference](reference/proto.md) for the full message
and service catalogue.

## Frontend (Rust)

The device UI, **`system-vision`**, is a Leptos app compiled to **WASM** via
Trunk and served by Nginx (port `:80`). It talks to the api-gateway over
HTTP/SSE/MJPEG, resolving the API host at runtime via `get_api_base_url()`.

The native **Tauri 2** desktop app in this repo is the separate
[`hub-vision`](services/hub-vision.md) fleet hub — a different application, not a
desktop build of `system-vision`.

### Localization

Both frontends are localized (**en** default, **pt-BR**, **es**) with
[`leptos_i18n`](https://crates.io/crates/leptos_i18n) 0.6. Translations are
compiled in: each crate's `build.rs` generates the i18n module from the shared
catalogs under the `i18n/` directory at the monorepo root
(`i18n/system-vision/<locale>/<namespace>.json`,
`i18n/hub-vision/<locale>.json` — layout, parity rules and the cross-app
terminology glossary are documented in `i18n/README.md`).

The device UI has **no language selector**. The only selector lives in the
hub's **Settings** page; the hub persists the choice (`hub-settings.json`) and
appends `?lang=<locale>` to the embedded device page's iframe URL. The device
UI resolves its locale as `?lang=` → localStorage (`conecsa.lang`, written on
every change so direct browser access keeps the last language) →
`navigator.languages` → `en`.

### Interface

Three-column layout with auto-refresh every 2 seconds:

- **Left — Video**: live stream with detections. Overlaid on the video:
    - **Top-right `▦`** (`AddAreaButton`): creates a new detection area
      centered in the frame and enters editing mode.
    - **Top-left** (`AreaChips`): chip strip listing every existing area.
      The `□`/`○` glyph indicates the shape; clicking the number enters
      editing; clicking the `✗` deletes the area. The chip for the editing
      area is highlighted amber.
    - **Bottom bar** (`EditingToolbar`, visible only while an area is in
      editing mode): movement controls (`↑ ↓ ← →`), axis resize (`W+`/`W−`
      width, `H+`/`H−` height), uniform (`⤢`/`⤡`), shape toggle (`□` ↔ `○`),
      `✓` saves and `✗` cancels (deletes the editing area).
- **Center — Control**: Start/Stop, ViewMode selector, performance statistics
- **Right — Configuration**: model upload/selection, thresholds (confidence
  + NMS), runtime selector, camera configuration, label management

## Protocol Buffers

All `.proto` files live under the `proto/` directory at the monorepo root. The
generated [Protocol Buffers reference](reference/proto.md) documents every
message and service.

| File | Use |
|---|---|
| `proto/detection.proto` | Schema of the REST message bodies (consumed by the Rust frontend (system-vision) via `prost`; used by the api-gateway for HTTP protobuf content-negotiation) |
| `proto/shm.proto` | Schema of the camera shared-memory header (webcam-server → inference-service / api-gateway / training-service) |
| `proto/inference.proto` | gRPC control/telemetry contract between the api-gateway and the headless inference-service (`:50061`) |
| `proto/hardware.proto` | gRPC contract for the `os-base` hardware agent (`HardwareService`, `:50051`) |
| `proto/training.proto` | gRPC contract for the training-service (`TrainingControl`, `:50071`) |

**Compilation**:

- **Rust** (system-vision, webcam-server): compiled automatically via `build.rs` with
  `prost-build` during `cargo build`
- **Python** (inference-service, api-gateway, training-service): compiled with
  `grpc_tools.protoc` in the Dockerfile (or locally with
  `scripts/compile-proto.sh`)
- **Script**: `scripts/compile-proto.sh` compiles every `.proto` for Python
  and triggers `cargo build` for Rust

## Tech stack

| Layer | Technology |
|---|---|
| Frontend UI | Leptos 0.8.15 (Rust WASM, served by Nginx) |
| Fleet hub | `hub-vision` — Leptos + Tauri 2.0 (native desktop, off-device) |
| Frontend build | Trunk, TailwindCSS |
| Localization | leptos_i18n 0.6 — compile-time catalogs (en / pt-BR / es) under `i18n/` |
| Protobuf client | prost 0.14.3 |
| Webcam server | Rust — nokhwa 0.10 (+ v4l 0.14 / rscam on aarch64), synchronous capture |
| Frame transport | POSIX Shared Memory (zero-copy IPC) — camera + processed rings |
| API gateway | Python 3.10 + Flask 3.1.2 + Waitress 3.0.2 (HTTP↔gRPC/SHM) |
| Inference | Headless Python — TensorRT pipeline + gRPC control |
| Training | Headless Python — ultralytics + SAM3 in child processes + gRPC control |
| Control plane | gRPC (grpcio): inference `:50061`, training `:50071`, os hardware agent `:50051` |
| Detection | TensorRT (TFLite/LiteRT/PyTorch removed) |
| Serialization | Protocol Buffers (protobuf / prost) |
| Automation | Node-RED + `conecsa-system-vision` package (9 custom nodes) |
| Containerization | Docker Compose + NVIDIA Container Runtime |
