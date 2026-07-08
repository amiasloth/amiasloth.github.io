# Chunker analysis — July 2026 rebuild

**Round 2 (2026-07-08, after debug/test_chnker*.out):** six further changes, all pinned in `test_dump_parses.py`. (1) Closing quotes are now boundaries (`close_quotes`): `…kommen“,` | `sagte der Arzt,`. (2) `nicht` directly before a verb fuses right regardless of the parse (the model hangs it on the modal). (3) A bare infinitive under a modal (`kann … kommen`) no longer gets rank-1 clause edges — it's a verb bracket, one predicate. (4) The pronoun fuse-right rule covers object pronouns too (`aber es | immer wieder vergessen hatte` fixed). (5) English phrasal-verb whitelist for particles the model mislabels as prepositions — unambiguous pairs only (`let in/out`, `wake up`, `give up`; `put on` excluded because "put [on the table]" is a real reading). (6) The pass-2 absorb rescue now scores directions as (severed verb, unlinked side, oversize, gate, boundary strength), where "severed" is dependency-aware (`benign_tail`: parting a verb from its PP is normal, from its object is not) and "linked" prefers the side the fragment syntactically attaches to — this fixed `the door, looked |` and the `and mango, then` clause-comma glue while leaving `Ölfässer, deren stattliche Reihe` intact. Klaus's comma question needed no comma-specific rule: clause commas are already rank-1 walls via verbal-conjunct edges; list commas stay rank-3 and pack. Also fixed: cuts can no longer strand sentence-initial punctuation (`„ | Ich kann`), and the repair pass no longer treats pronouns as offenders nor shifts a chunk down to bare punctuation.


**Update 2026-07-08, after debug/parse_dump.out:** the dump settled the open hypotheses — differently than expected. `Und wenn |`, `während an |` and `nur durch |` were ALL produced by `fallback_split`, not by pass-2 absorb and not by tagger noise: those atoms contain no fusion-clean candidate cut, fallback used fusion only as a third tiebreak behind the crossing count, and the min-word floor then forced the cut right after the fuse-R word. The dump also showed `sich`/`er` orphans exist because a pronoun directly after its verb had no fusion rule at all.

Phase 1 is now implemented in `chunk.py` (dash spacing in `clean()` + dash-as-opener, punctuation-transparent `good_cut`, pronoun-clitic fusion, fusion veto + max+1 stretch in `fallback_split`, starter min 2, `repair_fuse_right` output pass). Two documented behaviors changed intentionally: `auf einen | mit zwei…` now splits at the fusion-clean seam (`auf einen mit zwei magern Schimmeln | bespannten…`) because the old "good" example stranded an article, and fusion-locked spans may now exceed the level max by one word rather than strand a function word. Regression coverage: `test_merge_gates.py` (updated) and the new `test_dump_parses.py`, which replays the dump's REAL parses through hand-built spaCy Docs — both run without models; the Zarathustra tests reproduce Klaus's preferred chunkings exactly. Still to do on the model machine: rebuild, run `chunk_lint.py` before/after, and run `test_chunker.py` / `test_chunker_extended.py`.


Scope: all 32 built files in `docs/data` (5 German + 3 English books × 4 levels, 446k chunks), the two flagged passages (Zarathustra starter/beginner, Birnbaum beginner), and a code-path reading of `tools/chunk.py`. The spaCy models can't load in the sandbox, so parse-level claims are marked *confirmed* (reproduced without a model) or *hypothesis* (verify with `tools/parse_dump.py` on your machine). Two new diagnostic tools were added, no chunker changes: `tools/chunk_lint.py` (static output lint, no spaCy needed) and `tools/parse_dump.py` (parse + pipeline-path dump, run locally).

## Headline numbers (chunk_lint.py)

Share of chunks violating "reads as a slice of one phrase" (statically detectable classes only — real rate is somewhat higher because mixed-constituent chunks like `sein Herz,—und eines Morgens stand` need a parse to detect):

