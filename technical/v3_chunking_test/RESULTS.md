# Smoke-run results (preliminary — regenerate with lg before judging)

The committed `out/` was generated with **de_core_news_sm** (sandbox
couldn't hold the lg model). The shipped baseline was parsed with
**de_core_news_lg**, so individual boundary placements in the
side-by-side are NOT a fair quality comparison yet — sm and lg parse
differently. Rerun on the build machine before deciding anything:

    bash technical/v3_chunking_test/run_experiment.sh

Machinery is verified: 874 sentences, 3 sections, 0 reconstruction
failures, 0 baseline-alignment mismatches, 0 nesting violations.

## Preliminary read on the four judgment questions

**(2) Length variance at intermediate/advanced** — the headline
complaint, and the clearest win, largely parse-independent (it comes
from the DP balancer, not the parse):

| level | variant | mean | CV | adj. fluctuation | % over max |
|---|---|---|---|---|---|
| intermediate | current | 4.42 | 0.38 | 1.89 | 0.2% |
| intermediate | cand B | 5.45 | **0.27** | **1.73** | 0.0% |
| advanced | current | 6.15 | 0.38 | 2.44 | 0.3% |
| advanced | cand B | 8.54 | **0.24** | **2.13** | 0.0% |

Candidate B also actually *reaches* the target lengths (current
advanced averages 6.15 words against a target of 8 — part of why
intermediate≈advanced feels samey). Starter/beginner separate more
too: means 2.60 / 3.51 / 5.45 / 8.54 vs current 2.74 / 3.38 / 4.42 /
6.15.

**(3) Long sentences under the hard cap** — candidate B never exceeds
max+1 at any level (current: up to 14 words at advanced, 7 at
starter). Cost: its worst chunks sit closer to the cap on average
(10.8 vs 9.2 words at ≥25-word sentences) — bigger but *predictable*
chunks. Judge in the HTML whether that reads better.

**(4) Does nesting hurt?** — the constraint is real: once advanced
keeps a clause whole, intermediate must cut *inside* it and sometimes
picks a weaker boundary than free cutting would (visible in section 1,
sentence 2: "und sah, wenn er | den Kopf ein wenig hob," instead of
cutting at "wenn"). This is exactly the owner-skepticism scenario —
read the side-by-sides and decide if it's rare enough to accept for
the adaptive-rungs payoff. The current chunker has 117 nesting
violations across the book, i.e. adaptive rungs are impossible with
independently-cut levels.

**(1) Boundary quality vs current** — wait for the lg run.

## Tuning knobs (all in `chunk_hierarchy.py`, top of file)

`W_LEN / W_CUT / W_PREF / W_RUNT` and the per-level `pref` thresholds.
If nesting artifacts bother at intermediate, raising `W_PREF` (respect
strong boundaries more, tolerate length deviation) is the first thing
to try.

## What would falsify candidate B

- lg run shows systematically worse boundaries than current at
  beginner/intermediate (the levels actually read the most), or
- nesting artifacts show up in a noticeable fraction of long
  sentences, not just occasionally.

Then the answer is A (current + DP rebalancer as a post-pass), which
would inherit this file's DP balancer with `prev_cuts` fixed to the
current chunker's output — cheap to try next.
