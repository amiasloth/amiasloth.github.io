#!/usr/bin/env bash
# Run the v3 audio pass (per-sentence opus) for one book in an EPHEMERAL
# container — nothing persists except the opus files + manifest written
# into the separate audio repo. Design: 00_v3_overview.md §4.
#
#   container/audio.sh kafka                    # full book
#   container/audio.sh velveteen --limit 20     # smoke test
#   container/audio.sh kafka --dry-run          # section table + counts
#   container/audio.sh kafka --sections 1       # one chapter per run
#   extra args go to tools/v3/audio3.py (--bitrate 16, --force, ...)
#
# Env overrides:
#   AUDIO_REPO   checkout of zzzpeak-audio   (default ../zzzpeak-audio)
#   VOICES_DIR   host dir for voice models   (default ~/piper-voices)
#   VOICE_DE     (default de_DE-thorsten-medium)
#   VOICE_EN     (default en_GB-alba-medium)
#   IMAGE        (default zzzpeak-audio)
#
# The image is built on first use; `podman rmi zzzpeak-audio` reclaims
# the disk when the audio pass is done. Voices are downloaded once into
# VOICES_DIR (host-owned, survives image removal), then PATCHED once in
# place: stock rhasspy/piper-voices .onnx files export only the audio
# tensor, so `include_alignments=True` yields nothing (timing.json ends
# up empty — observed 2026-07-12). piper ships the fix:
# `python3 -m piper.patch_voice_with_alignment` exposes the duration
# ("Ceil") tensor as a second graph output. The app repo is mounted
# READ-ONLY — this pass can never touch docs/.
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

# alignment patch: run-timing (timing.json) needs the voice to emit the
# per-phoneme duration tensor; patch once, in place. Idempotent — skips
# when the model already has the second output. Voices dir mounted rw
# ONLY here; the synth run below keeps it ro.
# NB the -i is load-bearing: the script arrives on stdin, and without it
# podman closes stdin and `python3 -` runs an EMPTY script, exit 0 —
# exactly the silent no-op that shipped unpatched voices on 2026-07-12.
podman run --rm -i --userns=keep-id \
    -v "${VOICES_DIR}:/voices" \
    "$IMAGE" python3 - "/voices/${VOICE}.onnx" <<'PYEOF'
import subprocess, sys
import onnxruntime
path = sys.argv[1]
def n_outputs():
    return len(onnxruntime.InferenceSession(path).get_outputs())
if n_outputs() >= 2:
    print(f"voice already alignment-patched: {path}")
    sys.exit(0)
print(f"patching voice with alignment output: {path}")
subprocess.run(
    [sys.executable, "-m", "piper.patch_voice_with_alignment", path],
    check=True)
# the patcher does not propagate failures via exit code — verify
if n_outputs() < 2:
    sys.exit(f"ERROR: patch did not add the alignment output to {path}")
print("patched ok (2 outputs)")
PYEOF

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
