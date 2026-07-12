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
  - --sections '2' / '1-2' / '1,3' scopes ONE RUN to those chapters
    (session-sized batches on the build machine); files, manifest and
    coverage remain per-sentence and book-total. --dry-run prints the
    section table with indices and audio estimates.
  - Repeated identical sentences share one sid → one file, by design.
  - Text = join(toks, sp) with orth modernisation applied (better TTS
    pronunciation; same form check mode grades against). --raw-orth
    synthesises the original spelling instead.
  - books.json is NOT touched here; the `audio` base URL flows from
    tools/v3/books_src.toml through the app build (build3.py --audio)
    once the audio repo's Pages site is up.
  - Timing REQUIRES an alignment-patched voice: stock rhasspy voices
    export only the audio tensor, so every sentence comes back
    unaligned (container/audio.sh patches the .onnx once via
    `python3 -m piper.patch_voice_with_alignment`). Durations are
    stochastic per synthesis, so timing is only valid for the audio of
    the SAME run — files synthesised before the patch need --force.

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


def _align_words_to_runs(word_lens, run_lens, penalty=2.0, gmax=3):
    """DP alignment of spoken words to display runs by phoneme length.

    espeak FUSES function words ('in the' -> 'ɪnðə', 'Es ist' ->
    'ɛsɪst'): one spoken word covers several runs (1:N). Numbers go
    the other way ('1922' -> three spoken words, N:1). Ops: (1,1),
    (1,2)..(1,gmax), (2,1)..(gmax,1); cost = |phoneme-length diff| +
    penalty per extra unit. Returns [(n_words, n_runs), ...] covering
    both sequences, or None when no alignment exists.
    """
    n_w, n_r = len(word_lens), len(run_lens)
    if not n_w or not n_r:
        return None
    inf = float("inf")
    dp = [[inf] * (n_r + 1) for _ in range(n_w + 1)]
    bk = [[None] * (n_r + 1) for _ in range(n_w + 1)]
    dp[0][0] = 0.0
    ops = [(1, k) for k in range(1, gmax + 1)] \
        + [(k, 1) for k in range(2, gmax + 1)]
    for i in range(n_w + 1):
        for j in range(n_r + 1):
            base = dp[i][j]
            if base == inf:
                continue
            for nw, nr in ops:
                if i + nw > n_w or j + nr > n_r:
                    continue
                cost = abs(sum(word_lens[i:i + nw])
                           - sum(run_lens[j:j + nr])) \
                    + penalty * (nw + nr - 2)
                if base + cost < dp[i + nw][j + nr]:
                    dp[i + nw][j + nr] = base + cost
                    bk[i + nw][j + nr] = (nw, nr)
    if dp[n_w][n_r] == inf or dp[n_w][n_r] / n_w > 3.0:
        return None                      # no/implausible alignment
    groups, i, j = [], n_w, n_r
    while i or j:
        nw, nr = bk[i][j]
        groups.append((nw, nr))
        i, j = i - nw, j - nr
    groups.reverse()
    return groups


def run_ends_from_words(words_ph, word_ends, runs, solo_len):
    """Per-run end times from per-word (phoneme string, end) pairs.

    words_ph/word_ends: spoken words in order (phonemes, end seconds).
    runs: text.split() — the reader's display runs. solo_len(run) ->
    phoneme length of the run spoken alone (espeak; 0 for pure
    punctuation). Fast path: counts equal -> identity. Otherwise DP
    (see _align_words_to_runs); fused runs interpolate inside their
    word proportionally to solo lengths; punctuation-only runs stick
    to the preceding end. Returns list (len == len(runs)) or None.
    """
    alnum = [i for i, r in enumerate(runs) if any(c.isalnum() for c in r)]
    ends = [None] * len(runs)

    if len(words_ph) == len(alnum):
        groups = [(1, 1)] * len(alnum)
    else:
        groups = _align_words_to_runs(
            [len(w) for w in words_ph],
            [max(1, solo_len(runs[i])) for i in alnum])
        if groups is None:
            return None

    wi = ri = 0
    t_prev = 0.0
    for nw, nr in groups:
        t_end = word_ends[wi + nw - 1]
        span = [alnum[k] for k in range(ri, ri + nr)]
        if nr == 1:
            ends[span[0]] = t_end
        else:                            # fused: split the word's time
            lens = [max(1, solo_len(runs[i])) for i in span]
            total, cum = sum(lens), 0
            for i, ln in zip(span, lens):
                cum += ln
                ends[i] = t_prev + (t_end - t_prev) * cum / total
            ends[span[-1]] = t_end       # exact at the word edge
        wi, ri, t_prev = wi + nw, ri + nr, t_end

    t = 0.0                              # punct-only runs: previous end
    for i in range(len(runs)):
        if ends[i] is None:
            ends[i] = t
        else:
            t = ends[i]
    return [round(e, 3) for e in ends]


