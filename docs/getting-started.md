# Getting started

## Prerequisites

### Target hardware

- **NVIDIA Jetson Orin Nano** (ARM64/aarch64, JetPack 6.2.2 / L4T R36.5.0, CUDA 12.6)
- For local development on x86_64: TensorRT requires a compatible NVIDIA GPU

### System dependencies (Linux)

```bash
sudo apt-get install pkg-config libssl-dev libudev-dev v4l-utils protobuf-compiler
```

### Rust

```bash
# Install via rustup
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Add the WASM target
rustup target add wasm32-unknown-unknown

# Install Trunk (build tool for WASM)
cargo install trunk
```

### Python

For off-device development (api-gateway, the services' control-plane logic,
docs, type-checking) a **single root virtualenv** is enough — it aggregates every
service's deps plus the docs toolchain via `requirements-dev.txt`.

The fastest path is `./scripts/init.sh` (see [Local development](#local-development)),
which provisions the venv, installs the deps, compiles the proto stubs and warms
up pyright in one go. The manual equivalent is:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` pulls in each service's own requirements file with `-r`,
so the pins live in one place: the shared ML/runtime stack, the api-gateway web
stack, **the hardware agent's deps** (`jeepney`, `Jetson.GPIO` — pure-python, and
`Jetson.GPIO` raising at import off-device is exactly what makes
`create_gpio_backend()` return a `NullGpioBackend`), the docs toolchain, pytest
and pyright. That is deliberately a superset of what the tests need: the type
checker resolves against these packages, and a missing one would quietly degrade
its symbols to `Unknown` rather than fail.

Three things stay out of the venv because they only exist on the device:

- **`tensorrt` / `pycuda`** — need a CUDA toolkit. `./scripts/init.sh --gpu`
  installs the x86_64 flavour; the aarch64 recipe is below.
- **The Jetson `torch` / `torchvision` / `onnxruntime-gpu` wheels** from the
  jetson-ai-lab index. (A CPU `torch` does land in the venv via `ultralytics` —
  enough for the host tests and the type checker.)
- **`sam3`** — git-cloned into the training image and run in a subprocess on the
  device; its import is guarded, so nothing off-device needs it.

!!! warning "Use Python 3.10–3.12 for the venv"
    NVIDIA only publishes TensorRT/PyCUDA wheels for CPython **3.8–3.12** — there
    are no binding wheels for 3.13/3.14. If your system `python3` is newer,
    `pip install tensorrt` falls through to a source build that fails with
    `No matching distribution found for tensorrt_cu12_bindings`. Create the venv
    with a 3.10 interpreter (matches the Jetson). If you don't have one,
    [`uv`](https://docs.astral.sh/uv/) can provision it without touching the
    system Python:

    ```bash
    uv python install 3.10
    uv venv --python 3.10 .venv
    source .venv/bin/activate
    uv pip install -r requirements-dev.txt
    ```

#### GPU stack for local inference (x86_64)

To **run the inference locally** you need an NVIDIA GPU plus the CUDA stack.
This is kept out of `requirements-dev.txt` because the Jetson installs it
differently (the aarch64 device wheels below). `./scripts/init.sh --gpu`
installs the `tensorrt-cu12` + `pycuda` part of the steps below for you; the
CUDA driver/toolkit (steps 1–2) still has to be installed system-wide first.

1. **NVIDIA GPU (required)** — install the CUDA drivers and libraries from
   <https://developer.nvidia.com/cuda-downloads>.

2. **CUDA Toolkit**

   ```bash
   sudo apt-get install nvidia-cuda-toolkit
   ```

3. **PyCUDA** (inside the venv):

   ```bash
   pip install pycuda
   ```

4. **TensorRT** — `pip install tensorrt` resolves the build matching your
   CUDA/hardware:

   ```bash
   pip install tensorrt
   ```

!!! note
    The TensorRT wheels are large. To avoid hitting the disk limit on the
    `/tmp` volume, point `TMPDIR` at a temporary folder outside `/tmp`:

    ```bash
    TMPDIR="$HOME/.tmp" pip install tensorrt
    ```

!!! note "CUDA version parity"
    Plain `tensorrt` resolves to the latest build (currently TensorRT 11 /
    **cu13**), which needs a matching CUDA 13 runtime locally. The Jetson runs
    TensorRT 10.3 / **CUDA 12.6**. This mismatch is harmless for local dev —
    engines are not portable across TensorRT versions and are rebuilt locally
    from ONNX — but to mirror the device, install the cu12 build instead
    (`pip install tensorrt-cu12`) and make sure your local CUDA toolkit is 12.x.

On the **Jetson** (or wherever you need the GPU stack — TensorRT/PyCUDA/Torch),
add the aarch64 device wheels into the *same* venv:

```bash
pip config set global.extra-index-url https://pypi.jetson-ai-lab.io/jp6/cu126
pip install --no-deps torch==2.11.0 torchvision==0.26.0 onnxruntime-gpu==1.23.0 \
    https://github.com/Shattered217/Jetson-Orin-Nano-Wheels/releases/download/6.2.1rc1/tensorrt-10.3.0-cp310-none-linux_aarch64.whl
pip install pycuda==2024.1 "onnx>=1.14.0" Jetson.GPIO
pip install --force-reinstall numpy==1.26.4
```


!!! note
    Python 3.10 is required for compatibility with the NVIDIA wheels
    (TensorRT). The `pypi.jetson-ai-lab.io/jp6/cu126` index ships precompiled
    `torch`, `torchvision` and `onnxruntime-gpu` for aarch64+CUDA 12.6. `numpy`
    is left unpinned for dev (opencv needs 2.x) and pinned back to 1.26.4 only
    when the GPU stack is added (pycuda/tensorrt ABI).

## Quick start with Docker (recommended)

```bash
# Build and bring everything up in one go. Compose resolves the build order
# (`os-base` before the derived services) via `additional_contexts: base=service:os-base`.
docker compose up -d --build

# Follow the logs
docker compose logs -f
```

!!! note
    Because the derived services' Dockerfiles start with `FROM base` and
    `docker-compose.yml` maps `base=service:os-base` in `additional_contexts`,
    compose builds the base image first and injects it as context before
    processing each derived service's `FROM`. There is no need to run
    `docker compose build os-base` manually beforehand.

!!! tip "`python-env` volume (opt-in)"
    There is an option to expose the `os-base` `site-packages` as a shared volume
    (commented lines in `docker-compose.yml`). Useful for iterating on Python
    deps without rebuilding the services, with the caveat that a named volume
    is only populated from the image on **first creation** — to refresh it
    later, run `docker volume rm conecsa-python-env` before bringing the stack
    up again.

Services available after startup. In **production** the device publishes **only
`:443`** (the nginx mTLS terminator) — its UI, API and Flow editor are reached
through the [`hub-vision`](services/hub-vision.md) app. The plaintext ports below
are exposed by the **dev stack** (`docker-compose.dev.yml`) for local work:

- Web app: `http://localhost:80`
- API (api-gateway): `http://localhost:5000`
- Flow: `http://localhost:1880`

!!! note
    Neither the webcam-server nor the inference-service nor the training-service
    exposes an HTTP port. The api-gateway is the only HTTP surface (`:5000`);
    the backends are headless (gRPC) and frames travel via shared memory.

!!! warning "`docker-compose.yml` targets the Jetson"
    The root `docker-compose.yml` and its `Dockerfile.*` are **device-specific**
    (aarch64 JetPack wheels, Tegra host-library bind-mounts, GPIO/privileged,
    host network). They do **not** build or run on an x86_64 workstation — use
    the dev stack below for local development off-device.

## Local development with Docker (dev stack)

For local development on an **x86_64 workstation with an NVIDIA GPU**,
`docker-compose.dev.yml` is a faithful mirror of the production stack: it reuses
the **same service Dockerfiles** and the same all-services-up behavior, and only
substitutes the parts that are exclusive to the Jetson.

### Prerequisite: NVIDIA Container Toolkit

The `inference`/`training` services request the GPU via `deploy.resources`, so
the host needs the NVIDIA driver **and** the NVIDIA Container Toolkit registered
with Docker. The driver alone is not enough — without the toolkit the stack
fails with `could not select device driver "nvidia" with capabilities: [[gpu]]`.

```bash
# Add the NVIDIA Container Toolkit apt repo
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Install, register the runtime with Docker, and restart the daemon
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify the GPU is visible inside a container before bringing the stack up:

```bash
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### Run the stack

Bring it up exactly like production, with a single command:

```bash
docker compose -f docker-compose.dev.yml up -d --build

# Logs / teardown
docker compose -f docker-compose.dev.yml logs -f
docker compose -f docker-compose.dev.yml down
```

Services after startup:

- Web app: `http://localhost:80` (override the host port with `SYSTEM_VISION_PORT`)
- API (api-gateway): `http://localhost:5000`
- Flow: `http://localhost:1880`

!!! note "What the dev stack substitutes (Jetson-only → x86_64)"
    Only two things change versus production; every other service builds from its
    **production Dockerfile** unchanged:

    - **`os-base`** builds `os-base/Dockerfile.os-base.dev` — the shared ML stack plus the x86
      GPU wheels from PyPI (`tensorrt-cu12` + `pycuda`, the deps that differ from
      the aarch64 Jetson wheels), installed the way `scripts/init.sh` does. torch
      arrives via ultralytics as a CPU build; TensorRT + pycuda drive GPU
      inference. Every other service builds `FROM` this `conecsa-os-base:dev` base.
      `os-base` also runs as a plain base/volume-owner here (the GPIO/Wi-Fi hardware
      agent is Jetson-only; the gateway tolerates its absence).
    - **`system-vision`** builds `system-vision/Dockerfile.system-vision.dev` —
      identical to production but fetches the x86_64 Tailwind binary instead of
      the aarch64 one.

    The compose file also drops the Jetson-only bits from `inference`/`training`
    (the Tegra host-library bind-mounts, aarch64 `LD_LIBRARY_PATH`/jemalloc, GPIO
    shm, `privileged`/`pid: host`); the GPU is provided by the NVIDIA container
    toolkit via `deploy.resources`.

The bare-metal scripts below (`init.sh` / `dev.sh`) remain as a non-container
alternative.

## Local development

### Quick start (scripts)

Three scripts cover the whole local workflow:

```bash
# 1. One-time bootstrap: create .venv (prefers uv → Python 3.10), install
#    requirements-dev.txt, compile the proto stubs, and warm up pyright. Add
#    --gpu to also install the local TensorRT/PyCUDA stack.
./scripts/init.sh                 # or: ./scripts/init.sh --gpu

# 2. Start the full stack (webcam-server, inference, training, api-gateway,
#    frontend) with interleaved logs. Ctrl+C stops everything.
source .venv/bin/activate
./scripts/dev.sh

# 3. Before opening a PR: the same suites CI runs (pytest, pyright, cargo, jest).
./scripts/test.sh
```

`dev.sh` starts every service by default. On a machine without the GPU stack,
skip the GPU-heavy services and run just the gateway + frontend:

```bash
./scripts/dev.sh --no-inference --no-training
# or, gateway + frontend only (no webcam either):
./scripts/dev.sh --gateway-only
```

Once up: api-gateway on `http://localhost:5000`, web frontend on
`http://localhost:18080` (its `/api` is proxied to the gateway), inference gRPC
on `:50061`, training gRPC on `:50071`.

The rest of this section documents the same steps run individually, which is
useful when iterating on a single service.

### Compile Protocol Buffers

`./scripts/init.sh` already runs this for you; run it directly when you only
need to regenerate the stubs:

```bash
# Compiles every .proto for Python and Rust
./scripts/compile-proto.sh
```

The Python stubs (`*_pb2.py` / `.pyi` / `*_pb2_grpc.py`) are written to
`api-gateway/gateway/proto/` — the api-gateway imports every proto and is the
service you run off-device, so it is the canonical local-dev output. They are
gitignored and regenerated here / inside each service's Dockerfile at build.
Run this once so the editor and type-checker can resolve the proto modules
(see [Type checking](#type-checking-pyright)). `./scripts/init.sh` already does
it for you, and `./scripts/test.sh` generates them if they are missing. At runtime each headless
service falls back to this directory when its own co-located `proto/` (created
only inside the image) is absent.

### Webcam Server (Rust)

```bash
cd webcam-server
cargo run --release
```

### Inference Service (Python, headless — gRPC + pipeline, no HTTP)

```bash
source .venv/bin/activate           # the single dev venv from above
python inference-service/main.py    # starts the pipeline + gRPC :50061, then blocks
```

(Requires the GPU stack — TensorRT/PyCUDA — so this one realistically runs on
the Jetson.)

### API Gateway (Python)

```bash
# Needs the proto stubs under api-gateway/gateway/proto — run
# ./scripts/compile-proto.sh first (also compiled in the image).
source .venv/bin/activate           # the single dev venv from above
python api-gateway/main.py          # serves the HTTP API on :5000
```

### Web frontend (WASM)

`./scripts/dev.sh` launches the frontend along with the backend services. To run
*only* the frontend (Tailwind watch + trunk dev server on `:18080`, with `/api`
proxied to a gateway you run separately on `:5000`):

```bash
cd system-vision
trunk serve --proxy-rewrite=/api --proxy-backend=http://localhost:5000 --port=18080
# http://localhost:18080
```

### Flow

```bash
cd flow && docker build -t conecsa-flow . && docker run -p 1880:1880 conecsa-flow
# Visit http://localhost:1880
```

### Formatting and lint

```bash
cargo fmt
cargo clippy
```

### Type checking (pyright)

**Pyright is the Python type checker for this repo** — the same engine Pylance
runs in the editor, so a clean run on the command line means a clean editor. The
baseline is **zero errors**, and CI enforces it on every pull request.

```bash
pyright                 # whole repo — reads pyrightconfig.json
pyright inference-service/api/model_manager.py   # or a single file
./scripts/test.sh       # runs it alongside the unit tests (SKIP_TYPES=1 to skip)
```

`./scripts/init.sh` installs it (it is pinned in `requirements-dev.txt`) and
warms it up — the pip package downloads its own Node runtime on first run.

Everything it needs is in `pyrightconfig.json`:

- **`extraPaths`** — `api-gateway/gateway/proto` plus the three service roots, so
  the proto modules and each service's top-level package (`api`, `service`,
  `gateway`) resolve with **real types**, not `Any`. This mirrors what the
  runtime does via each pyproject's pytest `pythonpath`.
- **`venvPath`/`venv`** — points at the root `.venv`, which is what lets
  `grpc`/`cv2`/`torch`/… resolve from the installed packages. Note this **wins
  over a `--pythonpath` passed on the command line**.
- **`exclude`** — `yocto/` above all: walking the vendored Poky tree exhausts
  Node's heap and kills the run.
- **`ignore`** — `api-gateway/gateway/proto`. It is `protoc` output (regenerated
  by `scripts/compile-proto.sh`), and its `grpc.experimental` block is not
  declared by the grpcio stubs. Still analyzed, so importers keep real types; we
  just don't lint generated code.

Two prerequisites, both handled by `./scripts/init.sh`:

1. The proto stubs must exist under `api-gateway/gateway/proto`
   (`./scripts/compile-proto.sh`).
2. The root `.venv` must have the dependencies — **an uninstalled package does
   not fail the check, it silently weakens it**: every symbol from it degrades to
   `Unknown`. In the editor, select that `.venv` as the interpreter.

A handful of imports genuinely cannot resolve off-device (`sam3`, the co-located
`api.proto` package created inside the image) and carry a suppression comment at
the import line. Keep that list short — it is the one escape hatch from the zero
baseline.

!!! warning "Suppress with `# pyright: ignore[rule]`, not `# type: ignore[code]`"
    The bracketed codes in `# type: ignore[...]` are **mypy's**, and pyright does
    not read them: it ignores *every* diagnostic on that line regardless of what
    you write in the brackets — a bogus code suppresses just as well as a real
    one. So the comment reads as narrow while behaving as a blanket, and a second
    error on the same line disappears silently.

    `# pyright: ignore[reportMissingImports]` is scoped to that one rule, and
    pyright **validates the name**: get it wrong and the original error comes
    back, loudly. Use it.

### Running the tests

Host-side unit tests live in separate files next to the code they cover: Python
in each service's `tests/` directory (pytest), Rust in sibling
`#[cfg(test)] mod tests;` modules, and the Node-RED nodes under
`flow/nodes/conecsa-system-vision/test/` (jest). The one-shot runner executes
every suite:

```bash
./scripts/test.sh
```

It runs pytest for the three Python services, **pyright** across all of them,
`cargo test` for `webcam-server` and `hub-vision`, the wasm suite for
`system-vision`, and jest for the Flow nodes — generating the Python proto stubs
first if they are missing. These are the same suites CI runs on a pull request,
so a green `test.sh` is a green PR.

It uses the repo's `.venv` automatically when it exists; set `PYTHON` to override
the interpreter **pytest** runs under. Missing optional tools (`pyright`,
`wasm-pack`, `npm`) are warned about and skipped rather than failing the run.

!!! warning "`PYTHON` does not apply to pyright"
    Pyright resolves imports against the interpreter in `pyrightconfig.json`
    (`venvPath`/`venv` → `./.venv`), and that **wins over `$PYTHON`, over an
    activated virtualenv, and over `--pythonpath`**. So the type suite always
    describes `./.venv`, whatever environment you run the tests under — pointing it
    somewhere else means editing the config. If `./.venv` is missing, `test.sh`
    skips the type suite rather than let pyright fall back to another interpreter
    and report the whole dependency tree as unresolved.

```bash
PYTHON=/usr/bin/python3 ./scripts/test.sh      # override the interpreter
SKIP_TYPES=1 ./scripts/test.sh                 # unit tests only, no pyright
SKIP_WASM=1 SKIP_NODE=1 ./scripts/test.sh      # backend only
```

Granular flags: `SKIP_PYTHON`, `SKIP_TYPES`, `SKIP_RUST`, `SKIP_WASM`, `SKIP_NODE`.

To run a single suite directly:

```bash
# Python — needs the generated proto stubs (run ./scripts/compile-proto.sh once);
# tests/conftest.py adds api-gateway/gateway/proto to sys.path. Run from the service directory.
source .venv/bin/activate
cd inference-service && pytest        # or training-service / api-gateway

# Types (from the repo root — see "Type checking" above)
pyright

# Rust (native)
cargo test --manifest-path webcam-server/Cargo.toml
cargo test --manifest-path hub-vision/Cargo.toml

# Node-RED nodes
cd flow/nodes/conecsa-system-vision && npm install && npm test
```

The **`system-vision`** frontend is `wasm32`-only, so its tests run in a headless
browser via [`wasm-pack`](https://rustwasm.github.io/wasm-pack/)
(`cargo install wasm-pack`) plus a browser and its driver
(`firefox` + `geckodriver`, or `--chrome`):

```bash
wasm-pack test --headless --firefox system-vision
```

!!! note "CI runs the same suites on pull requests"
    `.github/workflows/test.yml` runs the pytest, pyright, Rust and Node suites on
    every pull request (four parallel jobs).

    The pytest job installs a focused test-dependency set — the GPU stack is never
    imported by the host tests, so it stays fast without the device wheels. The
    pyright job deliberately installs a **superset** of it: an uninstalled package
    turns every symbol from it into `Unknown` and weakens the check in silence
    instead of failing, so the type job needs the *imports* of every analyzed file.
    It pulls `torch` from the CPU-only index (the default PyPI wheel drags in a
    ~2.5GB CUDA runtime a type check has no use for) and installs into `.venv` at
    the repo root, because `pyrightconfig.json` points `venvPath`/`venv` there and
    that setting wins over a `--pythonpath` on the command line.

## Fleet hub (`hub-vision`, optional)

The [`hub-vision`](services/hub-vision.md) fleet hub is a native desktop app that
runs **off** the Jetson (on a hub machine on the same LAN) and is **independent
of the compose stack**. It reuses the Rust + Trunk toolchain from the
[prerequisites](#rust) above, plus the Tauri CLI (`cargo install tauri-cli`) and
its [system dependencies](https://tauri.app/start/prerequisites/).

```bash
# From the repo root — Tailwind CSS, Trunk WASM webview, then `cargo tauri build`
# (bundle under target/release/bundle/).
bash scripts/build-hub.sh                        # SQLite + PostgreSQL backends
HUB_FEATURES=mssql bash scripts/build-hub.sh     # also include SQL Server

# Dev loop (runs `trunk serve` for the webview):
cd hub-vision && cargo tauri dev
```

The hub discovers devices over mDNS and **pulls** their detections over mutual
TLS — there is no inbound ingestion port. See [Fleet hub](services/hub-vision.md)
for authentication, pairing, discovery and storage details.

## Building the documentation

The documentation site (this site) is built with MkDocs + mkdocstrings, plus
`cargo doc` for the Rust crates and a generated Protocol Buffers reference.

```bash
pip install -r docs/requirements-docs.txt
mkdocs serve -f docs/mkdocs.yml   # live preview at http://127.0.0.1:8000
# or the full site (MkDocs + cargo doc) into ./site:
scripts/build-docs.sh
```
