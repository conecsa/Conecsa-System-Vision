#!/bin/bash
#
# dev.sh — local full-stack dev launcher.
#
# Starts the whole stack for development as background jobs with prefixed,
# interleaved logs, and tears everything down on Ctrl+C (single trap):
#
#   webcam-server   (Rust)      POSIX SHM producer (conecsa_frame_shm), no port
#   inference-service (Python)  gRPC :50061, reads frames / writes processed SHM
#   training-service  (Python)  gRPC :50071
#   api-gateway     (Python)    HTTP API :5000 (the only HTTP surface)
#   system-vision   (WASM)      Tailwind watch + trunk serve on :18080
#
# All services start by default; use flags to skip the GPU-heavy ones on a
# machine without the TensorRT/PyCUDA stack:
#
#   ./scripts/dev.sh                          # everything
#   ./scripts/dev.sh --no-inference --no-training   # frontend + gateway only
#   ./scripts/dev.sh --gateway-only           # gateway + frontend, no webcam/GPU
#
# Run ./scripts/init.sh first to create the .venv and compile the protos.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PATH="$HOME/.cargo/bin:$PATH"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Arg parsing — default is "start everything".
# ---------------------------------------------------------------------------
RUN_WEBCAM=1
RUN_INFERENCE=1
RUN_TRAINING=1
RUN_APP=1

usage() {
    cat <<'EOF'
Usage: ./scripts/dev.sh [options]

  --no-webcam      Don't start webcam-server.
  --no-inference   Don't start inference-service (GPU stack).
  --no-training    Don't start training-service (GPU stack).
  --no-app         Don't start the web frontend (Tailwind + trunk).
  --gateway-only   Only api-gateway + frontend (implies --no-webcam
                   --no-inference --no-training).
  --help           Show this help.

The api-gateway always starts (it is the core HTTP surface).
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-webcam)    RUN_WEBCAM=0 ;;
        --no-inference) RUN_INFERENCE=0 ;;
        --no-training)  RUN_TRAINING=0 ;;
        --no-app)       RUN_APP=0 ;;
        --gateway-only) RUN_WEBCAM=0; RUN_INFERENCE=0; RUN_TRAINING=0 ;;
        --help|-h)      usage; exit 0 ;;
        *) echo -e "${RED}Unknown argument: $1${NC}" >&2; usage; exit 1 ;;
    esac
    shift
done

# ---------------------------------------------------------------------------
# venv guard — activate the root .venv if it isn't already active.
# ---------------------------------------------------------------------------
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
        # shellcheck disable=SC1091
        source "$PROJECT_ROOT/.venv/bin/activate"
    else
        echo -e "${RED}No .venv found.${NC} Run ./scripts/init.sh first." >&2
        exit 1
    fi
fi

# The Python services import the shared `conecsa_shm` package (os-base/conecsa_shm),
# which the images copy into dist-packages. Locally, put os-base/ on the path so the
# gateway/inference/training imports resolve regardless of the .pth init.sh adds.
export PYTHONPATH="$PROJECT_ROOT/os-base${PYTHONPATH:+:$PYTHONPATH}"

# The service configs default to Docker service hostnames (inference-service:50061,
# …). For local dev point the peers at localhost (override-able from the env).
export INFERENCE_GRPC_ADDR="${INFERENCE_GRPC_ADDR:-localhost:50061}"
export TRAINING_GRPC_ADDR="${TRAINING_GRPC_ADDR:-localhost:50071}"
export HARDWARE_AGENT_ADDR="${HARDWARE_AGENT_ADDR:-localhost:50051}"
export GATEWAY_ADDR="${GATEWAY_ADDR:-http://localhost:5000}"

# ---------------------------------------------------------------------------
# Process management — track each service's PID and, on exit, tear down each one
# together with its descendants (cargo's spawned binary, trunk's build procs,
# …). SIGTERM first, then SIGKILL any survivors after a short grace period
# (waitress/the gateway doesn't always stop promptly on SIGTERM alone). We kill
# specific subtrees rather than `kill 0` so the script stays alive long enough
# to escalate to SIGKILL.
# ---------------------------------------------------------------------------
PIDS=()

kill_tree() {
    local pid="$1" sig="$2" child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        kill_tree "$child" "$sig"
    done
    kill "-$sig" "$pid" 2>/dev/null
}

