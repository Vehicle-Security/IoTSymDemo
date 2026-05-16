#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$ROOT_DIR/src-demo"
FW_DIR="$ROOT_DIR/firmware"

mkdir -p "$SRC_DIR/out" "$SRC_DIR/traces"

gcc -Wall -Wextra -O0 -g \
  "$FW_DIR/miniiot.c" \
  -o "$SRC_DIR/out/miniiot_original"

gcc -Wall -Wextra -O0 -g \
  -I "$SRC_DIR" \
  "$SRC_DIR/miniiot_instrumented.c" \
  "$SRC_DIR/sym_iot.c" \
  -o "$SRC_DIR/out/miniiot_instrumented"

echo "[OK] built:"
echo "  $SRC_DIR/out/miniiot_original"
echo "  $SRC_DIR/out/miniiot_instrumented"
