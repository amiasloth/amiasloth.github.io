#!/usr/bin/env python3
"""audio3.py — v3 audio pass: per-sentence opus files from a built book.

Design record: technical/v3_discussion/00_v3_overview.md §4 (2026-07-11).
Consumes the BUILT book file (docs/data3/<lang>/<id>.json) — never the
raw Gutenberg source, so front/back-matter trimming and encoding are
already handled by build3.py. Output goes to a SEPARATE audio repo
checkout (zzzpeak-audio), never into docs/.

    <out>/<book_id>/<sid>.opus     one file per unique sentence id
    <out>/<book_id>/manifest.json  voice (+license), coverage, per-sid
                                   durations, provenance
    <out>/<book_id>/timing.json    per-sid display-run end times from
                                   piper's native phoneme alignments —
                                   chunk playback = slice the sentence
                                   audio (no extra alignment tool)

Properties:
  - Incremental: existing .opus files are kept (use --force to redo);
    durations for kept files come from the previous manifest.
  - Repeated identical sentences share one sid → one file, by design.
  - Text = join(toks, sp) with orth modernisation applied (better TTS
    pronunciation; same form check mode grades against). --raw-orth
    synthesises the original spelling instead.
  - books.json is NOT touched here; set its `audio` base URL by hand
    once the audio repo's Pages site is up.

Runs inside the ephemeral audio container (container/audio.sh) or
anywhere with `pip install piper-tts` + opus-tools. --dry-run needs
neither.

Usage:
  python3 audio3.py --book ../../docs/data3/de/kafka.json \
      --voice /voices/de_DE-thorsten-medium.onnx --out /audio [options]
"""

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

MANIFEST_SCHEMA = 1


def synth_with_timing(voice, text, wav_path, want_timing=True):
    """Synthesize `text` to `wav_path`; return (duration_s, run_ends_s).

    run_ends_s: cumulative end time (seconds) of every whitespace-
    separated unit of `text` — the reader's display RUNS (sp bits) —
    derived from piper's native phoneme alignments (piper1-gpl
    `include_alignments=True`): space phonemes delimit words, BOS/EOS
    bracket each espeak sentence, chunk boundaries close words too.
    Returns None for run_ends_s when the voice model does not emit
    alignments or the word count disagrees with the run count (espeak
    dropped/expanded units — numbers, bare dashes); partial timing
    coverage is fine by design, like partial audio coverage.
    """
    try:                              # deferred like PiperVoice; the
        from piper.voice import BOS, EOS   # fallback keeps the pure
    except ImportError:                    # timing logic unit-testable
        BOS, EOS = "^", "$"                # without piper installed

    rate = voice.config.sample_rate
    cum = 0                      # samples emitted so far (all chunks)
    word_ends = []               # sample offset at each word end
    in_word = False
    have_align = want_timing
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for chunk in voice.synthesize(text, include_alignments=want_timing):
            wf.writeframes(chunk.audio_int16_bytes)
            aligns = chunk.phoneme_alignments if want_timing else None
            if aligns is None:
                have_align = False
                cum += len(chunk.audio_int16_array)
                continue
            for al in aligns:
                prev = cum
                cum += al.num_samples
                if al.phoneme == " ":
                    if in_word:
                        word_ends.append(prev)
                    in_word = False
                elif al.phoneme in (BOS, EOS):
                    if in_word:          # EOS closes the last word
                        word_ends.append(prev)
                    in_word = False
                else:
                    in_word = True
            if in_word:                  # chunk boundary closes a word
                word_ends.append(cum)
                in_word = False
    dur = round(cum / rate, 2) if cum else None
    if dur is None:                      # alignments off: probe the wav
        with wave.open(str(wav_path), "rb") as wf:
            dur = round(wf.getnframes() / wf.getframerate(), 2)
    if not have_align or len(word_ends) != len(text.split()):
        return dur, None
    return dur, [round(w / rate, 3) for w in word_ends]


