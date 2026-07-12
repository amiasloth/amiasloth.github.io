#!/usr/bin/env python3
"""
tools/ai/emoji3.py — Mistral emoji-map passes (first AI pass of
00_v3_overview §5).  Lives in tools/ai/ (all AI tooling; owner decision
2026-07-12) — nothing here ever runs inside the deterministic build.

Two products, two strictness levels (owner decisions 2026-07-12):

  --book <id>   STUDY lemmas of one book -> build/emoji_ai_<id>.json.
                The book fixes the sense, so the model sees gloss +
                first-occurrence sentence and may be reasonably liberal.
                Owner review -> tools/v3/maps/emoji_<id>.json (the
                existing gloss3 --emoji-map entry point; replaces the
                CLDR stand-in).  COMMON lemmas encountered in the book
                are ALSO proposed (book context helps find them), but
                graded with the strict GENERAL rubric and routed into
                the general candidates file — the per-book map stays
                study-only.

  --general     Frequent lemmas (wordfreq top-N, simplemma-lemmatised)
                -> build/emoji_general_candidates_<lang>.json.  No
                context, so an emoji is kept only for the DOMINANT
                sense and only when unambiguous — conservative by
                prompt AND by grader.  Owner review ->
                tools/v3/maps/emoji_general_<lang>.json, a new gloss3
                layer BELOW the curated emoji_map.py (hand-picked wins
                collisions, machine never edits the curated file).

Both passes are two-stage generate -> grade (separate prompts, separate
calls); anything failing sanity checks or the grader is dropped —
"empty beats bad" end to end.  Rejections are listed in
build/emoji_*_rejected.txt for the owner review.

Plumbing:
- MISTRAL_API_KEY env var; api.mistral.ai chat completions; JSON-object
  response mode; stdlib urllib only (no SDK).
- cache/*.jsonl is COMMITTED (reproducibility, diffable reruns).  Keys
  include the prompt version (= prompt file name), so editing a prompt
  means saving it as prompts/<name>_v2.txt — old cache lines simply
  stop matching.
- --mock runs the whole pipeline offline (curated map echoes as fake
  answers, grader keeps all) without touching the cache: plumbing test.

Usage (build machine or anywhere with the key):
  export MISTRAL_API_KEY=...
  python3 tools/ai/emoji3.py --book kafka
  python3 tools/ai/emoji3.py --general --lang de --top 5000
"""

import argparse
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
sys.path.insert(0, str(ROOT / "tools"))            # emoji_map.py (read-only)
from emoji_map import EMOJI                        # noqa: E402

API_URL = "https://api.mistral.ai/v1/chat/completions"
BATCH = 40
LANG_NAME = {"de": "German", "en": "English"}

# Same guard as gloss3.py (schema rev 3.1): function words never carry
# emoji — they would fire on nearly every chunk.
EMOJI_FUNC_POS = {"DET", "PRON", "ADP", "CCONJ", "SCONJ", "CONJ",
                  "PART", "AUX"}


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


def is_emoji(s):
    """Same deliberately loose filter as emoji_map_gen3.py: a pictograph
    or symbol (♪ counts; ∈, @, ≡ not)."""
    return any(ord(c) >= 0x1F000 or 0x2600 <= ord(c) <= 0x27BF
               for c in s) and not any(0x2200 <= ord(c) <= 0x22FF
                                       for c in s)


def emoji_sane(e):
    """Deterministic pre-grade check.  '' is valid (means: none).
    ONE emoji only: multiple pictographs are allowed solely when ZWJs
    join them into a single glyph (🐦‍⬛, 👨‍👩‍👧 pass; 🐱🐶 fails)."""
    if e == "":
        return True
    if len(e) > 8 or any(c.isspace() for c in e):
        return False
    if any(c.isascii() and c.isalnum() for c in e):
        return False
    core = [c for c in e                     # drop presentation marks
            if not (c == "️" or "\U0001f3fb" <= c <= "\U0001f3ff"
                    or c == "⃣")]
    n_zwj = core.count("‍")
    if len(core) - n_zwj > n_zwj + 1:
        return False
    return is_emoji(e)


# ------------------------------------------------------------ prompts/cache

def load_prompt(name):
    """(text, version).  Version = file name — bump by saving a _v2."""
    path = HERE / "prompts" / f"{name}.txt"
    return path.read_text("utf-8"), name


class Cache:
    """Append-only JSONL: {"k": key, "v": value}.  Key embeds the prompt
    version; the whole file is committed so reruns are reproducible and
    reviewable as diffs."""

    def __init__(self, path, mock):
        self.path, self.mock, self.mem = path, mock, {}
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


