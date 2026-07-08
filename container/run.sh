#!/usr/bin/env bash
# Run the zzzpeak dev container (rootless podman).
#
#   container/run.sh              interactive shell, repo mounted at /project
#   container/run.sh claude       same, but launches Claude Code directly
#
# --userns=keep-id maps the container's uid 1000 back to your host uid, so
# files the container writes into the bind-mounted repo stay host-owned.
# Publishes 8080 for previewing docs/ — inside the container run `serve-docs`
# (a bashrc helper: python3 -m http.server 8080 in docs/), then open
# http://localhost:8080 on the host. localhost counts as a secure context,
# so mic capture + the service worker work without HTTPS.
#
# Optional env vars, forwarded if set: CLAUDE_CODE_OAUTH_TOKEN, GH_TOKEN.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-zzzpeak-dev}"
TAG="${TAG:-latest}"
PORT="${PORT:-8080}"

ENV_ARGS=()
[ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && ENV_ARGS+=(-e "CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}")
[ -n "${GH_TOKEN:-}" ] && ENV_ARGS+=(-e "GH_TOKEN=${GH_TOKEN}")

exec podman run -it --rm \
    --userns=keep-id \
    -v "$(pwd):/project" \
    -p "${PORT}:8080" \
    "${ENV_ARGS[@]}" \
    "${IMAGE}:${TAG}" \
    "${@:-bash}"
