#!/usr/bin/env bash
# Run it on the homelab host
cd "$(dirname "$0")"
caddy run --config Caddyfile
