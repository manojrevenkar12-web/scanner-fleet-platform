#!/usr/bin/env sh
# Regenerate the Python code for the telemetry contract.
set -e
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -Isrc --python_out=src src/sfp/proto/telemetry.proto
