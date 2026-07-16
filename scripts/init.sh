#!/bin/bash
#
# init.sh — one-time local development environment bootstrap.
#
# Provisions the single root virtualenv (.venv) with a TensorRT-compatible
# Python (3.10–3.12), installs the aggregated dev dependencies (including the
# hardware agent's, which otherwise only exist inside the os image), compiles the
# protobuf stubs, and warms up pyright — so the services, the editor and
# scripts/test.sh all resolve everything with no follow-up step. Prefers `uv`
# (which can auto-provision Python 3.10) and falls back to the system `python3`.
#
#   ./scripts/init.sh          # base dev deps (gateway, control-plane, docs, types)
#   ./scripts/init.sh --gpu    # also install the local GPU stack (TensorRT/PyCUDA)
#
# After this, run:  source .venv/bin/activate && ./scripts/dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${BLUE}$*${NC}"; }
ok()    { echo -e "${GREEN}$*${NC}"; }
warn()  { echo -e "${YELLOW}$*${NC}"; }
err()   { echo -e "${RED}$*${NC}" >&2; }

INSTALL_GPU=0

usage() {
    cat <<'EOF'
Usage: ./scripts/init.sh [--gpu] [--help]

  --gpu     Also install the local GPU stack (tensorrt-cu12 + pycuda) for running
            inference/training off-device. Requires an NVIDIA GPU and a local
            CUDA 12.x toolkit (see docs/getting-started.md).
  --help    Show this help.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --gpu)  INSTALL_GPU=1 ;;
        --help|-h) usage; exit 0 ;;
        *) err "Unknown argument: $1"; usage; exit 1 ;;
    esac
    shift
done

VENV="$PROJECT_ROOT/.venv"
USE_UV=0

# ---------------------------------------------------------------------------
# 1. Provision the virtualenv
# ---------------------------------------------------------------------------
echo "==================================="
info "Bootstrapping local dev environment"
echo "==================================="

# Reuse an existing venv rather than recreating it — re-running init.sh to pick
# up new dependencies must not throw away an environment someone is working in.
# (`uv venv` would silently recreate it, which is what this guard prevents.)
if [ -x "$VENV/bin/python" ]; then
    EXISTING_VER="$("$VENV/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")"
    warn "[1/5] Virtualenv already exists at .venv (Python $EXISTING_VER) — reusing it."
    warn "      Delete it and re-run to recreate from scratch."
    case "$EXISTING_VER" in
        3.10|3.11|3.12) ;;
        *)
            warn "      Note: Python $EXISTING_VER is outside the supported 3.10–3.12 range."
            warn "      NVIDIA publishes TensorRT/PyCUDA wheels only for CPython 3.8–3.12,"
            warn "      so --gpu will fail on it. Everything else works."
            ;;
    esac
    if command -v uv >/dev/null 2>&1; then
        USE_UV=1
    fi
elif command -v uv >/dev/null 2>&1; then
    USE_UV=1
    info "[1/5] Creating virtualenv with uv (Python 3.10)..."
    uv venv --python 3.10 "$VENV"
else
    info "[1/5] uv not found — using system python3 + venv."
    # Find an interpreter in the supported 3.10–3.12 range.
    PYBIN=""
    for cand in python3.12 python3.11 python3.10 python3; do
        if command -v "$cand" >/dev/null 2>&1; then
            ver="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
            case "$ver" in
                3.10|3.11|3.12) PYBIN="$cand"; break ;;
            esac
        fi
    done
    if [ -z "$PYBIN" ]; then
        err "No Python 3.10–3.12 interpreter found."
        err "NVIDIA only publishes TensorRT/PyCUDA wheels for CPython 3.8–3.12."
        err "Install uv (https://docs.astral.sh/uv/) — it can provision 3.10:"
        err "    uv python install 3.10 && ./scripts/init.sh"
        exit 1
    fi
    info "    Using $PYBIN ($("$PYBIN" --version 2>&1))"
    "$PYBIN" -m venv "$VENV"
fi

# ---------------------------------------------------------------------------
# 2. Install dependencies into the venv
# ---------------------------------------------------------------------------
# shellcheck disable=SC1091
source "$VENV/bin/activate"

