#!/usr/bin/env bash
#
# test.sh — run every host-side unit-test suite in the repo.
#
# Suites:
#   1. Python (pytest)   — inference-service, training-service, api-gateway
#   2. Python (pyright)  — static types across every Python service; baseline is 0
#   3. Rust native       — webcam-server, hub-vision (`cargo test`)
#   4. Rust wasm         — system-vision (`wasm-pack test`, headless browser)
#   5. Node-RED (jest)   — flow custom nodes
#
# These are the same suites .github/workflows/test.yml runs on a pull request.
#
# Prerequisites (see docs/getting-started.md):
#   - the repo `.venv` (./scripts/init.sh). pytest runs under it (or under $PYTHON,
#     if set); the proto stubs are generated on demand below.
#   - a Rust toolchain (+ wasm32-unknown-unknown for system-vision).
#   - wasm-pack and a browser/driver (firefox+geckodriver) for the wasm suite.
#   - node + npm for the Node-RED suite.
#
# NOTE: $PYTHON does NOT apply to pyright. Pyright resolves imports against the
# interpreter named by pyrightconfig.json (venvPath/venv → ./.venv), and that wins
# over anything on the command line or in the environment — so the type suite
# always describes ./.venv, whatever env you run the tests under.
#
# Usage:
#   scripts/test.sh                     # everything available
#   SKIP_WASM=1 SKIP_NODE=1 scripts/test.sh
#   PYTHON=/usr/bin/python3 scripts/test.sh    # pytest only — see the note above
#
# Granular skips: SKIP_PYTHON, SKIP_TYPES, SKIP_RUST, SKIP_WASM, SKIP_NODE.
# Missing optional tools (pyright, wasm-pack, npm) are warned about and skipped
# rather than failing the whole run.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Default to the repo venv when it exists: without it a bare `scripts/test.sh`
# fails with "No module named pytest" unless the caller remembered to activate.
# Absolute — the pytest suites run from inside each service directory.
if [[ -z "${PYTHON:-}" && -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
fi
PYTHON="${PYTHON:-python3}"
WASM_BROWSER="${WASM_BROWSER:-firefox}"

# ── 1. Python ───────────────────────────────────────────────────────────────────
if [[ "${SKIP_PYTHON:-0}" != "1" ]]; then
  # The Tier-1/2 modules that touch proto rely on the generated Python stubs
  # under api-gateway/gateway/proto (gitignored). Generate them if absent.
  if [[ ! -f "api-gateway/gateway/proto/inference_pb2.py" ]]; then
    echo "==> Generating Python proto stubs"
    scripts/compile-proto.sh
  fi

  for svc in inference-service training-service api-gateway; do
    echo "==> pytest: $svc"
    ( cd "$svc" && "$PYTHON" -m pytest -q )
  done
fi

# ── 2. Python (pyright) ─────────────────────────────────────────────────────────
if [[ "${SKIP_TYPES:-0}" != "1" ]]; then
  # Everything pyright needs is in pyrightconfig.json (venv, extraPaths, exclusions).
  # It resolves imports against the venv named THERE — ./.venv — regardless of
  # $PYTHON, of an activated virtualenv, or of which pyright binary we invoke. So
  # this suite always type-checks against ./.venv; there is no way to point it at
  # another environment from here without editing the config.
  PYRIGHT="${PYRIGHT:-}"
  if [[ -z "$PYRIGHT" ]]; then
    if [[ -x ".venv/bin/pyright" ]]; then
      PYRIGHT=".venv/bin/pyright"
    elif command -v pyright >/dev/null 2>&1; then
      PYRIGHT="pyright"
    fi
  fi

  if [[ -z "$PYRIGHT" ]]; then
    echo "!! pyright not found — skipping type check"
    echo "   (install: ./scripts/init.sh, or pip install -r requirements-dev.txt)"
  elif [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
    # Without it, pyright silently falls back to some other interpreter and reports
    # the whole dependency tree as unresolved — errors that look like code defects
    # but are really "you have no .venv".
    echo "!! .venv is missing — skipping type check"
    echo "   pyrightconfig.json resolves imports against ./.venv (not \$PYTHON)."
    echo "   Create it with ./scripts/init.sh, then re-run."
  else
    echo "==> pyright: Python services"
    "$PYRIGHT"
  fi
fi

# ── 3. Rust (native) ────────────────────────────────────────────────────────────
if [[ "${SKIP_RUST:-0}" != "1" ]]; then
  echo "==> cargo test: webcam-server"
  cargo test --manifest-path webcam-server/Cargo.toml

  # hub-vision lives only in the private monorepo; the public mirror exported by
  # scripts/export-mirror.sh ships this same test.sh without the crate.
  if [[ -f hub-vision/Cargo.toml ]]; then
    echo "==> cargo test: hub-vision"
    cargo test --manifest-path hub-vision/Cargo.toml
  else
    echo "!! hub-vision not present in this checkout — skipping its suite"
  fi
fi

# ── 4. Rust (wasm, system-vision) ───────────────────────────────────────────────
if [[ "${SKIP_WASM:-0}" != "1" ]]; then
  if command -v wasm-pack >/dev/null 2>&1; then
    echo "==> wasm-pack test: system-vision (headless $WASM_BROWSER)"
    wasm-pack test --headless "--$WASM_BROWSER" system-vision
  else
    echo "!! wasm-pack not found — skipping system-vision wasm tests"
    echo "   (install: cargo install wasm-pack; needs a browser + driver)"
  fi
fi

# ── 5. Node-RED (flow) ──────────────────────────────────────────────────────────
if [[ "${SKIP_NODE:-0}" != "1" ]]; then
  if command -v npm >/dev/null 2>&1; then
    FLOW_DIR="flow/nodes/conecsa-system-vision"
    echo "==> jest: $FLOW_DIR"
    (
      cd "$FLOW_DIR"
      [[ -d node_modules ]] || npm install --no-audit --no-fund
      npm test
    )
  else
    echo "!! npm not found — skipping Node-RED node tests"
  fi
fi

echo ""
echo "All selected test suites passed."
