# Diagnosis — English port of candidate B (2026-07-10)

> STATUS: implemented and verified on `en_core_web_sm` (the model the
> shipped English data uses — see `tools/build_data.sh`). Unlike German,
> the sm model IS the shipping model for English, so this run is
> judgement-grade, not just a smoke test. `out/` holds the sm run for
> Alice / Frankenstein / Velveteen.

Follows `NEXT_SESSION_ENGLISH.md`. The German architecture, DP, nesting,
merge-ladder rungs, and metrics tooling transferred unchanged. Only the
STRENGTH SCORING needed English work: (a) lift the German TIGER labels
that were still literal into per-language config so nothing silently
no-ops or misfires, (b) gate the German-only comma rules off, (c) add
the two English-specific fixes the data demanded (copula binding,
dash isolation). No change to the DP or the nesting.

## Bottom line (owner's verbatim guide)

Chunking must make meaning easier for someone who doesn't know English
well — not confuse them. Every decision below was made on that basis;
the two new rules exist purely because their absence stranded words
from the meaning they belong to.

## What transferred with zero changes

DP length balancer, top-down nesting (levels nest by construction),
max+1 stretch economics, desperation cutter, merge-ladder rungs +
collapse, punct-only-chunk prevention, absorb pass, alnum word counting,
reconstruction invariant, `compare_report.py` / `test_improvements.py`
(only a book-label parameterization added). Parse-independent
punctuation scoring and the en quote sets already in `LANG_CFG`
transferred as-is — Alice uses curly quotes (“ ” ‘ ’), so the straight-
quote-ambiguity exclusion in `close_quotes` is correct and the speech
seam ("…," said Alice) fires cleanly (0 straight-quote misfires observed).

## Ported — German labels lifted into per-language config

`HIER_CFG` (new, in `chunk_hierarchy.py`) holds the labels that were
still German-literal in v1; it is merged into `base.LANG_CFG[lang]` at
load time via `build_cfg()`, so every function sees one dict. The
English half uses spaCy en labels:

| was literal (German)            | now cfg key         | English value          |
|---------------------------------|---------------------|------------------------|
| `dep_ == "oc"` + STTS `BRACKET_TAGS` | `bracket_dep` / `bracket_tags` | `None` / ∅ (no verb-final bracket) |
| `dep_ == "mo"` (adverbial mod)  | `modifier_deps`     | `advmod`, `npadvmod`   |
| `dep_ == "svp"` (sep. prefix)   | `sep_prefix_deps`   | `prt` (phrasal particle) |
| infinitive `("rc","acl","relcl")` | `inf_rel_deps`    | `acl`, `relcl`         |
| `dep_ == "cj"` (coord. clause)  | `cfg["conj_deps"]`  | `conj`                 |
| zu-child `"pm"` / `PTKZU`       | `inf_child_marks` / `inf_child_tags` | ∅ |

`is_verb_bracket` now returns `False` for English (`bracket_dep=None`):
English has no verb-final bracket, and the verb-cluster rule already
keeps "has been seen" whole. `FINITE_TAGS` already carried the English
tags (VBD/VBZ/VBP/MD).

## German-only linguistics, gated OFF for English

**Clause-comma backstops.** German commas are grammar-bearing, so
"comma directly before/after a finite verb = clause seam (85)" is right
there. English commas are prosodic/optional — "However, he went" and
"He went, John said" would misfire — so the whole block is behind
`cfg["clause_comma"]` (True for de, False for en). English clause commas
are instead caught by `clause_edge` from `advcl`/`ccomp`/`relcl`/`mark`
subtree edges, which is parse-driven and correct. The list-comma cap
("big, red | dog") transfers conceptually and stays on. V2-resumption
(", fand er sich") is German-only and off. The extended-prenominal-
attribute lock and pronoun-after-verb fusion ("said she", "thought
Alice") stay on: the first mostly no-ops in English (attributes are
postnominal), the second is dep-guarded and verified correct on Alice's
"said the King / said Alice" inversions.

## English-specific fixes the data demanded

### 1. Copula binding — a "be"-verb must keep its predicate