def MOCK_GEN(it, lang):    # echo the curated map: realistic sparsity
    return EMOJI[lang].get(it["lemma"], "")


def MOCK_GRADE(it, lang):
    return True


# ------------------------------------------------------------ pipeline

def two_stage(items, kind, lang, cache, args, rejected):
    """items: [{"lemma","gloss"?,"sentence"?}] -> {lemma: emoji} kept.
    kind: 'book' (liberal) or 'general' (strict) — picks the prompts."""
    gen = run_stage(
        items, key_of=lambda it: it["lemma"],
        prompt_name=f"{kind}_gen_v1", cache=cache, args=args, lang=lang,
        temperature=0.15, mock_answer=MOCK_GEN, default="")

    to_grade = []
    for it in items:
        e = (gen.get(it["lemma"]) or "").strip()
        if e == "":
            continue
        if not emoji_sane(e):
            rejected.append((it["lemma"], it.get("gloss", ""), e, "sanity"))
            continue
        to_grade.append({**it, "emoji": e})

    grade = run_stage(
        to_grade, key_of=lambda it: f"{it['lemma']}|{it['emoji']}",
        prompt_name=f"{kind}_grade_v1", cache=cache, args=args, lang=lang,
        temperature=0.0, mock_answer=MOCK_GRADE, default=False)

    kept = {}
    for it in to_grade:
        if grade.get(f"{it['lemma']}|{it['emoji']}") is True:
            kept[it["lemma"]] = it["emoji"]
        else:
            rejected.append((it["lemma"], it.get("gloss", ""),
                             it["emoji"], "grader"))
    return kept


def meta(args, extra):
    return {"generator": f"emoji3.py@{git_short()}",
            "model": "mock" if args.mock else args.model,
            "date": time.strftime("%Y-%m-%d"), **extra}


def out_path(args, name):
    """Mock runs write .mock.json siblings so a plumbing test never
    pollutes the real artifacts (the candidates file is merged across
    runs, so a mock write there would stick)."""
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
        f"{l}\t{g}\t{e}\t{why}\n" for l, g, e, why in sorted(rejected)),
        encoding="utf-8")
    print(f"  -> {path} ({len(rejected)} rejected)")


def merge_general_candidates(lang, kept, args, provenance):
    """Common/general keepers accumulate in ONE candidates file per
    language (merged across --book and --general runs, sorted)."""
    path = out_path(args, f"emoji_general_candidates_{lang}.json")
    existing = {}
    if path.exists():
        existing = {k: v for k, v in
                    json.loads(path.read_text("utf-8")).items()
                    if not k.startswith("_")}
    existing.update(kept)
    write_map(path, meta(args, {"kind": "general-candidates",
                                "lang": lang, "last_source": provenance}),
              existing)


def load_general_covered(lang):
    """Lemmas already carrying an emoji in the curated map or the
    reviewed general map — no need to re-propose them."""
    covered = set(EMOJI.get(lang, {}))
    reviewed = ROOT / "tools" / "v3" / "maps" / f"emoji_general_{lang}.json"
    if reviewed.exists():
        covered |= {k for k, v in
                    json.loads(reviewed.read_text("utf-8")).items()
                    if v and not k.startswith("_")}
    return covered


# ------------------------------------------------------------ --book

def sentence_text(sent):
    return "".join(t + (" " if b == "1" else "")
                   for t, b in zip(sent["toks"], sent["sp"])).strip()


