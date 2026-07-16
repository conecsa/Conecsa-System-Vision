#!/bin/bash
#
# build.sh — production build of the web frontend.
#
# Downloads the Tailwind CLI if missing, builds minified CSS, compiles every
# Protocol Buffer (scripts/compile-proto.sh), then builds the Leptos/WASM app
# in release mode with Trunk into ../dist. This is the static bundle Nginx
# serves in the web deployment.

# Resolve the project root (one level above the scripts/ directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Add Cargo bin to PATH so tools like trunk are available
export PATH="$HOME/.cargo/bin:$PATH"

cd "$PROJECT_ROOT"

# Build CSS with Tailwind
echo "Building CSS..."
TAILWIND_BIN="$PROJECT_ROOT/bin/tailwindcss"
if [ ! -f "$TAILWIND_BIN" ]; then
    echo "Tailwind binary not found, downloading..."
    mkdir -p "$PROJECT_ROOT/bin"
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  TAILWIND_ASSET="tailwindcss-linux-x64" ;;
        aarch64) TAILWIND_ASSET="tailwindcss-linux-arm64" ;;
        *)       echo "Unsupported architecture: $ARCH"; exit 1 ;;
    esac
    curl -fsSL -o "$TAILWIND_BIN" \
        "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/${TAILWIND_ASSET}"
    chmod +x "$TAILWIND_BIN"
fi
"$TAILWIND_BIN" -i ./styles/input.css -o ./system-vision/styles.css --minify

# Compile protobuf files
echo "Compiling protobuf files..."
"$SCRIPT_DIR/compile-proto.sh"

# Build Rust/WASM with Trunk
echo "Building Rust application..."
cd "$PROJECT_ROOT/app" && trunk build --release --dist ../dist
