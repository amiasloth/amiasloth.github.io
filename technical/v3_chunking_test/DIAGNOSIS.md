# Diagnosis — owner review of the lg run (2026-07-10)

> STATUS: all problems below are addressed in chunk_hierarchy.py v2
> (see "v2 fixes" at the end of this file and RESULTS.md).
> `out/` currently holds an sm smoke run again — rerun
> `run_experiment.sh` with lg before judging boundaries.

Verdict from review: candidate B improves sometimes (9, 11, variance,
caps), regresses on specific boundaries (1, 2, 7, 8). Every regression
traces to the STRENGTH SCORING, not to the DP or the nesting. That's
the good news: the current chunker's German rules can be ported into
the scoring layer while keeping the hierarchy machinery (= owner's
question 3: yes).

All evidence below is read from the recorded per-break strengths in
`out/hierarchy_kafka.json` (lg run), section 1.

## Problem 1 — German clause commas score as bare commas (root cause #1)

Sentence 1: `… Träumen ‖5‖ erwachte , ‖55‖ fand … ‖65‖ in seinem Bett
‖80‖ zu einem …`

The comma after "erwachte," got 55 (bare comma). The Als-clause is
dep `mo` in TIGER — my `clause_deps` = {rc, oc, par, re} (copied from
tools/chunk.py's cfg) misses adverbial/conditional clauses entirely,
so their edges never get 80. A 65 PP cut then beats the 55 comma by
~0.4 cost and the DP splits mid-clause. Same cause for "wenn er den
Kopf ein wenig hob," in sentence 2 (its closing comma: 55).

Fix: clause = any subtree headed by a verb that is not the sentence
root (covers mo-clauses with a `cp` child, i.e. Als/wenn/weil/daß…),
both edges 85. Extra German rule, nearly free: comma directly followed
by a finite verb is the verb-second resumption seam (", fand er sich")
— always strong. tools/chunk.py gets this right via its rank-1 marker
+ clause-edge logic; that's the "manual" feel.

## Problem 2 — all commas are equal (they aren't)

Sentence 2: `… seinen gewölbten , ‖55‖ braunen , ‖55‖ von
bogenförmigen …` — the list comma inside the NP ("gewölbten, braunen,
… Bauch") scored the same 55 as the clause comma after "hob,". The DP
then chose "braunen, | von bogenförmigen … Bauch" (severs coordinated
adjectives from their noun — confusing, as reviewed) over the
linguistically right "hob, |" because lengths balanced better.

Fix: comma classes. Clause-closing comma ≈ 85 (problem 1), apposition
comma ≈ 60, list comma joining attributive ADJs / NPs inside one NP
≈ 15 (below PP strength, so it's only used under length pressure).
German commas are grammar-bearing — this IS the rule-based layer the
owner asked for.

## Problem 3 — NP right edges were never scored

Sentence 3: `Seine vielen , ‖55‖ im Vergleich ‖20‖ zu seinem … Umfang
‖20‖ kläglich dünnen Beine ‖5‖ flimmerten …`

The subject-NP/verb seam (before "flimmerten") got 5 — desperation —
because I only score LEFT edges of subj/obj subtrees. So the DP cut
inside the extended participial NP instead of after it. Fix: score
both edges (right edge of subject before the finite verb ≈ 45).
Owner note "verb can go to the shorter side": once this seam exists
as a candidate, the DP's balance term does exactly that.

## Problem 4 — paired em-dashes: closing dash treated as opener

Sentence 7: `… war ‖100‖ — Samsa war Reisender ‖100‖ — , ‖55‖ hing …`
produced the lone-punct chunk "—,". My rule "cut before any dash =
100" is right for the OPENING dash but wrong for the CLOSING one — it
must fuse left (cut goes after "—," not before "—"). tools/chunk.py
handles this with rank-0 "around parentheses" + absorb_punct_chunks;
candidate B has no punct-absorption pass at all. Fix: pair dashes
within the sentence (open/close like quotes) + port
absorb_punct_chunks.

## Problem 5 — punctuation counts as words

word_count() splits on whitespace, so "— ," = 2 "words". This skews
the DP length costs around every parenthetical and quote. Fix: count
only tokens containing a letter/digit.

## Problem 6 — halves rung: strength-lexicographic, non-recursive

Sentence 11: rung cut at the 65 PP ("auch | auf die rechte") far off
center instead of the 55 comma near the middle — the picker maximizes
strength first, position second, so a 65 at position 6/19 beats a 55
at 12/19. Fix: score = strength − λ·off-center. (After problem 1's
fix the comma is 85 and wins anyway.)

Owner question 1 (halve → thirds → more for monsters like the
"Wohnzimmertür" sentence, no rung for short ones): the hierarchy gives
this for free — recursively split at the strongest remaining break
until every part ≤ ~N words. Rung count then adapts: 0 extra rungs
for short sentences, 1 (halves) for medium, 2+ (quarters via repeated
halving) for the extreme ones. This matches the discussion doc's
"rung count should adapt to sentence length".

## What is NOT broken

- DP balancer + nesting: variance/cap wins are real (CV 0.27–0.28 vs
  0.38 everywhere, nothing beyond max+1, levels reach their targets)
  and survive all fixes above, since fixes touch only scoring and
  post-passes.
- Reconstruction invariant, alignment, level separation.

## Conclusion

Candidate B ≠ wrong architecture; candidate B with a NAIVE strength
function. The strength function is exactly where tools/chunk.py's
hard-won German rules belong (clause edges, comma classes, dash
pairing, punct absorption, fusion). Port those into
`break_strengths()`, keep DP + nesting untouched, rerun, re-judge.

## v2 fixes (implemented after this diagnosis)

1. Clause detection: verb-headed non-root subtrees with their own
   subordinator/finite verb are clauses (covers TIGER mo-clauses);
   modal brackets ("kann … kommen") exempted, as in tools/chunk.py.
   Plus a parse-independent backstop: a comma directly before OR after
   a finite verb is a clause seam (85) under any parse.
2. Comma classes: clause 85 / apposition 60 / default 50 / NP-list 15,
   and the list class CAPS generic edge signals (a "braunen," cut
   can't sneak back in via a subtree edge).
3. Subj/obj subtrees score BOTH edges, normalized past trailing
   punctuation ("… dünnen Beine | flimmerten" is now a 45 seam).
4. Paired dashes (open cuts before, close cuts after), punct-only
   chunks impossible (0-word span = ∞ DP cost), punct-only "sentences"
   (stray «) absorbed into neighbours.
5. words = whitespace pieces containing a letter/digit.
6. Full fuse_dir port: pronoun-after-verb ("stand er",
   "verwandelte sich"), pronoun-before-verb, PTKNEG, ADV/NUM before
   head, look-through-punct ("und, | weil"), hyphen compounds.
7. Severed-verb penalty (gate B as a DP cost), exempt at seams ≥ 85 —
   the parser sometimes mis-hangs objects on a clause-final verb.
8. Progressive rungs: recursive + adaptive (strongest sufficiently-
   central break until every part ≤ 14 words). The 111-word
   "Wohnzimmertür" monster gets 4 rungs (2→4→8→11 parts); short
   sentences get none. Rung picking now weighs centeredness, so
   sentence 11 cuts at the comma.

Owner-flagged sentences after v2 (sm smoke run): 1 cuts at
"erwachte, |"; 2 reads "und sah, | wenn er den Kopf ein wenig hob, |
seinen gewölbten, braunen, von bogenförmigen Versteifungen geteilten
Bauch, | …"; 3 cuts at "Beine | flimmerten"; 7 has no "—," chunk;
11's rung cuts at the comma.

# Round 4 final state (owner review of lg test_improvements report)

- **Cheap strong cuts ADOPTED** (CHEAP_STRONG_CUTS = True): owner read
  the lg before/after (378/892 sentences, mostly beginner) and judged
  it good. Verified neutral at starter sizes (runts/oversize
  unchanged) — the discount only redistributes cuts toward strong
  seams.
- **lg vs sm test reports**: qualitatively identical (case 1
  starter-only, case 2 beginner-dominated, same example sentences);
  lg just scales the counts (180 vs 45 / 378 vs 124) and separates
  more shadow cases (16 vs 7).
- **Extended-attribute lock added**: the "mit vor Befriedigung |
  tränenden Augen" cut turned out to be a *valid* strength-5 cut the
  DP took under length pressure (not a desperation cut — case 1
  couldn't touch it, intermediate changes were 0). Root fix: no cut
  inside the subtree of a prenominal adjective/participle (ADJ with
  NOUN head to its right) — "vor Befriedigung tränenden", "von
  bogenförmigen Versteifungen geteilten" are one attribute phrase.
  Costs ~1pp extra starter runts next to locked attributes; meaning >
  size regularity per the project bottom line. (sm cannot verify the
  motivating sentence — it splits it mid-sentence and parses the
  fragment with "tränenden" as ROOT; lg has the correct structure.)

# Rung diagnosis — owner review of the v2 lg run (round 2)

Owner findings: s1-3 rung1 not nested with advanced; s1-10 rung2
should be a more even 3-way; s1-12 rungs could be better; identical
rungs must not repeat in the app. Levels themselves: acceptable.

Scale of it (lg run, 512 sentences with rungs): 39% of rung ladders
contain a cut that is NOT an advanced cut (no nesting); 224 sentences
have a rung identical to the advanced chunking (pure repetition); 8%
of first rungs are badly uneven (max/min part > 2.5).

## Root cause: rungs are computed from RAW strengths, ignoring the
## level hierarchy the DP already built

progressive_rungs() re-derives cuts from scratch with a different,
worse objective (greedy binary split, score = strength − 45·off-center):

- **s1-3**: the off-center 65 PP ("hilflos ‖65‖ vor den Augen",
  14|3) outscores the central 45 NP|verb seam (65−29.1=35.9 vs
  45−13.2=31.8) — while the advanced DP had already correctly chosen
  the 45 seam (11|6). Two pickers, two answers, no nesting.
- **s1-10**: rung1 cuts at the zu-infinitive edge INSIDE the
  denn-clause ("gewöhnt, ‖85‖ auf der rechten", 24|18, 85−6.4=78.6)
  beating the top-level speech seam ("vergäße,« ‖90‖ dachte er",
  13|29, 90−17.1=72.9). Flat strength − linear centeredness cannot
  express "this seam is top-level, that one is subordinate" — but the
  advanced cuts [11, 26, 38] already encode exactly that.
- **s1-12**: greedy BINARY recursion can never produce an even 3-way
  split, so rung2 strands a 4-word "und ließ erst ab," next to a
  15-word piece.

## Fix design: rungs = a merge ladder OVER the advanced chunks

Choose rung cuts as SUBSETS of the advanced cut set (DP again, growing
target per rung, e.g. ~half the sentence, then ~quarter, until the
rung equals the advanced cuts — emit only DISTINCT intermediate
steps). This gives, by construction:

- nesting with EVERY level (rungs ⊆ advanced ⊆ intermediate ⊆ … —
  moving up a rung = merging familiar advanced chunks);
- no repetition (ladder stops before duplicating advanced; the app
  appends the level's own chunks as the finest rung and the whole
  sentence as the final one, deduping by cut-set equality);
- evenness via the DP instead of greedy halving (s1-10 rung1 becomes
  the 20|22 split at "denn", and a 3-way step is available);
- boundary quality inherited from the advanced DP — one picker, one
  answer.

Checks for s1-3: only advanced cut = [12] → ladder is empty, rung =
advanced = 11|6, shown once. Exactly the owner's "if rung1 is the
same as advanced it is good, and it should not repeat".

## Round-2 fix: IMPLEMENTED (merge-ladder rungs)

progressive_rungs() now selects rung cuts as nested subsets of the
advanced cuts via a light DP with growing part-count targets (÷2, ÷3,
÷4, …); only distinct intermediate steps are emitted. Verified on the
sm smoke run (whole book): 355 ladders, 0 nesting violations, 0 rungs
duplicating advanced, 0 duplicate steps; metrics.md now reports these
invariants on every run. Owner cases: s1-3 → no intermediate rung
(chunks → sentence); s1-10 → 20|22 at "denn", then 20|10|12; s1-12 →
16|19, next step is advanced itself. The 108-word monster gets a
6-step ladder (2 → 3 → 4 → 8 → 9 → 10 parts) — the app can subsample
(e.g. every other rung) if 6 is too many; the data is the full ladder.

App contract: ladder for level L = [distinct rungs coarser than L] +
[L's own chunks] + [whole sentence], deduped by cut-set equality —
rungs ⊆ advanced ⊆ every finer level, so this works at any level.

# Round 3 (owner feedback on v2-lg): two refinements, IMPLEMENTED

## 1. Verb brackets beyond modals (s1-15 "auferlegt")

The cut before "auferlegt" scored 85 as a clause edge: "auferlegt" is
`oc` under "ist", and oc was blanket-listed as a clause dep. But
"ist … auferlegt" is a passive verb BRACKET — one predicate, same as
the modal bracket already excepted. Fix: is_verb_bracket() covers all
analytic forms (participles + bare infinitives under a finite verb —
perfect, passive, future, modal), and the right-bracket verb fuses
LEFT. zu-infinitives keep clause status (cutting before "auf der
rechten Seite zu schlafen" is good). tools/chunk.py has the same
blind spot (excepts only VMFIN) but its merge gates masked it; the DP
has no gates, so the scoring must know.

Blast radius (sm, section I): 5–11% of sentences per level, sampled
changes all improvements — "»Was ist mit mir geschehen?«" no longer
split, "ich hätte längst gekündigt," whole, "ist noch nicht gänzlich
aufgegeben," whole, "… diese Plage des Reisens auferlegt," whole.

## 2. Ladder collapse of independent merges (s1-2, s3-2)

Climbing the ladder, step F→M and step M→C commute when no chunk that
C merges contains a boundary F→M removed — then M teaches nothing on
the way to C. collapse_ladder() drops such rungs, so successive rungs
always build on each other and progressive practice is less
repetitive. s1-2: 3 rungs → 2 (advanced jumps straight to 16|8|14).
Ladder depth across the book: was up to 8, now ≤ 3; the 108-word
monster reads 12 chunks → 8 → 4 → 2 → sentence. All invariants still
hold (0 nesting violations, 0 duplicates).