Root cause (read off recorded strengths): `she was ‖65‖ up to her chin
in salt water` — the position after the copula scored **65** ("verb-
attached PP", a detachable adjunct) because "up" is a preposition whose
head is "was". But "up to her chin" is the **predicate** of the copula,
not an adjunct, and the 65 seam made the DP strand `she was |` from its
own meaning. Same class: `it would be | of very little use`, `she was |
in the pool of tears`, `you were all | in bed`, `and was just | in time`.

Fix (`COPULA_BIND`, on for en via `copula_lemmas={"be"}`, empty and thus
a no-op for de):
- a PP whose head lemma is "be" scores **10** (tight), like a noun-
  attached PP, not 65;
- `severs_verb_tail` drops `prep`/`acomp`/`attr`/`oprd`/`advmod`/
  `npadvmod` from the benign set when the verb is a copula, so
  stranding a "be"-verb from a predicate PP, predicate adjective ("so
  tired"), or predicate nominal ("a rabbit") takes the sever penalty.

Both are exempt at seams ≥ 85, so a copula still splits before a full
*clause* ("Her first idea was | that she had somehow fallen" stays —
a that-clause reads fine). Result: `she was up to her chin | in salt
water`, `it would be of very little use`, `you were all in bed`.

Blast radius (Alice, sm): advanced 2, intermediate 22, beginner 28,
starter 8 sentences of 1528 — every sampled change an improvement; the
handful of lateral cases ("a person of authority" splitting one way vs
another) are length-balance choices, not confusions.

### 2. Desperation must never isolate a word-less span

6 pure-punctuation chunks appeared at **starter** only — lone em-dashes:
`— Why,` split to `—` | `Why,`; `mad — at least` to `mad` | `—` |
`at least`; `“ — as far` to `“ —` | `as far`. The DP is immune (0-word
span = ∞ cost), but the **desperation cutter ignores fusion by design**
and, at the tightest level (max 3), split oversized spans at a dash,
isolating it. Alice is dialogue-dash-heavy; Kafka rarely leads with a
dash, so German never surfaced this. Fix: desperation candidates now
require `wcount(a,k) > 0 and wcount(k,b) > 0`, so a dash can never
become its own chunk. It attaches to a neighbour instead
(`— Why,` | `I hadn’t to bring`).

### 3. Contractions (verified, guard added)

spaCy splits "won't"→"wo"+"n't", "she'd"→"she"+"'d". Fusion already
forbade cutting between the halves (neg/aux/case in `fused_deps`,
subject-pronoun-before-verb leans right), but per the handoff a parse-
independent guarantee was added to `valid_break`: never cut where the
raw text has no whitespace between the two tokens. Verified: **0**
contraction splits across all three books.

## Verification (Alice 1500 + Frankenstein 3356 + Velveteen 226 sents)

All must be 0, all are 0: reconstruction failures, pure-punct chunks,
over-cap chunks (beyond max+1), contraction splits, nesting violations
(coarser ⊆ finer, and rungs ⊆ advanced), chunks starting with stray
punctuation. Alignment mismatches vs shipped data: 0.

Aggregate vs the shipped English chunker (Alice, `out/metrics.md`):

| level        | CV (cur→candB) | worst chunk (cur→candB) |
|--------------|----------------|-------------------------|
| starter      | 0.32 → 0.29    | 7 → 4 (= max+1)         |
| beginner     | 0.34 → 0.29    | 7 → 6                   |
| intermediate | 0.38 → 0.29    | 9 → 8                   |
| advanced     | 0.38 → 0.29    | 13 → 12 (= hard cap)    |

Length variance drops at every level and nothing exceeds the hard cap
(the current chunker overshoots to 7 at starter and 13 at advanced).
Nesting violations: candidate B 0, current chunker 243 — the current
chunker cuts levels independently, which is what blocks adaptive rungs
today. Progressive rungs: 450 ladders, all nested, no duplicates.

## What is NOT changed (per process)

Only the scoring layer and the desperation candidate filter were
touched. The DP, nesting, rung machinery, and every invariant are the
accepted German design. `tools/` is untouched — the English config is
added in `chunk_hierarchy.py`, not in `tools/chunk.py`.

## Flags (all owner-tunable, shown both ways in test_improvements.py)

- `COPULA_BIND = True` — English copula predicate binding (fix 1). Off
  → German behaviour, which re-strands `she was | up to her chin`.
- `DESP_CROSSINGS`, `CHEAP_STRONG_CUTS` — inherited from German, on.
- `clause_comma` (cfg) — German comma backstops, off for English.

## Open questions for the owner

1. Copula binding lateral cases: a few long sentences shift where they
   balance ("a person of authority among them"). Read section HTML and
   confirm none read worse than before.
2. sm vs lg: the German session found lg separated more cases and fixed
   parse-driven misfires. English *ships* on sm, so sm is the right
   judge here — but if a future English book wants lg, the parse-
   independent backstops (punctuation, quote seams, copula binding,
   dash isolation) are exactly the ones that carried German across the
   sm/lg gap, so they should hold.
3. Whether the copula rule should extend to linking verbs beyond "be"
   (become/seem/look/feel). Left out for now (conservative — those are
   rarer and over-binding risks its own confusion); trivially added to
   `copula_lemmas` if the owner wants it.
