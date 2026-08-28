#!/usr/bin/env bash
# Download Windows x64 Python 3.12 wheels into windows-deploy/wheels/
# Run on Mac/Linux when requirements.txt changes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/windows-deploy/wheels"
mkdir -p "$DEST"
echo "Downloading Windows wheels -> $DEST"
python3 -m pip download \
  -r "$ROOT/requirements.txt" \
  -d "$DEST" \
  --platform win_amd64 \
  --python-version 312 \
  --implementation cp \
  --abi cp312 \
  --only-binary=:all:
echo "Done. Size:"
du -sh "$DEST"
