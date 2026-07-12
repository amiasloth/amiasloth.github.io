#!/usr/bin/env python3
"""
tools/v3/gloss3.py — offline glossary builder (v3 layout).

Realises the 06 glossary pipeline in the PINNED v3 schema
(technical/v3_discussion/02_v3_data_schema.md): reads a BOOK FILE
produced by build3.py (tokens + ents are the single source of truth) and
emits docs/data3/gloss/<book>.json with words / forms / freq /
study_by_sent / sections.  Deterministic, offline; the network is used
exactly once (--fetch) to vendor the FreeDict dictionary.

Stable contract note (06 spec): a later Mistral pass may add `g_de`
learner definitions and fill the `overrides` sense-exception layer; both
are additive keys, never a reshape.

Byproducts (small-batch review + the orthography pass):
  tools/v3/build/gloss_misses_<book>.txt    rare lemmas with no dict hit
  tools/v3/build/orth_candidates_<book>.txt archaic->modern proposals
      (dictionary-miss detection per 00_v3_overview; a human reviews
      these into an --orth-subst list for build3.py)

Usage:
  python3 gloss3.py --fetch                       # one-time vendoring
  python3 gloss3.py --book ../../docs/data3/de/kafka.json \
      [--out ../../docs/data3/gloss/kafka.json] [--threshold 3.5]

Languages: de (FreeDict deu-eng, de->en glosses) and en (WordNet 3.0
dictd, en->en definitions).  The archaic-orthography machinery is
German-only.
"""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))        # tools/ (emoji_map.py, read-only)
from emoji_map import EMOJI                 # noqa: E402

import simplemma                            # noqa: E402
from wordfreq import zipf_frequency         # noqa: E402

SCHEMA = 3
VENDOR = HERE / "vendor"

# UPOS tags whose lemmas never enter the common-word emoji channel
# (emoji_common, schema rev 3.1): function words — articles, pronouns,
# adpositions, conjunctions, particles, auxiliaries — would otherwise
# fire on nearly every chunk with whatever junk a map carries for them.
EMOJI_FUNC_POS = {"DET", "PRON", "ADP", "CCONJ", "SCONJ", "CONJ",
                  "PART", "AUX"}

# Per-language dictionary config.  de: FreeDict deu-eng (de->en gloss).
# en: WordNet 3.0 in dictd format (en->en definitions — same-language
# glosses, which is also the owner-preferred direction).  Both are
# dictd, so one index/data reader serves both; only the entry FORMAT
# parser differs.
DICTS = {
    "de": {
        "url": ("https://download.freedict.org/dictionaries/deu-eng/"
                "1.9-fd1/freedict-deu-eng-1.9-fd1.dictd.tar.xz"),
        "archive": "freedict-deu-eng-1.9-fd1.dictd.tar.xz",
        "version": "freedict-deu-eng-1.9-fd1",
        "index": VENDOR / "deu-eng" / "deu-eng.index",
        "dict": VENDOR / "deu-eng" / "deu-eng.dict.dz",
        "format": "freedict",
    },
    "en": {
        "url": ("http://ftp.debian.org/debian/pool/main/w/wordnet/"
                "dict-wn_3.0-41_all.deb"),
        "archive": "dict-wn_3.0-41_all.deb",
        "version": "wordnet-3.0-dictd (dict-wn 3.0-41)",
        "index": VENDOR / "wn" / "wn.index",
        "dict": VENDOR / "wn" / "wn.dict.dz",
        "format": "wordnet",
    },
}

B64ALPH = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


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


# ------------------------------------------------------------ vendoring

def ar_members(path):
    """Minimal Unix ar reader (a .deb is an ar archive) — 60-byte
    headers: name[16] mtime[12] uid[6] gid[6] mode[8] size[10] magic[2]."""
    blob = Path(path).read_bytes()
    assert blob[:8] == b"!<arch>\n"
    i = 8
    while i + 60 <= len(blob):
        name = blob[i:i + 16].decode().strip().rstrip("/")
        size = int(blob[i + 48:i + 58].decode().strip())
        yield name, blob[i + 60:i + 60 + size]
        i += 60 + size + (size & 1)


