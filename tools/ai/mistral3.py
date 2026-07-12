#!/usr/bin/env python3
"""
tools/ai/mistral3.py — shared plumbing for the v3 AI passes
(00_v3_overview §5).  Extracted from emoji3.py when gde3.py became the
second consumer (2026-07-12).  Nothing here runs inside the
deterministic build; scripts in this folder produce reviewable
artifacts in build/ that the owner promotes into tools/v3/maps/.

The contract every pass shares:
- MISTRAL_API_KEY env var; api.mistral.ai chat completions; JSON-object
  response mode; stdlib urllib only (no SDK).
- Prompts are versioned FILES in prompts/ — the file name IS the cache
  version: editing a prompt means saving it as <name>_v2.txt, which
  cleanly invalidates only that stage's cache lines.
- cache/*.jsonl is COMMITTED (reproducibility, diffable reruns).
  --new-cache moves the file aside (kept) for e.g. model A/B runs,
  since cache keys do not include the model.
- --mock runs the whole pipeline offline without touching cache or
  real artifacts (out_path adds .mock).
- Batches are keyed by the item's "lemma" field; the model must answer
  with a JSON object keyed the same way.
"""

import json
import os
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent            # tools/ai
ROOT = HERE.parent.parent                          # repo root
DATA = ROOT / "docs" / "data3"
MAPS = ROOT / "tools" / "v3" / "maps"

API_URL = "https://api.mistral.ai/v1/chat/completions"
BATCH = 40
LANG_NAME = {"de": "German", "en": "English"}


def git_short():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=HERE, capture_output=True, text=True,
                             check=True).stdout.strip()
        return out or "0000000"
    except Exception:
        return "0000000"


def nfc_lower(s):
    return unicodedata.normalize("NFC", s).lower()


def is_word(s):
    return any(ch.isalnum() for ch in s)


# ------------------------------------------------------------ prompts/cache

def load_prompt(name):
    """(text, version).  Version = file name — bump by saving a _v2."""
    path = HERE / "prompts" / f"{name}.txt"
    return path.read_text("utf-8"), name


class Cache:
    """Append-only JSONL: {"k": key, "v": value}.  Key embeds the prompt
    version; the whole file is committed so reruns are reproducible and
    reviewable as diffs.

    archive=True (--new-cache): the existing file is MOVED aside to
    <name>.<timestamp>.jsonl (kept, still committed — history) and the
    run starts cold — the model A/B lever, since cache keys do not
    include the model."""

    def __init__(self, path, mock, archive=False):
        self.path, self.mock, self.mem = path, mock, {}
        if archive and not mock and path.exists():
            aside = path.with_name(
                f"{path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
            path.rename(aside)
            print(f"  cache moved aside -> {aside.name}")
            return
        if path.exists():
            for line in path.read_text("utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.mem[rec["k"]] = rec["v"]

    def get(self, key):
        return None if self.mock else self.mem.get(key)

    def put(self, key, value):
        self.mem[key] = value
        if self.mock:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"k": key, "v": value},
                               ensure_ascii=False) + "\n")


# ------------------------------------------------------------ API

# Request pacing baked in (owner 2026-07-12: "so I don't ban myself").
# Mistral workspace tiers: mistral-large-* = 0.5 req/s (and 800k TPM,
# which batched requests never approach); mistral-medium-* = 33 req/s.
# A floor of 2.2s between LARGE requests keeps every run inside the
# tier with margin; other models get a token 0.1s courtesy gap.
_last_request = [0.0]


def _pace(model):
    gap = 2.2 if "large" in model else 0.1
    wait = _last_request[0] + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request[0] = time.monotonic()


def api_call(model, system, user, temperature):
    key = os.environ.get("MISTRAL_API_KEY")
    if not key:
        sys.exit("MISTRAL_API_KEY is not set (or use --mock)")
    body = json.dumps({
        "model": model,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    })
    delay = 2
    for attempt in range(6):
        try:
            _pace(model)
            with urllib.request.urlopen(req, timeout=120) as resp:
                out = json.loads(resp.read().decode("utf-8"))
            return json.loads(out["choices"][0]["message"]["content"])
        except (urllib.error.HTTPError, urllib.error.URLError,
                json.JSONDecodeError, KeyError, TimeoutError) as exc:
            code = getattr(exc, "code", None)
            if isinstance(exc, urllib.error.HTTPError) \
                    and code not in (429,) and not 500 <= (code or 0) < 600:
                raise                              # 4xx other than 429: bug
            if attempt == 5:
                raise
            print(f"    retry in {delay}s ({exc})", file=sys.stderr)
            time.sleep(delay)
            delay *= 2