pip_install() {
    if [ "$USE_UV" -eq 1 ]; then
        uv pip install "$@"
    else
        pip install "$@"
    fi
}

info "[2/5] Installing base dev dependencies (requirements-dev.txt)..."
if [ "$USE_UV" -eq 0 ]; then
    pip install --upgrade pip >/dev/null
fi
pip_install -r requirements-dev.txt

if [ "$INSTALL_GPU" -eq 1 ]; then
    info "[2b] Installing local GPU stack (tensorrt-cu12 + pycuda)..."
    warn "    Requires an NVIDIA GPU + local CUDA 12.x toolkit (see docs/getting-started.md)."
    # Keep parity with the dev container (os-base/Dockerfile.os-base.dev): pin versions and
    # force numpy back to 1.26.4 for the pycuda/tensorrt ABI.
    # TensorRT wheels are large; if /tmp is small, point TMPDIR elsewhere, e.g.:
    #   TMPDIR="$HOME/.tmp" ./scripts/init.sh --gpu
    pip_install tensorrt-cu12==10.3.0 pycuda==2024.1 onnx==1.22.0
    pip_install --force-reinstall numpy==1.26.4
fi

# Make the shared `conecsa_shm` package (os-base/conecsa_shm) importable from the
# venv. In the images os-base/Dockerfile.os-base copies it into dist-packages;
# locally we add os-base/ to the venv's path via a .pth so `import conecsa_shm`
# resolves for the gateway/inference/training services (and the documented manual
# commands).
info "    Linking shared conecsa_shm package into the venv..."
SITE_PACKAGES="$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
echo "$PROJECT_ROOT/os-base" > "$SITE_PACKAGES/conecsa_os.pth"

# ---------------------------------------------------------------------------
# 3. Compile protobuf stubs (re-uses the existing script)
# ---------------------------------------------------------------------------
info "[3/5] Compiling protobuf stubs..."
bash "$SCRIPT_DIR/compile-proto.sh"

# ---------------------------------------------------------------------------
# 4. Warm up pyright
# ---------------------------------------------------------------------------
# The pyright pip package is a thin wrapper: on its first run it downloads a
# private Node runtime (via nodeenv). Doing that here — rather than the first
# time someone runs `pyright` or `scripts/test.sh` — keeps the surprise (a
# multi-second network fetch) inside the bootstrap step where it belongs.
info "[4/5] Warming up pyright (downloads its bundled Node on first run)..."
if pyright --version >/dev/null 2>&1; then
    ok "    $(pyright --version 2>/dev/null | head -1)"
else
    warn "    pyright could not start — run 'pyright' manually to see why."
fi

# ---------------------------------------------------------------------------
# 5. Check the Rust toolchain for the frontend (warn-only)
# ---------------------------------------------------------------------------
info "[5/5] Checking Rust/Trunk toolchain (frontend)..."
RUST_OK=1
if ! command -v cargo >/dev/null 2>&1; then
    warn "    cargo not found — install Rust via rustup (see docs/getting-started.md)."
    RUST_OK=0
fi
if ! command -v trunk >/dev/null 2>&1; then
    warn "    trunk not found — install with: cargo install trunk"
    RUST_OK=0
fi
if command -v rustup >/dev/null 2>&1; then
    if ! rustup target list --installed 2>/dev/null | grep -q wasm32-unknown-unknown; then
        warn "    wasm32 target missing — add it: rustup target add wasm32-unknown-unknown"
        RUST_OK=0
    fi
fi
[ "$RUST_OK" -eq 1 ] && ok "    Rust toolchain looks good."

echo ""
echo -e "${GREEN}==================================="
echo "Environment ready!"
echo -e "===================================${NC}"
echo ""
echo "Next steps:"
echo "    source .venv/bin/activate"
echo "    ./scripts/dev.sh                 # start the full stack"
echo "    ./scripts/dev.sh --no-inference --no-training   # frontend + gateway only (no GPU)"
echo ""
echo "Before opening a PR (same suites CI runs):"
echo "    ./scripts/test.sh                # unit tests + pyright"
echo "    pyright                          # type check only (reads pyrightconfig.json)"
echo ""
