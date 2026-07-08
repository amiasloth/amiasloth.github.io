#!/usr/bin/env bash
# Build the zzzpeak dev container image with rootless podman.
# Run from anywhere; always builds with the repo root as context so
# tools/requirements.txt is reachable from container/Dockerfile.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-zzzpeak-dev}"
TAG="${TAG:-latest}"

podman build \
    -t "${IMAGE}:${TAG}" \
    -f container/Dockerfile \
    --build-arg USER_UID="$(id -u)" \
    --build-arg GIT_REVISION="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
    --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    .

echo "built ${IMAGE}:${TAG} -> run it with: container/run.sh"