def batched(seq, n=BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def run_stage(items, key_of, prompt_name, cache, args, lang,
              temperature, mock_answer, default):
    """Generic cached batch stage.  items -> {key_of(item): answer}.
    Cached keys (same prompt version) are not re-asked; model answers
    for lemmas it was not asked about are discarded; lemmas the model
    skipped get `default`."""
    system, version = load_prompt(prompt_name)
    out, todo = {}, []
    for it in items:
        hit = cache.get(f"{version}|{key_of(it)}")
        if hit is None:
            todo.append(it)
        else:
            out[key_of(it)] = hit
    print(f"  {prompt_name}: {len(items) - len(todo)} cached, "
          f"{len(todo)} to ask")
    for batch in batched(todo):
        user = (f"Language: {LANG_NAME.get(lang, lang)}\n"
                + json.dumps(batch, ensure_ascii=False))
        if args.mock:
            resp = {it["lemma"]: mock_answer(it, lang) for it in batch}
        else:
            resp = api_call(args.model, system, user, temperature)
        for it in batch:
            val = resp.get(it["lemma"], default)
            out[key_of(it)] = val
            cache.put(f"{version}|{key_of(it)}", val)
        print(f"    batch of {len(batch)} done")
    return out


# ------------------------------------------------------------ artifacts

def meta(args, extra):
    return {"generator": f"{Path(sys.argv[0]).name}@{git_short()}",
            "model": "mock" if args.mock else args.model,
            "date": time.strftime("%Y-%m-%d"), **extra}


def out_path(args, name):
    """Mock runs write .mock.json siblings so a plumbing test never
    pollutes the real artifacts (some are merged across runs, so a
    mock write there would stick)."""
    if args.mock:
        name = name.replace(".json", ".mock.json") \
                   .replace("_rejected.txt", "_rejected.mock.txt")
    return HERE / "build" / name


def write_map(path, m, kept):
    """_meta first, then sorted lemmas — a flat map gloss3 can consume
    directly (it only ever .get()s lemma keys, never '_meta')."""
    out = {"_meta": m}
    out.update({k: kept[k] for k in sorted(kept)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"  -> {path} ({len(kept)} entries)")


def write_rejected(path, rejected):
    if not rejected:
        return
    path.write_text("".join(
        "\t".join(map(str, row)) + "\n" for row in sorted(rejected)),
        encoding="utf-8")
    print(f"  -> {path} ({len(rejected)} rejected)")


# ------------------------------------------------------------ book data

def sentence_text(sent):
    return "".join(t + (" " if b == "1" else "")
                   for t, b in zip(sent["toks"], sent["sp"])).strip()


def load_book(book_id):
    """(lang, book, gloss) for a built book, via books.json."""
    books = json.loads((DATA / "books.json").read_text("utf-8"))
    entry = next((b for b in books["books"] if b["id"] == book_id), None)
    if not entry:
        sys.exit(f"unknown book id {book_id!r} (not in books.json)")
    lang = entry["lang"]
    book = json.loads((DATA / lang / f"{book_id}.json").read_text("utf-8"))
    gloss = json.loads(
        (DATA / "gloss" / f"{book_id}.json").read_text("utf-8"))
    return lang, book, gloss


def first_sentences(book, study_by_sent, cap=240):
    """study lemma -> text of its first-occurrence sentence."""
    first = {}
    for sec in book["sections"]:
        for sent in sec["sentences"]:
            text = None
            for lemma in study_by_sent.get(sent["id"], []):
                if lemma not in first:
                    text = text or sentence_text(sent)
                    first[lemma] = text[:cap]
    return first


def add_common_args(ap):
    ap.add_argument("--model", default="mistral-large-latest")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap candidate count (pilot runs)")
    ap.add_argument("--new-cache", action="store_true",
                    help="move the run's cache file(s) aside "
                         "(<name>.<timestamp>.jsonl, kept) and re-ask "
                         "everything — e.g. to A/B another --model")
    ap.add_argument("--mock", action="store_true",
                    help="offline plumbing test: fake answers, cache "
                         "untouched, artifacts written as .mock files")
