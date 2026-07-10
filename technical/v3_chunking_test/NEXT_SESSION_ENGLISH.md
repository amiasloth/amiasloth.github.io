# Handoff: porting the chunking experiment to English

Written at the end of the German session (2026-07-10). German
candidate B is owner-accepted (see DIAGNOSIS.md for the full history:
4 review rounds). This file is what the English session needs to know.

## State of the code

`chunk_hierarchy.py` is the accepted German implementation:
break-point strengths → nested DP levels (advanced→starter) →
merge-ladder rungs with independent-merge collapse. Flags
DESP_CROSSINGS and CHEAP_STRONG_CUTS are both ON (owner-approved).
`compare_report.py` and `test_improvements.py` are language-agnostic
apart from defaults (book id, data dir).

## Transfers as-is (language-independent — do NOT redesign)

- The whole architecture: strengths once, DP length balancer, top-down
  nesting, max+1 stretch economics, desperation (sever → fusion grade
  → edge crossings → balance), merge-ladder rungs + collapse_ladder,
  punct-only-chunk prevention (0-word span = ∞ cost), absorb pass for
  stray-quote "sentences", alnum-only word counting, reconstruction
  invariant, the metrics/report tooling and its invariant checks.
- Parse-independent punctuation scoring: strong punct 100, paired
  em-dashes (open cuts before / close cuts after), closing-quote →
  narration seam 90 (en cfg already has the right quote sets in
  tools/chunk.py LANG_CFG).
- The DP weights (W_LEN/W_CUT/W_PREF/W_RUNT/W_STRETCH, 0.3 cheap
  factor). Start with the German values; only touch after reading.

## Needs porting — TIGER labels are hardcoded in places

`break_strengths` and helpers read most labels from cfg, but several
German TIGER labels appear LITERALLY and silently no-op or misfire on
English (spaCy en uses nsubj/dobj/advcl/relcl/mark/cc/conj/prep/…):

- `t.dep_ == "mo"` (adverbial modifier signal, ADP attachment tests
  `("mo","op","pg","cvc")`, `("mnr","pg","ag")`) — EN equivalents:
  `advmod`/`npadvmod`; verb-attached PP = `prep` on VERB, noun-attached
  = `prep` on NOUN (en cfg's benign_tail/fused sets differ too).
- `is_verb_bracket`: `dep_ == "oc"` — EN has no verb-final bracket;
  auxiliaries are contiguous and the verb-cluster rule already covers
  "has been seen". The function will no-op on EN: fine, but don't
  delete it — parameterize.
- infinitive tight-binding test `("rc","acl","relcl")` — the en half
  ("acl","relcl") is already there.
- `"svp"` (separable prefix) — EN analog is `prt` (verb particle,
  "set out"); en cfg's `phrasal` whitelist handles mislabeled ones.
- FINITE_TAGS already contains some EN tags (VBD/VBZ/VBP/MD) but the
  German clause-comma backstops built on them DON'T transfer (below).

Best first step: lift every literal label into a per-language dict
(extend base.LANG_CFG-style config) BEFORE judging any English output,
otherwise you'll diagnose ghosts.

## Do NOT port blindly — German-specific linguistics

1. **Clause-comma backstops.** German commas are grammar-bearing;
   "comma directly before/after a finite verb = clause seam (85)" is
   correct there. English commas are prosodic/optional — "However, he
   went" and "He went, John said" would misfire. EN clause detection
   should lean on `advcl`/`ccomp`/`relcl`/`mark` subtree edges (already
   in en cfg) and NOT on comma-adjacent-verb heuristics.
2. **Comma classes.** The German trichotomy (clause 85 / apposition 60
   / NP-list 15) needs EN re-derivation. The list-comma cap (severing
   "big, red | dog" style adjective lists) transfers conceptually;
   the clause-comma promotion does not (see 1).
3. **V2-resumption rule** (", fand er sich") — meaningless in EN.
4. **Extended prenominal attributes** ("vor Befriedigung tränenden
   Augen" lock) — barely exists in EN (attributes are postnominal);
   the ADJ-subtree lock will mostly no-op. Harmless, keep.
5. **Pronoun-after-verb fusion** ("stand er") — EN books here are
   19th-century: "said she", "thought Alice" inversions are common
   and the rule is dep-guarded, so keep it, but VERIFY on Alice
   dialogue: "said the King/Queen/Alice" is the single most frequent
   pattern in the book.

## English-specific things to look out for

- **The EN build uses en_core_web_sm** (see tools/build_data.sh) — a
  much weaker parse than de lg. Expect more parser mis-attachments;
  the parse-independent backstops mattered in German and EN will need
  its own (punctuation, quote seams). Consider proposing
  en_core_web_lg for the experiment to separate "bad rule" from "bad
  parse" — that distinction drove most German round-2/3 fixes.
- Gutenberg EN texts mark italics as _underscores_ — check how the
  tokenizer treats them (stray punct-ish tokens could recreate the
  "—," class of bugs; the absorb pass should catch, verify).
- Contractions: spaCy splits "won't" → "wo"+"n't", "she'd" →
  "she"+"'d". Word counting slices raw text on whitespace so counts
  stay right, but fusion must never allow a cut between the halves —
  they're not whitespace-separated, so the desperation word-boundary
  check already forbids it. Verify with a test sentence anyway.
- Dialogue-heavy Alice: straight vs curly quotes, quotes closed after
  punctuation ('"…?" said Alice'), nested quotes. The de session hit
  spaCy splitting lone closing quotes into own "sentences" — absorb
  pass handles it; EN will hit the same with different characters.
- Baselines for comparison: docs/data/en/{alice,frankenstein,
  velveteen}_*.json. compare_report.py needs --data docs/data/en and
  --book alice (and the hierarchy run needs the en skip-until regexes
  from tools/build_data.sh).

## Process that worked (keep it)

1. Implement → smoke-test mechanics on sm → owner runs lg/full model
   and commits `out/` → judge ONLY on that.
2. Diagnose from the recorded per-break strengths in the JSON (align
   token indices with `spacy.blank(lang)` — tokenization is
   model-independent) before touching code.
3. Fix the SCORING layer; never patch outcomes into the DP/nesting.
4. Every change: show before/after on the owner's flagged sentences +
   blast-radius counts per level (test_improvements.py pattern), then
   let the owner judge. Balance test: "can it break working parts vs
   will it improve" — when in doubt, make it a flag and show both.
5. Owner's bottom line, verbatim guide for every decision: chunking
   should make the meaning easier to understand for people who don't
   understand the language very well — not confuse them.

## Owner decisions already made (don't relitigate)

- Candidate B accepted for German; A (old chunker) superseded; C is a
  UI decision on top of B's data (breaks+strengths ship, DP portable
  to JS).
- Rungs: merge ladder over advanced, independent merges collapsed,
  no repetition in the app (dedup by cut-set equality).
- CHEAP_STRONG_CUTS on, crossing-aware desperation on.
- Levels: starter 2/2/3, beginner 2/3/5, intermediate 2/5/8,
  advanced 3/8/12 (min/target/max), max+1 stretch allowed.