| level | de range | worst offender |
|---|---|---|
| beginner | 1.1–1.9% (Zarathustra 4.9%) | glued dashes |
| intermediate/advanced | 0.3–1.0% | glued dashes |
| **starter** | **18–20% every book, both languages** | lone function words (12–13%) |

Two conclusions up front: the beginner+ pipeline is fundamentally sound — the flagged examples come from four specific, fixable mechanisms, not from spaCy being the wrong strategy. And starter is not "beginner but smaller" — it is structurally broken and needs a design change, not tuning.

## Finding 1 — em-dash gluing: a cleaning bug, not a parsing bug (CONFIRMED)

Both flagged Zarathustra chunkings are downstream of one defect. `clean()` only spaces out `--` when it sits directly between word characters; `Herz,--und` becomes `Herz,—und`, and **both** the German and English tokenizers keep `Herz,—und` / `pictures,—and` as ONE token (reproduced in the sandbox with `spacy.blank`). Consequences cascade:

1. A cut inside a token is impossible — the rank-0 dash cut and the rank-1 `und` coordination cut can never fire.
2. The parser sees a garbage noun-ish token where a clause boundary should be, so the parse of *both* clauses around it is poisoned. That is why beginner glues clause 1's subject to clause 2's verb (`sein Herz,—und eines Morgens stand`) and why the merge gates never got a say — no merge ever happened; the atoms were already wrong.

Impact: 975 chunks in `zarathustra_beginner` alone (3.7%), near-constant across all levels (it happens before chunking), 4,500 chunks corpus-wide, both languages. Highest value-per-line fix in the codebase: either space dashes in `clean()` (`Herz, — und`, arguably better display typography too) or add a tokenizer infix rule for `—` to keep the text byte-identical. Decision below.

## Finding 2 — starter is structurally broken (CONFIRMED mechanism, parse details hypothesis)

`Endlich aber verwandelte | sich | … | er | … | auf, | trat | … | hin` — 12–13% of all starter chunks are a single stranded function word. Three interacting causes:

1. `min_words: 1` makes lone `sich` / `er` / `auf,` legal output.
2. `max_words: 3` makes them near-inevitable: `eines Morgens stand er` is 4 words, so either `er` or `eines Morgens` must be orphaned from `stand`.
3. `fallback_split` ranks **crossings before fusion** (`key = (severs_verb, crossings, good_cut, mid)`). A separable particle, reflexive, or post-verbal pronoun has its head *outside* the span, so the cut right beside it crosses zero internal edges and wins — the seam metric actively *prefers* orphaning exactly the words fusion protects. Same mechanism produces `Vor dem in | dem großen…` in Birnbaum (note: the docstring's own showcase says `Vor dem | in dem großen…`, but the built data shows the cut landing after `in` — the intended and actual behavior have diverged).

Design implication, given your stated priority (meaning over size): starter needs `min_words: 2` plus permission to stretch to 4 when that is what it takes to avoid breaking a fusion (`mit der Morgenröthe auf,` is one unit of meaning; `auf,` alone is noise). And in `fallback_split`, fusion violations should be a veto ahead of the seam count, not a third tiebreak.

## Finding 3 — chunk-final stranded function words at beginner (~1–1.5%)

The `während an |`, `nur durch |`, `Und wenn |`, `die die |`, `sprang und, |` family. Corpus-wide at beginner: 386 severed articles, 347 stranded subordinators, 81 conjunction+comma, plus true preposition strandings. Three distinct mechanisms, none guarded by the merge gates (by design — gates only guard merges):

**3a. Comma masking in `good_cut` (CONFIRMED by code reading).** `good_cut` checks only `toks[i-1]`; when that is a comma it skips the fusion check entirely, so the `und` *behind* the comma is never seen: `ans Fenster und, | weil das Licht…`. Fix: skip back over punctuation to the last content token before testing fuse direction.

**3b. Pass-2 absorb creates fuse-R-final chunks (HYPOTHESIS — parse_dump case 4).** Two adjacent rank ≤ 1 cuts (coordination + subordinator) leave `wenn` as a lone atom; pass 1 may not merge over rank ≤ 1, pass 2 absorbs the undersized `Und` *into* it, reaches `min_words`, and stops — with no check that the result ends on a fuse-right word. Hence the very regular `Und wenn | es ein Gitter wird` / `und als | er ins Haus kam` pattern in every book.

**3c. Parse/tag noise (HYPOTHESIS — parse_dump cases 2–3).** `während an | der andern … lagen,` requires a cut after `an`, which every rule forbids if `an` is parsed as a preposition governing rightward — so the parser almost certainly attached it leftward. Individual mis-parses like this are unfixable case-by-case, which motivates the repair-pass approach below.

## Finding 4 — old orthography degrades the parse (HYPOTHESIS, lower priority)

`de_core_news_lg` is trained on contemporary news text. Zarathustra (1883: *Morgenröthe, giebt, thut*, Swiss-style *ss*) is the worst performer at every level even with dash-glue excluded. A deterministic, token-count-preserving normalization (th→t, giebt→gibt, …) applied to a *parse copy* — cut positions mapped back to the original text, which stays untouched on screen — would be a static, testable experiment. Measure with chunk_lint before/after; only keep it if the delta is real.

## Strategy recommendation

**Keep spaCy. Don't abandon it — demote it.** A pure function-word/regex chunker was considered and rejected: German phrase chunking needs to find finite verbs, verb clusters, and bracket structures, and that cannot be done reliably from closed word lists alone (is *liebe* a verb or noun? only the tagger knows). Swapping parsers (Stanza etc. — also static/deterministic) trades known failure modes for unknown ones at high cost. The actual lesson of the data is a *trust hierarchy*: text cleaning and tokenization (finding 1) and closed-class lexical facts ("an before der is a preposition", finding 3) are far more reliable than dependency labels — so parse-independent layers should be able to overrule the tree, and the quality bar should be enforced on the *output*, not only at cut time.

Proposed order of work, impact-ranked:

1. **Fix dash handling** in `clean()` or via tokenizer infix. Removes ~4,500 bad chunks plus the un-countable parse poisoning around each one. Trivial diff.
2. **Punctuation-transparent `good_cut`** — check the last *content* token before the cut. Removes the `und, |` class.
3. **Lexical repair pass** (new, analogous to `shift_trailing_openers`): after chunking, any chunk ending on a closed-list fuse-right word (article, preposition-before-article, subordinator, coordinator) pushes that word onto the following chunk, merging if the remainder falls under min. Because it runs on output, it catches 3a, 3b, 3c, and any future tagger noise in one place — the quality bar becomes an enforced invariant instead of a property you hope the paths preserve.
4. **`fallback_split`: fusion as veto**, not tiebreak (except in the existing desperation stage). Fixes `Vor dem in |` and most starter orphans.
5. **Starter redesign**: `min_words: 2`, stretch to 4 to close a fusion. Expected to take starter from ~19% to low single digits.
6. Only then, if Zarathustra still lags: orthography normalization experiment (finding 4).

**Make the quality bar executable.** `chunk_lint.py` runs on the built JSON with no dependencies; wire it into `build_data.sh` so every rebuild prints the violation table. Suggested acceptance: beginner+ < 0.5% per book, starter < 3%. It slightly over-counts (some `als ob`-type hits are legitimate line ends) — good enough as a ratchet: the number must only go down.

## To run on your machine (models needed)

```
cd tools && python parse_dump.py > parse_dump.out
```

Dumps tokenization (glued tokens flagged), full parses, and every pipeline intermediate (atoms → coherence → merge → fallback) for the flagged sentences plus the `Und wenn` pattern, and flags final chunks ending on fuse-R words. That output confirms or kills hypotheses 3b, 3c, and the exact parse of the Birnbaum sentence before any fix is written.

## Decisions needed

1. Dash display: is `Herz, — und` (spaced) acceptable on screen, or keep the original `Herz,—und` glued and fix only the tokenizer?
2. Starter: OK to raise min to 2 and stretch max to 4 when a fusion demands it?
3. Zarathustra: OK to parse a normalized copy while displaying the original spelling?
