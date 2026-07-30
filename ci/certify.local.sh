#!/usr/bin/env bash
# Per-repo certify override for ai-trading-common (the shared library) — picked up
# automatically by $WS/tools/certify/certify.sh because this file exists + is executable.
#
# WHY this file exists:
#   ai-trading-common is a pure-python package (no runtime Dockerfile / service
#   layout), so certify-run.sh's generic stack detection reports "no test stack".
#   The library ships its own tests and declares a [test] extra, so the correct
#   path is a flat python image: editable-install with test extras and run pytest.
#
# PERFORMANCE NOTE: mount the host pip cache so every run after the first is a
#   no-op install (immutable content-addressed blobs; concurrent readers safe).
#
# Prerequisites: Docker daemon running; no external services needed.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

DOCKER_BIN="${DOCKER_BIN:-docker}"
PY_IMG="${CERTIFY_IMAGE_PY:-python:3.12-slim}"

echo "  stack: python ($PY_IMG, editable install + pip cache — pure library)"

$DOCKER_BIN run --rm --platform linux/amd64 \
  -e TESTING=true -e CI=true \
  -v "$(pwd)":/app \
  -v "${HOME}/.cache/pip":/root/.cache/pip \
  -w /app \
  "$PY_IMG" bash -lc "
    set -euo pipefail
    pip install -q -e '.[test]' >/dev/null 2>&1
    python -m pytest -q --tb=short
  "
