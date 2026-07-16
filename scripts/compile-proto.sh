#!/bin/bash

# Script to compile Protocol Buffers for both Rust and Python
# All .proto files live in the root proto/ directory.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "==================================="
echo "Compiling Protocol Buffers"
echo "==================================="

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

PROTO_DIR="proto"
# Local-dev output: the api-gateway is the HTTP service you run off-device
# (`python api-gateway/main.py`), and it imports every proto (inference /
# hardware / training / detection). Its gateway/proto dir is gitignored — these
# stubs are regenerated here locally and inside Dockerfile.api-gateway at build.
# (inference-service generates its own stubs in its Dockerfile.)
PYTHON_OUT="api-gateway/gateway/proto"

# Check if proto directory exists
if [ ! -d "$PROTO_DIR" ]; then
    echo -e "${RED}Error: Proto directory not found: $PROTO_DIR${NC}"
    exit 1
fi

echo -e "${BLUE}Proto directory: $PROTO_DIR${NC}"

# ===========================
# Compile for Python
# ===========================
echo ""
echo -e "${GREEN}[1/2] Compiling protobuf for Python...${NC}"

# Check that grpcio-tools (grpc_tools.protoc) is available — it bundles protoc
# and the gRPC Python plugin used for --grpc_python_out.
if ! python3 -c "import grpc_tools.protoc" &> /dev/null; then
    echo -e "${RED}Error: grpc_tools.protoc not found (grpcio-tools).${NC}"
    echo "Install it:  pip install grpcio-tools"
    echo "(it ships in os-base/requirements-common.txt and requirements-dev.txt)"
    exit 1
fi

mkdir -p "$PYTHON_OUT"

# Compile all .proto files for Python (message + gRPC service stubs).
# `--pyi_out` emits a sibling .pyi stub so static analyzers (Pyright,
# PyCharm) can resolve the dynamically-built message classes that the
# runtime .py adds via `_builder.BuildTopDescriptorsAndMessages`.
# `--grpc_python_out` emits the *_pb2_grpc.py service stubs the gateway imports
# (inference_pb2_grpc, hardware_pb2_grpc, training_pb2_grpc).
for proto_file in "$PROTO_DIR"/*.proto; do
    echo -e "${BLUE}  Compiling $(basename "$proto_file")...${NC}"
    python3 -m grpc_tools.protoc \
        -I"$PROTO_DIR" \
        --python_out="$PYTHON_OUT" \
        --pyi_out="$PYTHON_OUT" \
        --grpc_python_out="$PYTHON_OUT" \
        "$proto_file"
done

# Ensure __init__.py exists
touch "$PYTHON_OUT/__init__.py"

echo -e "${GREEN}✓ Python protobuf compiled successfully${NC}"
echo "  Generated files in: $PYTHON_OUT/"

# ===========================
# Compile for Rust
# ===========================
echo ""
echo -e "${GREEN}[2/2] Compiling protobuf for Rust...${NC}"

# Rust protobuf compilation is handled by build.rs during cargo build
# Trigger it by building the relevant crates
echo -e "${BLUE}Running cargo build to trigger build.rs...${NC}"

# Build webcam-server (compiles shm.proto)
cargo build --manifest-path webcam-server/Cargo.toml 2>&1 | grep -v "warning:" || true

# Build system-vision (compiles detection.proto) — only if the manifest exists
if [ -f "system-vision/Cargo.toml" ]; then
    cargo build --manifest-path system-vision/Cargo.toml 2>&1 | grep -v "warning:" || true
fi

echo -e "${GREEN}✓ Rust protobuf compiled successfully${NC}"

# ===========================
# Summary
# ===========================
echo ""
echo -e "${GREEN}==================================="
echo "Protobuf compilation completed!"
echo "===================================${NC}"
echo ""
echo "Proto source:    $PROTO_DIR/"
echo "Python output:   $PYTHON_OUT/"
echo "Rust output:     handled by build.rs (prost)"
echo ""