def fetch_vendor():
    import io
    import tarfile
    import urllib.request
    VENDOR.mkdir(parents=True, exist_ok=True)
    for lang, cfg in DICTS.items():
        if cfg["index"].exists():
            print(f"{lang}: already vendored ({cfg['version']})")
            continue
        archive = VENDOR / cfg["archive"]
        if not archive.exists():
            print(f"downloading {cfg['url']} ...")
            urllib.request.urlretrieve(cfg["url"], archive)
        if archive.suffix == ".deb":
            for name, blob in ar_members(archive):
                if name.startswith("data.tar"):
                    with tarfile.open(fileobj=io.BytesIO(blob)) as tf:
                        out = cfg["index"].parent
                        out.mkdir(parents=True, exist_ok=True)
                        for m in tf.getmembers():
                            base = Path(m.name).name
                            if base in (cfg["index"].name, cfg["dict"].name):
                                (out / base).write_bytes(
                                    tf.extractfile(m).read())
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(VENDOR)
        print(f"vendored -> {cfg['index'].parent}")


# ------------------------------------------------------------ dictd access

def b64int(s):
    v = 0
    for c in s:
        v = v * 64 + B64ALPH.index(c)
    return v


def load_dict(lang):
    """headword(lower) -> [(offset, length), ...] of ALL its entry blocks
    (homographs: FreeDict indexes 'Flimmern' the noun and 'flimmern' the
    verb under the same folded key — the caller picks by case).  Data =
    the whole decompressed .dict (dictzip is gzip-compatible)."""
    idx_path = DICTS[lang]["index"]
    dict_path = DICTS[lang]["dict"]
    if not idx_path.exists():
        sys.exit(f"vendored dictionary missing — run: {sys.argv[0]} --fetch")
    index = {}
    with open(idx_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 3:
                continue
            hw = nfc_lower(parts[0].strip())
            if hw:
                index.setdefault(hw, []).append(
                    (b64int(parts[1]), b64int(parts[2])))
    data = gzip.open(dict_path).read()
    return index, data


TAG_RE = re.compile(r"<[^>]*>|\[[^\]]*\]|\{[^}]*\}")


WN_MARK = re.compile(r"\b(n|v|adj|adv|s)?\s*(\d+):\s*")
UPOS2WN = {"NOUN": "n", "PROPN": "n", "VERB": "v", "AUX": "v",
           "ADJ": "adj", "ADV": "adv"}


def parse_entry_wordnet(raw, want=None):
    """(headword, one_line_gloss) from a WordNet dictd block:
    headword line, then '  n 1: definition [syn: ...] "example"' with
    indented wrap lines, senses grouped per part of speech.  `want`
    (n/v/adj/adv) picks the first sense of THAT part of speech — the
    caller passes the occurrence's actual UPOS from the book file, so
    'peep' used as a verb glosses as looking, not as a bird cry.
    Fallback: first sense of the block (WordNet sense order is not
    frequency order, hence the whole exercise)."""
    lines = raw.decode("utf-8").split("\n")
    head = lines[0].strip()
    body = " ".join(l.strip() for l in lines[1:])
    senses, cur = {}, None
    marks = list(WN_MARK.finditer(body))
    for m, nxt in zip(marks, marks[1:] + [None]):
        if m.group(1):
            cur = "adj" if m.group(1) == "s" else m.group(1)
        if m.group(2) == "1" and cur and cur not in senses:
            t = body[m.end(): nxt.start() if nxt else len(body)]
            t = re.split(r'\[syn|"|;', t)[0]
            senses[cur] = " ".join(t.split()).strip(" ,;")[:80]
    if not senses:
        return head, ""
    if want in senses:
        return head, senses[want]
    return head, next(iter(senses.values()))


WN_POS_TAGS = {"n", "v", "adj", "adv"}


def parse_entry(raw):
    """(display_headword, one_line_gloss, pos_tags) from a FreeDict
    entry block.  pos_tags ⊆ {n,v,adj,adv}, from the headword line's
    <neut, n, sg> / <v, trans> annotation — used to pick the homograph
    entry matching the occurrence's actual UPOS (Leben the noun vs
    leben the verb), which beats guessing from lemma capitalisation."""
    lines = raw.decode("utf-8").split("\n")
    head = lines[0].split("/")[0].strip() or lines[0].strip()
    m = re.search(r"<([^>]*)>", lines[0])
    tags = ({t.strip() for t in m.group(1).split(",")} & WN_POS_TAGS
            if m else set())
    for ln in lines[1:]:
        t = ln.strip()
        if not t or t.startswith(('"', "Note", "Synonym", "see:", "-")):
            continue
        t = TAG_RE.sub("", t)
        t = re.sub(r"^\d+[.)]\s*", "", t)
        t = " ".join(t.split()).strip(" ,;")
        if t:
            t = t.split(";")[0]
            syns = [p.strip() for p in t.split(",") if p.strip()]
            return head, ", ".join(syns[:3])[:80], tags
    return head, "", tags


# ------------------------------------------------------------ archaic forms

def _add(seen, out, x):
    if x not in seen:
        seen.add(x)
        out.append(x)


def variants(k):
    """SAFE archaic-orthography variants of a lowercase string, tried
    only after a dictionary miss and allowed to feed the LIVE gloss
    (Thür->Tür, daß->dass, sey->sei).  Safe = a false hit is next to
    impossible in German."""
    seen, out = {k}, []
    _add(seen, out, k.replace("th", "t"))
    _add(seen, out, k.replace("ey", "ei"))
    _add(seen, out, k.replace("th", "t").replace("ey", "ei"))
    _add(seen, out, k.replace("ß", "ss"))
    return out


def propose_variants(k):
    """AGGRESSIVE variants (gieng->ging, Waaren->Waren).  These can hit
    unrelated real words (beeilen -> "beilen" -> Beil!), so they are
    NEVER glossed from — they only feed the orth_candidates report,
    which a human reviews into build3.py's --orth-subst list."""
    seen, out = {k}, []
    _add(seen, out, k.replace("ie", "i"))           # gieng -> ging
    _add(seen, out, re.sub(r"([aeo])\1", r"\1", k))  # Waaren -> Waren
    return out


# ------------------------------------------------------------ main pass

def run(args):
    book = json.loads(Path(args.book).read_text("utf-8"))
    lang = book.get("lang")
    if lang not in DICTS:
        sys.exit(f"gloss3.py: no dictionary configured for lang {lang!r}")
    index, data = load_dict(lang)
    wordnet = DICTS[lang]["format"] == "wordnet"

    def entry(key, lemma_display, want=None):
        """Pick among the key's homograph entries.  `want` (n/v/adj/adv
        from the occurrence's baked UPOS) narrows to entries of that
        part of speech first — FreeDict via headword tags, WordNet via
        its per-POS sense blocks; then exact-case headword match (verb
        'flimmern' over noun 'Flimmern'); then first usable entry."""
        if wordnet:
            usable = [(h, g) for h, g in
                      (parse_entry_wordnet(data[off:off + ln], want)
                       for off, ln in index[key]) if g]
        else:
            parsed = [parse_entry(data[off:off + ln])
                      for off, ln in index[key]]
            usable = [(h, g, t) for h, g, t in parsed if g]
            if want:
                usable = ([e for e in usable if want in e[2]] or usable)
            usable = [(h, g) for h, g, _ in usable]
        if not usable:
            return None, None
        for h, g in usable:
            if h == lemma_display:
                return h, g
        return usable[0]

    zipf_cache = {}

    def zipf(k):
        if k not in zipf_cache:
            zipf_cache[k] = zipf_frequency(k, lang)
        return zipf_cache[k]

    lemma_cache = {}

    def lemmatize(tok):
        if tok not in lemma_cache:
            lemma_cache[tok] = simplemma.lemmatize(
                unicodedata.normalize("NFC", tok), lang=lang)
        return lemma_cache[tok]

    resolve_cache = {}                       # surface_lower -> (key, archaic)

    def resolve(surface_lower, lemma_lower):
        """Final lemma KEY for a surface form.  Direct lemma when common
        or in the dictionary; otherwise archaic variants of the surface
        (re-lemmatised: gieng->ging->gehen) then of the lemma."""
        if surface_lower in resolve_cache:
            return resolve_cache[surface_lower]
        res = (lemma_lower, False)
        if lang == "de" and lemma_lower not in index \
                and zipf(lemma_lower) < args.threshold:
            found = False
            for v in variants(surface_lower):
                l2 = nfc_lower(lemmatize(v))
                if l2 in index:
                    res, found = (l2, True), True
                    break
            if not found:
                for v in variants(lemma_lower):
                    if v in index:
                        res = (v, True)
                        break
        resolve_cache[surface_lower] = res
        return res

    words, forms, freq = {}, {}, {}
    study_by_sent, sections_out = {}, []
    misses = {}                              # key -> set of surfaces
    orth_cand = {}                           # archaic surface -> (key, head)
    n_tokens = 0
    emoji_common = {}                        # common-lemma emoji channel
    ec_seen = set()                          # common keys already decided

    emoji_map = {}
    if args.emoji_map:
        emoji_map = json.loads(Path(args.emoji_map).read_text("utf-8"))

    def pick_emoji(key):
        """Emoji source precedence (2026-07-12): a REVIEWED map (later:
        the Mistral-reviewed one) beats the curated emoji_map.py, but
        the curated map beats a GENERATED CLDR map standing in for the
        reviewed one (--emoji-map-generated) — hand-picked beats
        auto-derived, auto-derived fills the rest."""
        cur = EMOJI[lang].get(key, "")
        mapped = emoji_map.get(key, "")
        if args.emoji_map_generated:
            return cur or mapped
        return mapped or cur

    for sec in book["sections"]:
        sec_study, sec_seen = [], set()
        for sent in sec["sentences"]:
            ent_toks = set()
            for a, b, _ in sent.get("ents", []):
                ent_toks.update(range(a, b))
            orth = sent.get("orth", {})
            sent_study, sent_seen = [], set()
            for i, tok in enumerate(sent["toks"]):
                if i in ent_toks or not is_word(tok):
                    continue
                n_tokens += 1
                # baked orth (reviewed substitution list) wins: lookup
                # runs on the MODERN form per the pinned schema; the
                # original surface still maps in `forms` so a tap on
                # the displayed old spelling resolves too.
                mod = orth.get(str(i), tok)
                surf = nfc_lower(mod)
                lemma = lemmatize(mod)
                key, archaic = resolve(surf, nfc_lower(lemma))
                forms[surf] = key
                forms[nfc_lower(tok)] = key
                if zipf(key) >= args.threshold:
                    # common word: not study material — but it may still
                    # carry the chunk-emoji FALLBACK channel (restores
                    # v1 emoji density; 2026-07-12).  Function words are
                    # guarded out by POS so ein/eine/und can never fire.
                    if (key not in ec_seen
                            and sent["pos"][i] not in EMOJI_FUNC_POS):
                        ec_seen.add(key)
                        e = pick_emoji(key)
                        if e:
                            emoji_common[key] = e
                    continue
                if key not in index:
                    misses.setdefault(key, set()).add(tok)
                    # report-only proposal from the aggressive variants —
                    # never glossed from (see propose_variants); German only
                    for v in propose_variants(surf) if lang == "de" else []:
                        l2 = nfc_lower(lemmatize(v))
                        if l2 in index:
                            h, g = entry(l2, lemmatize(v))
                            if g:
                                orth_cand[tok] = (l2, h + " [UNVERIFIED]")
                            break
                    continue
                if key not in words:
                    # sense choice follows the FIRST rare occurrence's POS.
                    # German ADV maps to adj: German adjectives are used
                    # adverbially unmarked ("lächelte närrisch"), and the
                    # base-adjective gloss is the vocabulary item — the
                    # <adv> entries give awkward English ("clownishly",
                    # "unhurtly").  True adverbs (gern) have only adv
                    # entries and reach them via the pool fallback.
                    want = UPOS2WN.get(sent["pos"][i])
                    if lang == "de" and want == "adv":
                        want = "adj"
                    head, g_en = entry(key, lemma, want)
                    if not g_en:             # no entry with a usable line
                        misses.setdefault(key, set()).add(tok)
                        continue
                    words[key] = {"l": head, "g_en": g_en,
                                  "e": pick_emoji(key)}
                    freq[key] = round(zipf(key), 2)
                if archaic:
                    orth_cand[tok] = (key, words[key]["l"])
                if key not in sent_seen:
                    sent_seen.add(key)
                    sent_study.append(key)
                if key not in sec_seen:
                    sec_seen.add(key)
                    sec_study.append(key)
            if sent_study:
                study_by_sent[sent["id"]] = sent_study
        sections_out.append({"title": sec["title"], "study": sec_study})

    out = {
        "schema": SCHEMA,
        "generator": f"gloss3.py@{git_short()}",
        "lang": lang,
        "source_hash": book["source_hash"],
        "dict_version": DICTS[lang]["version"],
        "words": words,
        "forms": forms,
        "freq": freq,
        "emoji_common": emoji_common,
        "study_by_sent": study_by_sent,
        "overrides": {},
        "sections": sections_out,
    }
    out_path = Path(args.out) if args.out else (
        Path(args.book).parent.parent / "gloss" / Path(args.book).name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False,
                                   separators=(",", ":")), encoding="utf-8")

    build_dir = HERE / "build"
    build_dir.mkdir(exist_ok=True)
    bid = book["id"]
    miss_path = build_dir / f"gloss_misses_{bid}.txt"
    miss_path.write_text(
        "".join(f"{k}\t{', '.join(sorted(v))}\n"
                for k, v in sorted(misses.items())), encoding="utf-8")
    orth_path = build_dir / f"orth_candidates_{bid}.txt"
    orth_path.write_text(
        "".join(f"{s}\t{h}\t(lemma key: {k})\n"
                for s, (k, h) in sorted(orth_cand.items())), encoding="utf-8")

    print(f"{bid}: word_tokens={n_tokens} forms={len(forms)} "
          f"glossed_lemmas={len(words)} misses={len(misses)} "
          f"archaic_hits={len(orth_cand)} emoji_common={len(emoji_common)}")
    print(f"  -> {out_path}\n  -> {miss_path}\n  -> {orth_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", help="book file produced by build3.py")
    ap.add_argument("--out", default=None,
                    help="output path (default: sibling gloss/<book>.json)")
    ap.add_argument("--threshold", type=float, default=3.5,
                    help="zipf below which a lemma is glossed (default 3.5)")
    ap.add_argument("--emoji-map", default=None,
                    help="reviewed {lemma: emoji} JSON — overrides the "
                         "curated fallback; the future AI-drafted map "
                         "uses this same entry point")
    ap.add_argument("--emoji-map-generated", action="store_true",
                    help="the --emoji-map file is the GENERATED CLDR "
                         "map standing in for a reviewed one: curated "
                         "emoji_map.py wins collisions instead")
    ap.add_argument("--fetch", action="store_true",
                    help="download + extract the FreeDict dictionary")
    args = ap.parse_args()
    if args.fetch:
        fetch_vendor()
        if not args.book:
            return
    if not args.book:
        ap.error("--book is required (or use --fetch alone)")
    run(args)


if __name__ == "__main__":
    main()
