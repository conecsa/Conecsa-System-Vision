# Conecsa Object Detection System

Real-time object detection system built with a Rust web frontend (Leptos/WASM),
a Rust camera server and a Python inference backend. Designed for the **NVIDIA
Jetson Orin Nano** embedded hardware (ARM64, JetPack 6.2.2 / L4T R36.5.0,
CUDA 12.6), with
**TensorRT-only** inference.

The backend follows an **`app → api → service`** split: a thin **api-gateway**
owns the entire external HTTP/SSE/MJPEG contract, while the heavy work runs in
independent services it reaches over **gRPC** (control/config) or **POSIX shared
memory** (per-frame media). The **inference-service is headless** (no HTTP — only
a gRPC control server + the decode∥infer∥encode pipeline), a privileged
**`os-base` hardware agent** owns host network/Wi-Fi/GPIO over gRPC, and a headless
**training-service** owns datasets, SAM3-assisted labeling and YOLO training.

A separate native **`hub-vision`** desktop app is the single authenticated, secure
entry point to a fleet: it discovers devices on the LAN over mDNS and **pulls**
their detection records over mutual TLS. It is not part of the compose stack —
it runs on a hub machine, or **on a Jetson itself as a boot-time Wayland kiosk**
on the DisplayPort — see [Fleet hub](services/hub-vision.md).

## Documentation map

| Page | Contents |
|---|---|
| [Architecture](architecture.md) | Services, transports, communication rules, the frontend |
| [Getting started](getting-started.md) | Prerequisites, Docker quick start, local development |
| [Configuration](configuration.md) | Every `docker-compose` environment variable |
| [HTTP API reference](api-reference.md) | All REST/SSE/MJPEG endpoints on the api-gateway |
| [Troubleshooting](troubleshooting.md) | Common failures + Yocto runtime notes |
| **Services** | [inference-service](services/inference-service.md) · [api-gateway](services/api-gateway.md) · [webcam-server](services/webcam-server.md) · [os hardware agent](services/os-hardware-agent.md) · [training-service](services/training-service.md) · [Flow](services/flow.md) |
| [Fleet hub](services/hub-vision.md) | The native `hub-vision` app: auth, mDNS discovery + mTLS detection pull across many devices |
| **Reference** | [Protocol Buffers](reference/proto.md) · [Python API](reference/python-api/index.md) · Rust API (`cargo doc`) |
| [Yocto build](yocto-build.md) | Building the lean Yocto host image for the Jetson |

## Features

- **Real-time detection**: supports YOLO26 models via TensorRT
  (`.pt`, `.engine`, `.plan`, `.onnx`)
- **Single runtime**: application pinned to TensorRT
- **Detection areas**: one or more rectangular or circular regions defined in
  the UI (normalized coordinates in `[0,1]`) where inference is restricted.
  Persistent across restarts.
- **Streaming via shared memory**: camera frames are transferred from the
  webcam-server to the inference-service through POSIX shared memory
  (zero-copy IPC), eliminating HTTP network overhead
- **MJPEG streaming**: the processed stream with detection overlays is
  exposed over HTTP for the frontend
- **Model management**: upload, selection, deletion and asynchronous
  `.pt` → `.engine` conversion (TensorRT)
- **On-device training**: capture datasets, label with SAM3 assistance and
  train YOLO models without leaving the device (see
  [training-service](services/training-service.md))
- **Camera configuration**: real-time adjustment of index, resolution,
  framerate and exposure via shared memory, no restart required
- **System monitoring**: real-time CPU, RAM, disk, temperature and GPU usage
- **Web frontend**: Leptos compiled to WASM, served by Nginx
- **Multilingual UI**: English (default), Brazilian Portuguese and Spanish in
  both frontends; the language selector lives in the hub's **Settings** and
  propagates to embedded device pages (see
  [Architecture § Localization](architecture.md#localization))
- **Fleet aggregation hub**: a separate native (Tauri) `hub-vision` app is the
  single authenticated gateway — it discovers devices over mDNS and pulls their
  detections over mutual TLS; it runs on a hub machine or as a **boot-time
  kiosk on the device's DisplayPort** (see [Fleet hub](services/hub-vision.md))
- **Efficient API**: REST with Protocol Buffers serialization (JSON fallback)

## Quick start

```bash
# Build and bring everything up in one go.
docker compose up -d --build
docker compose logs -f
```

The production stack publishes only `:443` (mTLS) — the device's UI, API and Flow
editor are reached through the `hub-vision` app. The dev stack
(`docker-compose.dev.yml`) also exposes the plaintext ports (`:80`, `:5000`,
`:1880`) for local work. See [Getting started](getting-started.md) for the full
setup.