cleanup() {
    trap - INT TERM EXIT
    echo -e "\n${YELLOW}Shutting down...${NC}"
    for pid in "${PIDS[@]}"; do kill_tree "$pid" TERM; done
    sleep 2
    for pid in "${PIDS[@]}"; do kill_tree "$pid" KILL; done
}
trap cleanup INT TERM EXIT

# run_svc NAME COLOR CMD...  — launch CMD as a background job, tagging each of
# its output lines with a colored [NAME] prefix (line-buffered via stdbuf), and
# record its PID for cleanup.
run_svc() {
    local name="$1"; local color="$2"; shift 2
    echo -e "${color}▶ starting ${name}${NC}"
    local tag
    tag="$(printf '%b' "${color}")[${name}]$(printf '%b' "${NC}") "
    "$@" > >(stdbuf -oL sed "s/^/${tag}/") 2>&1 &
    PIDS+=($!)
}

# ---------------------------------------------------------------------------
# Frontend prerequisite: Tailwind CLI (downloaded on first run).
# ---------------------------------------------------------------------------
if [ "$RUN_APP" -eq 1 ]; then
    TAILWIND_BIN="$PROJECT_ROOT/bin/tailwindcss"
    if [ ! -f "$TAILWIND_BIN" ]; then
        echo "Tailwind binary not found, downloading..."
        mkdir -p "$PROJECT_ROOT/bin"
        ARCH=$(uname -m)
        case "$ARCH" in
            x86_64)  TAILWIND_ASSET="tailwindcss-linux-x64" ;;
            aarch64) TAILWIND_ASSET="tailwindcss-linux-arm64" ;;
            *)       echo -e "${RED}Unsupported architecture: $ARCH${NC}"; exit 1 ;;
        esac
        curl -fsSL -o "$TAILWIND_BIN" \
            "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/${TAILWIND_ASSET}"
        chmod +x "$TAILWIND_BIN"
    fi
fi

# ---------------------------------------------------------------------------
# Start services. Order matters: webcam-server produces the SHM ring that
# inference/training consume, so it goes first. (Consumers self-reconnect, so a
# strict barrier isn't required — a short head start is enough.)
# ---------------------------------------------------------------------------
if [ "$RUN_WEBCAM" -eq 1 ]; then
    run_svc "webcam" "$BLUE" \
        cargo run --release --manifest-path "$PROJECT_ROOT/webcam-server/Cargo.toml"
    sleep 1
fi

if [ "$RUN_INFERENCE" -eq 1 ]; then
    run_svc "inference" "$GREEN" \
        bash -c "cd '$PROJECT_ROOT/inference-service' && exec python3 -m main"
fi

if [ "$RUN_TRAINING" -eq 1 ]; then
    run_svc "training" "$YELLOW" \
        bash -c "cd '$PROJECT_ROOT/training-service' && exec python3 -m main"
fi

# api-gateway always runs — it's the HTTP surface the frontend talks to.
run_svc "gateway" "$BLUE" \
    python3 "$PROJECT_ROOT/api-gateway/main.py"

if [ "$RUN_APP" -eq 1 ]; then
    # Tailwind watch: shared input styles/input.css → system-vision/styles.css
    # (the file index.html loads). Trunk serve proxies /api to the gateway :5000.
    run_svc "tailwind" "$YELLOW" \
        "$PROJECT_ROOT/bin/tailwindcss" \
        -i "$PROJECT_ROOT/styles/input.css" -o "$PROJECT_ROOT/system-vision/styles.css" --watch
    run_svc "system-vision" "$GREEN" \
        bash -c "cd '$PROJECT_ROOT/system-vision' && exec trunk serve --proxy-rewrite=/api --proxy-backend=http://localhost:5000 --port=18080"
fi

# ---------------------------------------------------------------------------
# Banner + block until interrupted.
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}=== conecsa dev stack running ===${NC}"
echo "  api-gateway   http://localhost:5000   (HTTP API)"
[ "$RUN_APP" -eq 1 ]       && echo "  web frontend  http://localhost:18080  (trunk dev server)"
[ "$RUN_INFERENCE" -eq 1 ] && echo "  inference     grpc://localhost:50061"
[ "$RUN_TRAINING" -eq 1 ]  && echo "  training      grpc://localhost:50071"
[ "$RUN_WEBCAM" -eq 1 ]    && echo "  webcam-server SHM producer (conecsa_frame_shm)"
echo -e "${YELLOW}Press Ctrl+C to stop everything.${NC}"
echo ""

# Wait on all children; Ctrl+C triggers the trap above.
wait
