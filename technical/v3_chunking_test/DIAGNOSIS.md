# Diagnosis — owner review of the lg run (2026-07-10)

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
