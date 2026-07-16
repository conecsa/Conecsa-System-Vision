#!/usr/bin/env bash
#
# build-docs.sh — build the full documentation site into ./site
#
# Steps:
#   1. mkdocs build (Material theme + mkdocstrings Python API + generated proto
#      reference). Uses --strict so broken links / missing nav fail the build.
#   2. cargo doc for the Rust workspace (app + webcam-server), with private
#      items, and overlay it under site/rust/ so it is reachable from the nav.
#
# Prerequisites:
#   pip install -r docs/requirements-docs.txt
#   a Rust toolchain (rustup) with the wasm32-unknown-unknown target for the app
#
# Usage:
#   scripts/build-docs.sh           # full build
#   SKIP_RUST=1 scripts/build-docs.sh   # docs only, skip cargo doc
#
set -euo pipefail

# Silence the third-party "MkDocs 2.0 / switch to <other tool>" advert that some
# packages inject into the build output. We intentionally stay on mkdocs +
# mkdocs-material.
export DISABLE_MKDOCS_2_WARNING=true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "==> Building MkDocs site (strict)"
mkdocs build --strict -f docs/mkdocs.yml

if [[ "${SKIP_RUST:-0}" == "1" ]]; then
  echo "==> SKIP_RUST=1 set — skipping cargo doc"
  echo "Done. Site in ./site"
  exit 0
fi

mkdir -p site/rust

# system-vision: document the wasm32 target — that is the deployed frontend, and it
# avoids the Tauri/GTK (glib-2.0) native system deps that a host-target doc build
# would require. Needs the wasm32-unknown-unknown target installed.
echo "==> Building Rust API docs: system-vision (wasm32)"
cargo doc --no-deps --document-private-items --manifest-path system-vision/Cargo.toml \
  --target wasm32-unknown-unknown
cp -a system-vision/target/wasm32-unknown-unknown/doc/. site/rust/

# webcam-server: a standalone workspace (see its Cargo.toml), documented from its
# own manifest. Needs the v4l/udev system libs.
echo "==> Building Rust API docs: webcam-server (native)"
cargo doc --no-deps --document-private-items --manifest-path webcam-server/Cargo.toml
cp -a webcam-server/target/doc/. site/rust/

echo "Done. Site in ./site (open site/index.html; Rust docs under site/rust/)"
