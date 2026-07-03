#!/usr/bin/env bash
# Regenerate alleycatv_pb2.py from alleycatv.proto and copy to all consumers.
# Run this any time alleycatv.proto changes.
#
# Requires protoc (Protocol Buffer Compiler):
#   Option A: apt install protobuf-compiler
#   Option B: pip install grpcio-tools  (then use python -m grpc_tools.protoc)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v protoc &>/dev/null; then
    echo "Using system protoc..."
    protoc --python_out=. alleycatv.proto
elif python3 -c "import grpc_tools" &>/dev/null; then
    echo "Using grpc_tools.protoc..."
    python3 -m grpc_tools.protoc -I. --python_out=. alleycatv.proto
else
    echo "ERROR: protoc not found. Install with:"
    echo "  apt install protobuf-compiler"
    echo "  OR: pip install grpcio-tools"
    exit 1
fi

echo "Generated alleycatv_pb2.py"

# Copy to all consumers
cp alleycatv_pb2.py ../ha_integration/custom_components/alleycatv/alleycatv_pb2.py
cp alleycatv_pb2.py ../client/alleycatv_player/alleycatv_pb2.py

echo "Copied to:"
echo "  ha_integration/custom_components/alleycatv/alleycatv_pb2.py"
echo "  client/alleycatv_player/alleycatv_pb2.py"