def run_book(args):
    books = json.loads((DATA / "books.json").read_text("utf-8"))
    entry = next((b for b in books["books"] if b["id"] == args.book), None)
    if not entry:
        sys.exit(f"unknown book id {args.book!r} (not in books.json)")
    lang = entry["lang"]
    gloss = json.loads(
        (DATA / "gloss" / f"{args.book}.json").read_text("utf-8"))
    book = json.loads(
        (DATA / lang / f"{args.book}.json").read_text("utf-8"))
    words, freq = gloss["words"], gloss["freq"]
    study_by_sent = gloss["study_by_sent"]
    forms = gloss["forms"]

    # first-occurrence sentence per study lemma; common-lemma collection
    # mirrors gloss3's emoji_common walk (forms resolves surface->key,
    # so no runtime lemmatiser is needed here either).
    from wordfreq import zipf_frequency
    first_sent, commons = {}, {}
    covered = load_general_covered(lang)
    ec = set(gloss.get("emoji_common", {}))
    for sec in book["sections"]:
        for sent in sec["sentences"]:
            text = None
            for lemma in study_by_sent.get(sent["id"], []):
                if lemma not in first_sent:
                    text = text or sentence_text(sent)
                    first_sent[lemma] = text[:240]
            ent_toks = set()
            for a, b, _ in sent.get("ents", []):
                ent_toks.update(range(a, b))
            orth = sent.get("orth", {})
            for i, tok in enumerate(sent["toks"]):
                if i in ent_toks or not is_word(tok):
                    continue
                if sent["pos"][i] in EMOJI_FUNC_POS:
                    continue
                key = forms.get(nfc_lower(orth.get(str(i), tok)))
                if (not key or key in words or key in commons
                        or key in covered or key in ec):
                    continue
                if zipf_frequency(key, lang) >= args.threshold:
                    commons[key] = True

    study_items = [{"lemma": k, "gloss": w["g_en"],
                    "sentence": first_sent.get(k, "")}
                   for k, w in sorted(words.items())]
    common_items = [{"lemma": k} for k in sorted(commons)]
    if args.limit:
        study_items = study_items[:args.limit]
        common_items = common_items[:args.limit]
    print(f"{args.book} ({lang}): {len(study_items)} study lemmas, "
          f"{len(common_items)} common candidates")

    rejected = []
    cache = Cache(HERE / "cache" / f"emoji_book_{args.book}.jsonl",
                  args.mock)
    kept_study = two_stage(study_items, "book", lang, cache, args, rejected)
    write_map(out_path(args, f"emoji_ai_{args.book}.json"),
              meta(args, {"kind": "book-study", "book": args.book,
                          "lang": lang,
                          "source_hash": gloss["source_hash"],
                          "review_to": f"tools/v3/maps/emoji_{args.book}.json"}),
              kept_study)

    rejected_c = []
    cache_g = Cache(HERE / "cache" / f"emoji_general_{lang}.jsonl",
                    args.mock)
    kept_common = two_stage(common_items, "general", lang, cache_g, args,
                            rejected_c)
    merge_general_candidates(lang, kept_common, args,
                             f"--book {args.book}")
    write_rejected(out_path(args, f"emoji_ai_{args.book}_rejected.txt"),
                   rejected + rejected_c)
    print(f"study kept {len(kept_study)}/{len(study_items)}; "
          f"common kept {len(kept_common)}/{len(common_items)} "
          "(-> general candidates)")


# ------------------------------------------------------------ --general

def run_general(args):
    lang = args.lang
    import simplemma
    from wordfreq import top_n_list
    covered = load_general_covered(lang)
    path = HERE / "build" / f"emoji_general_candidates_{lang}.json"
    if path.exists():                     # already decided in earlier runs
        covered |= {k for k in json.loads(path.read_text("utf-8"))
                    if not k.startswith("_")}
    seen, items = set(), []
    for w in top_n_list(lang, args.top):
        if not w.isalpha() or len(w) < 2:
            continue
        lemma = nfc_lower(simplemma.lemmatize(w, lang=lang))
        if lemma in seen or lemma in covered or len(lemma) < 2:
            continue
        seen.add(lemma)
        items.append({"lemma": lemma})
    if args.limit:
        items = items[:args.limit]
    print(f"general ({lang}): {len(items)} candidate lemmas "
          f"from top {args.top}")

    rejected = []
    cache = Cache(HERE / "cache" / f"emoji_general_{lang}.jsonl", args.mock)
    kept = two_stage(items, "general", lang, cache, args, rejected)
    merge_general_candidates(lang, kept, args, f"--general top{args.top}")
    write_rejected(out_path(args, f"emoji_general_{lang}_rejected.txt"),
                   rejected)
    print(f"kept {len(kept)}/{len(items)} "
          f"(review -> tools/v3/maps/emoji_general_{lang}.json)")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", help="book id (per books.json)")
    ap.add_argument("--general", action="store_true",
                    help="frequent-lemma general map candidates")
    ap.add_argument("--lang", default="de", choices=("de", "en"),
                    help="--general language (default de)")
    ap.add_argument("--top", type=int, default=5000,
                    help="--general: wordfreq top-N pool (default 5000)")
    ap.add_argument("--threshold", type=float, default=3.5,
                    help="zipf split study/common — keep = gloss3's")
    ap.add_argument("--model", default="mistral-large-latest")
    ap.add_argument("--limit", type=int, default=0,
                    help="cap candidate count (pilot runs)")
    ap.add_argument("--mock", action="store_true",
                    help="offline plumbing test: curated map echoes as "
                         "answers, grader keeps all, cache untouched")
    args = ap.parse_args()
    if bool(args.book) == args.general:
        ap.error("exactly one of --book / --general")
    if args.book:
        run_book(args)
    else:
        run_general(args)


if __name__ == "__main__":
    main()
