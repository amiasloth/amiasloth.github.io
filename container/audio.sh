#!/usr/bin/env bash
# Run the v3 audio pass (per-sentence opus) for one book in an EPHEMERAL
# container — nothing persists except the opus files + manifest written
# into the separate audio repo. Design: 00_v3_overview.md §4.
#
#   container/audio.sh kafka                    # full book
#   container/audio.sh velveteen --limit 20     # smoke test
#   container/audio.sh kafka --dry-run          # counts only
#   extra args go to tools/v3/audio3.py (--bitrate 16, --force, ...)
#
# Env overrides:
#   AUDIO_REPO   checkout of zzzpeak-audio   (default ../zzzpeak-audio)
#   VOICES_DIR   host dir for voice models   (default ~/piper-voices)
#   VOICE_DE     (default de_DE-thorsten-medium)
#   VOICE_EN     (default en_US-lessac-medium)
#   IMAGE        (default zzzpeak-audio)
#
# The image is built on first use; `podman rmi zzzpeak-audio` reclaims
# the disk when the audio pass is done. Voices are downloaded once into
# VOICES_DIR (host-owned, survives image removal). The app repo is
# mounted READ-ONLY — this pass can never touch docs/.
set -euo pipefail
cd "$(dirname "$0")/.."

BOOK="${1:?usage: container/audio.sh <book-id> [audio3.py args...]}"; shift

IMAGE="${IMAGE:-zzzpeak-audio}"
AUDIO_REPO="${AUDIO_REPO:-../zzzpeak-audio}"
VOICES_DIR="${VOICES_DIR:-$HOME/piper-voices}"
VOICE_DE="${VOICE_DE:-de_DE-thorsten-medium}"   # PINNED 2026-07-12
VOICE_EN="${VOICE_EN:-en_GB-alba-medium}"       # PINNED 2026-07-12

# built book file -> language -> voice
if   [ -f "docs/data3/de/${BOOK}.json" ]; then BLANG=de
elif [ -f "docs/data3/en/${BOOK}.json" ]; then BLANG=en
else
  echo "ERROR: no built book at docs/data3/{de,en}/${BOOK}.json" >&2
  echo "       run tools/v3/build_data3.sh first" >&2
  exit 1
fi
VOICE_VAR="VOICE_${BLANG^^}"; VOICE="${!VOICE_VAR}"

if [ ! -d "$AUDIO_REPO" ]; then
  echo "ERROR: audio repo not found at $AUDIO_REPO" >&2
  echo "       clone zzzpeak-audio there, or set AUDIO_REPO=" >&2
  exit 1
fi
mkdir -p "$VOICES_DIR"

podman image exists "$IMAGE" || podman build -t "$IMAGE" \
    -f container/Dockerfile.audio \
    --build-arg USER_UID="$(id -u)" \
    --build-arg GIT_REVISION="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
    --build-arg BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    .

# voice model: download once into the host dir (data, not image)
if [ ! -f "${VOICES_DIR}/${VOICE}.onnx" ]; then
  echo "downloading voice ${VOICE} -> ${VOICES_DIR}"
  podman run --rm --userns=keep-id \
      -v "${VOICES_DIR}:/voices" -w /voices \
      "$IMAGE" python3 -m piper.download_voices "$VOICE"
fi

exec podman run --rm --userns=keep-id \
    -v "$(pwd):/project:ro" \
    -v "$(cd "$AUDIO_REPO" && pwd):/audio" \
    -v "${VOICES_DIR}:/voices:ro" \
    -e "AUDIO3_REV=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" \
    "$IMAGE" \
    python3 /project/tools/v3/audio3.py \
      --book "/project/docs/data3/${BLANG}/${BOOK}.json" \
      --voice "/voices/${VOICE}.onnx" \
      --out /audio \
      "$@"