def synth_with_timing(voice, text, wav_path, want_timing=True):
    """Synthesize `text` to `wav_path`; return (duration_s, run_ends_s).

    run_ends_s: cumulative end time (seconds) of every whitespace-
    separated unit of `text` — the reader's display RUNS (sp bits) —
    derived from piper's native phoneme alignments (piper1-gpl
    `include_alignments=True`, alignment-patched voice): space phonemes
    delimit words, BOS/EOS bracket each espeak sentence, chunk
    boundaries close words too. Spoken-word count can disagree with the
    run count (espeak fuses function words, expands numbers, drops bare
    dashes/quotes) — run_ends_from_words maps words to runs; None (no
    timing for this sentence) only when even that fails. Partial timing
    coverage is fine by design, like partial audio coverage.
    """
    try:                              # deferred like PiperVoice; the
        from piper.voice import BOS, EOS   # fallback keeps the pure
    except ImportError:                    # timing logic unit-testable
        BOS, EOS = "^", "$"                # without piper installed

    rate = voice.config.sample_rate
    cum = 0                      # samples emitted so far (all chunks)
    word_ends = []               # sample offset at each word end
    words_ph = []                # phoneme string of each spoken word
    cur = ""
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
                        words_ph.append(cur)
                    in_word, cur = False, ""
                elif al.phoneme in (BOS, EOS):
                    if in_word:          # EOS closes the last word
                        word_ends.append(prev)
                        words_ph.append(cur)
                    in_word, cur = False, ""
                else:
                    in_word = True
                    cur += al.phoneme
            if in_word:                  # chunk boundary closes a word
                word_ends.append(cum)
                words_ph.append(cur)
                in_word, cur = False, ""
    dur = round(cum / rate, 2) if cum else None
    if dur is None:                      # alignments off: probe the wav
        with wave.open(str(wav_path), "rb") as wf:
            dur = round(wf.getnframes() / wf.getframerate(), 2)
    if not have_align or not word_ends:
        return dur, None

    ends_s = [w / rate for w in word_ends]
    phonemize = getattr(voice, "phonemize", None)
    if phonemize is None:                # unit-test fakes: no mapping
        runs = text.split()
        if len(word_ends) != len(runs):
            return dur, None
        return dur, [round(e, 3) for e in ends_s]

    cache = {}
    def solo_len(run):
        if run not in cache:
            try:
                cache[run] = sum(len(p) for sent in phonemize(run)
                                 for p in sent if p != " ")
            except Exception:  # noqa: BLE001 — espeak oddity: punt
                cache[run] = 0
        return cache[run]

    return dur, run_ends_from_words(words_ph, ends_s, text.split(),
                                    solo_len)


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


def parse_sections(spec, n):
    """'2', '1-2', '1,3' (1-based, as printed by --dry-run) -> 0-based set."""
    idx = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            idx.update(range(int(a) - 1, int(b)))
        else:
            idx.add(int(part) - 1)
    bad = sorted(i + 1 for i in idx if not 0 <= i < n)
    if bad:
        raise SystemExit(f"--sections: no section {bad}; book has 1-{n}")
    return idx


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
    ap.add_argument("--sections", metavar="SPEC",
                    help="only synthesise these sections, 1-based: "
                         "'2', '1-2', '1,3' (indices as shown by --dry-run). "
                         "Files/manifest stay per-sentence & book-total; "
                         "this only scopes one run.")
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

    # unique sids in book order; repeated identical sentences share a file.
    # texts always covers the WHOLE book (manifest coverage is book-total);
    # --sections only scopes which sids this run synthesises.
    sections = book["sections"]
    texts = {}  # sid -> text
    total_occurrences = 0
    for sent in iter_sentences(book):
        total_occurrences += 1
        texts.setdefault(sent["id"], sentence_text(sent, not args.raw_orth))

    sel = parse_sections(args.sections, len(sections)) if args.sections \
        else set(range(len(sections)))
    scope = {s["id"] for i in sel for s in sections[i]["sentences"]}

    out_dir = Path(args.out) / book_id
    existing = {p.stem for p in out_dir.glob("*.opus")} if out_dir.is_dir() else set()
    todo = [sid for sid in texts
            if sid in scope and (args.force or sid not in existing)]
    if args.limit:
        todo = todo[: args.limit]

    print(f"==== {book_id} ({lang}): {len(texts)} unique sentences "
          f"({total_occurrences} occurrences), {len(existing)} on disk, "
          f"{len(todo)} to synthesise"
          + (f" [sections {args.sections}]" if args.sections else ""))
    if args.dry_run:
        # per-section table; audio estimate ~14 chars/s (medium voices)
        print(f"  {'#':>3} {'sentences':>9} {'new':>5} {'~audio':>8}  title")
        for i, sec in enumerate(sections):
            sids = {s["id"] for s in sec["sentences"]}
            chars = sum(len(texts[sid]) for sid in sids)
            mins = chars / 14 / 60
            mark = "*" if i in sel else " "
            print(f" {mark}{i + 1:>3} {len(sec['sentences']):>9} "
                  f"{len(sids - existing):>5} {mins:>6.0f}m   "
                  f"{sec.get('title', '')[:40]}")
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

    # fail LOUDLY before synthesising a whole batch: an unpatched voice
    # (single ONNX output) can never produce timing — see the docstring.
    if not args.no_timing:
        try:
            n_out = len(voice.session.get_outputs())
        except Exception:  # noqa: BLE001 — probe only, never block synth
            n_out = None
        if n_out == 1:
            print("WARNING: voice model has NO alignment output — every "
                  "sentence will be unaligned and timing.json will stay "
                  "empty. Patch the voice once:\n"
                  "  python3 -m piper.patch_voice_with_alignment "
                  f"{voice_path}\n"
                  "(container/audio.sh does this automatically), then "
                  "re-run with --force.", file=sys.stderr)

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
    if n_unaligned and n_unaligned == len(todo) - len(failed):
        print("WARNING: EVERY sentence came back without alignments — the "
              "voice model almost certainly lacks the duration output "
              "(stock rhasspy export). Patch it once:\n"
              "  python3 -m piper.patch_voice_with_alignment <voice.onnx>\n"
              "(container/audio.sh does this automatically), then re-run "
              "with --force: timing is only valid for audio from the same "
              "synthesis run.", file=sys.stderr)
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
