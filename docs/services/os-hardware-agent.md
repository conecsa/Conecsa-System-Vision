# `os-base` — base image + hardware agent

The `os-base` service plays two roles.

## 1. The `conecsa-os-base:base` image

It builds `conecsa-os-base:base` (CUDA 12.6 + Python 3.10 + the ML stack: torch,
torchvision, tensorrt, pycuda, opencv, ultralytics, numpy, …), which is
inherited via `FROM base` by every Python service (inference-service,
api-gateway and training-service). `docker-compose.yml` maps
`base=service:os-base` in `additional_contexts`, so compose builds this image first.
The `os-base` service also owns the shared volumes (`/data/models`, `/data/runs`).
The shared ML/CUDA requirements are the single source of truth in
`os-base/requirements-common.txt`.

## 2. The privileged hardware agent

Beyond the base image, the `os-base` container runs the **privileged hardware
agent** (`python3 -m agent`): a gRPC `HardwareService` on `:50051`
(`proto/hardware.proto`) that owns all host hardware access. The api-gateway
(network/Wi-Fi/GPIO endpoints) and the inference-service (GPIO hot path) are
clients of this agent.

### Network / Wi-Fi configuration

The device uses **systemd-networkd + wpa_supplicant** (not NetworkManager /
`nmcli`). The agent reads and writes the wired + Wi-Fi configuration, scans for
networks, and connects/forgets saved networks.

!!! warning "Wi-Fi connect must not strand the device"
    A failed connect must never persist the new config (no `SAVE_CONFIG` on
    failure): the agent rolls back with a wpa `RECONFIGURE` so a bad password
    cannot lock the device out of its network.

### GPIO

GPIO uses **BOARD numbering** on the Jetson Orin Nano 40-pin header: pin 7 is
the trigger input; pins 29/31/33 are freely-controllable digital outputs (driven
from Node-RED). The agent configures the pinmux + `Jetson.GPIO` and runs a small
poll loop.

The only per-frame GPIO **hot path** is the trigger gate: it does **not** cross
gRPC but a small mmap **GPIO SHM** channel (`/run/conecsa-gpio/state`,
overridable via `GPIO_SHM_PATH`), so the
inference-service can read the trigger pin level every frame without RPC
overhead. Output pins are event-driven, not per-frame, so they are driven on
demand over gRPC (`SetGpioPin`); availability, trigger mode and current pin
levels are read with `GetGpioStatus`.

### System metrics

Host CPU/RAM/disk/temperature/GPU metrics (via `psutil` + Jetson sysfs) are
exposed over the same gRPC service and surfaced by the gateway on
`/api/system/status`.

### System power

The agent also owns host shutdown/restart via the `SystemPower` RPC, surfaced
by the gateway on `POST /api/v1/system/power`.

### Performance-clock pinning

At startup the agent **pins the Jetson performance clocks** (GPU
`min_freq = max_freq`, CPU cores → `performance` governor — the core of
`jetson_clocks`). Without it the dynamic governors keep the GPU at its minimum
for the bursty TensorRT workload, roughly doubling inference latency. Opt out
with `PIN_PERFORMANCE_CLOCKS=0`.

## Reference

- Python API: [`agent` and `conecsa_shm` packages](../reference/python-api/index.md)
- gRPC contract: [`proto/hardware.proto`](../reference/proto.md)