def sentence_text(sent, use_orth=True):
    """Reconstruct sentence text from toks+sp, optionally orth-modernised."""
    toks = list(sent["toks"])
    if use_orth:
        for i, form in (sent.get("orth") or {}).items():
            toks[int(i)] = form
    sp = sent["sp"]
    return "".join(t + (" " if b == "1" else "") for t, b in zip(toks, sp)).strip()


def iter_sentences(book):
    for sec in book["sections"]:
        for sent in sec["sentences"]:
            yield sent


def sha256_12(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()[:12]


def git_rev(repo_dir):
    import os
    if os.environ.get("AUDIO3_REV"):  # set by container/audio.sh (image has no git)
        return os.environ["AUDIO3_REV"]
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def opus_duration(path):
    """Fallback duration probe for pre-existing files missing from the
    old manifest: parse `opusinfo` playback length."""
    try:
        out = subprocess.run(["opusinfo", str(path)],
                             capture_output=True, text=True).stdout
        m = re.search(r"Playback length:\s*(?:(\d+)h)?:?(\d+)m:([\d.]+)s", out)
        if m:
            h = int(m.group(1) or 0)
            return round(h * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 2)
    except Exception:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--book", required=True,
                    help="built book file, e.g. docs/data3/de/kafka.json")
    ap.add_argument("--voice", help=".onnx voice model (required unless --dry-run)")
    ap.add_argument("--out", required=True,
                    help="audio repo root; files go to <out>/<book_id>/")
    ap.add_argument("--bitrate", type=int, default=24,
                    help="opus bitrate in kbps (default 24; 16 = size fallback)")
    ap.add_argument("--limit", type=int, default=0,
                    help="synthesise at most N new sentences (smoke tests)")
    ap.add_argument("--force", action="store_true",
                    help="re-synthesise even if the .opus already exists")
    ap.add_argument("--raw-orth", action="store_true",
                    help="synthesise original spelling, not orth-modernised")
    ap.add_argument("--no-timing", action="store_true",
                    help="skip run-timing extraction (timing.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be done; no piper/opusenc needed")
    args = ap.parse_args()

    book = json.loads(Path(args.book).read_text(encoding="utf-8"))
    book_id, lang = book["id"], book["lang"]

    # unique sids in book order; repeated identical sentences share a file
    texts = {}  # sid -> text
    total_occurrences = 0
    for sent in iter_sentences(book):
        total_occurrences += 1
        texts.setdefault(sent["id"], sentence_text(sent, not args.raw_orth))

    out_dir = Path(args.out) / book_id
    existing = {p.stem for p in out_dir.glob("*.opus")} if out_dir.is_dir() else set()
    todo = [sid for sid in texts if args.force or sid not in existing]
    if args.limit:
        todo = todo[: args.limit]

    print(f"==== {book_id} ({lang}): {len(texts)} unique sentences "
          f"({total_occurrences} occurrences), {len(existing)} on disk, "
          f"{len(todo)} to synthesise")
    if args.dry_run:
        for sid in todo[:5]:
            print(f"  {sid}  {texts[sid][:70]}")
        if len(todo) > 5:
            print(f"  ... {len(todo) - 5} more")
        return 0

    if not args.voice:
        ap.error("--voice is required unless --dry-run")
    voice_path = Path(args.voice)

    from piper import PiperVoice  # deferred: --dry-run works without piper
    voice = PiperVoice.load(str(voice_path))

    manifest_path = out_dir / "manifest.json"
    old = json.loads(manifest_path.read_text(encoding="utf-8")) \
        if manifest_path.is_file() else {}
    durations = dict(old.get("durations") or {})

    timing_path = out_dir / "timing.json"
    old_timing = json.loads(timing_path.read_text(encoding="utf-8")) \
        if timing_path.is_file() else {}
    run_ends = dict(old_timing.get("runs") or {})  # sid -> [end_s, ...]

    out_dir.mkdir(parents=True, exist_ok=True)
    failed = []
    n_unaligned = 0
    for n, sid in enumerate(todo, 1):
        text = texts[sid]
        opus_path = out_dir / f"{sid}.opus"
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
                dur, ends = synth_with_timing(
                    voice, text, tmp.name, want_timing=not args.no_timing)
                tmp_opus = opus_path.with_suffix(".opus.tmp")
                subprocess.run(
                    ["opusenc", "--quiet", "--bitrate", str(args.bitrate),
                     tmp.name, str(tmp_opus)],
                    check=True, capture_output=True)
                tmp_opus.replace(opus_path)  # atomic: no half-written files
            durations[sid] = dur
            if ends is not None:
                run_ends[sid] = ends
            else:
                run_ends.pop(sid, None)      # resynth invalidates old timing
                if not args.no_timing:
                    n_unaligned += 1
        except Exception as e:  # noqa: BLE001 — log & continue the batch
            failed.append(sid)
            print(f"  FAIL {sid}: {e}", file=sys.stderr)
        if n % 100 == 0 or n == len(todo):
            print(f"  {n}/{len(todo)}")

    # durations for files that predate the manifest (or a lost manifest)
    on_disk = {p.stem for p in out_dir.glob("*.opus")}
    for sid in sorted(on_disk - set(durations)):
        d = opus_duration(out_dir / f"{sid}.opus")
        if d is not None:
            durations[sid] = d
    durations = {sid: durations[sid] for sid in texts if sid in durations}

    voice_cfg = {}
    cfg_path = Path(str(voice_path) + ".json")
    if cfg_path.is_file():
        voice_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    covered = len(on_disk & set(texts))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generator": f"audio3.py@{git_rev(Path(__file__).parent)}",
        "created": _dt.datetime.now(_dt.timezone.utc)
                      .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "book": {"id": book_id, "lang": lang,
                 "generator": book.get("generator"),
                 "source_hash": book.get("source_hash")},
        "voice": {
            "file": voice_path.name,
            "sha256": sha256_12(voice_path),
            "name": (voice_cfg.get("dataset")
                     or voice_path.stem.split("-")[0]),
            "quality": voice_cfg.get("audio", {}).get("quality"),
            "sample_rate": voice_cfg.get("audio", {}).get("sample_rate"),
            "license": "see MODEL_CARD in rhasspy/piper-voices for this voice",
        },
        "encode": {"codec": "opus", "bitrate_kbps": args.bitrate, "channels": 1},
        "orth_applied": not args.raw_orth,
        "coverage": {"sentences": len(texts), "files": covered,
                     "complete": covered == len(texts),
                     "seconds": round(sum(durations.values()), 1)},
        "durations": durations,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    # timing sidecar (design 2026-07-12): per-sid END TIME (seconds) of
    # each display RUN — whitespace unit of the synthesised text, which
    # the reader maps to token indices via the sp bits.  Chunk playback
    # = seek ends[run(a)-1], stop at ends[run(b)-1].  Kept OUT of the
    # manifest so partial/absent timing never bloats or blocks it.
    run_ends = {sid: run_ends[sid] for sid in texts
                if sid in run_ends and sid in on_disk}
    timing = {
        "schema": 1,
        "generator": manifest["generator"],
        "book": manifest["book"],
        "voice_sha256": manifest["voice"]["sha256"],
        "granularity": "runs",
        "coverage": {"sentences": len(texts), "timed": len(run_ends)},
        "runs": run_ends,
    }
    timing_path.write_text(
        json.dumps(timing, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")

    print(f"manifest -> {manifest_path}")
    print(f"timing   -> {timing_path} ({len(run_ends)}/{len(texts)} timed"
          + (f", {n_unaligned} unaligned this run" if n_unaligned else "")
          + ")")
    print(f"coverage: {covered}/{len(texts)} "
          f"({manifest['coverage']['seconds']}s total)")
    if covered == len(texts):
        print(f"REMINDER: set books.json audio base URL for '{book_id}' "
              f"once the audio repo Pages site serves these files.")
    if failed:
        print(f"{len(failed)} sentence(s) FAILED: {' '.join(failed[:10])}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
