# Chunking experiment metrics — current vs candidate B

Book: alice, 1500 sentences, 12 sections. Alignment mismatches: 0 (should be 0).

| level | variant | chunks | words/chunk mean | stdev | CV | adj. fluctuation | % under min | % over max | max |
|---|---|---|---|---|---|---|---|---|---|
| starter | current | 9989 | 2.65 | 0.85 | 0.32 | 0.90 | 5.1% | 15.7% | 7 |
| starter | candB | 9885 | 2.68 | 0.79 | 0.29 | 0.84 | 3.5% | 16.7% | 4 |
| beginner | current | 8711 | 3.04 | 1.03 | 0.34 | 1.08 | 1.3% | 1.2% | 7 |
| beginner | candB | 7966 | 3.32 | 0.96 | 0.29 | 1.10 | 0.4% | 1.2% | 6 |
| intermediate | current | 6814 | 3.89 | 1.47 | 0.38 | 1.57 | 0.6% | 0.0% | 9 |
| intermediate | candB | 5075 | 5.22 | 1.52 | 0.29 | 1.79 | 0.4% | 0.0% | 8 |
| advanced | current | 4720 | 5.61 | 2.11 | 0.38 | 2.15 | 2.0% | 0.0% | 13 |
| advanced | candB | 3368 | 7.86 | 2.27 | 0.29 | 2.26 | 2.0% | 0.0% | 12 |

*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a sentence — the “2–6–2” complaint, lower is steadier.

## Long sentences (≥ 25 words): worst chunk at intermediate/advanced

- sentences counted: 335
- current: mean worst-chunk 8.3 words, absolute worst 12
- candidate B: mean worst-chunk 10.5 words, absolute worst 12

## Nesting (coarser boundaries ⊆ finer boundaries)

- candidate B violations: 0 (must be 0 — nested by construction)
- current chunker violations: 243 (levels cut independently; expected > 0 — this is what blocks adaptive progressive rungs today)

## Progressive rungs (candidate B, merge ladder over advanced)

- sentences with a rung ladder: 450
- ladder depth distribution: 1 rung(s): 307, 2 rung(s): 124, 3 rung(s): 15, 4 rung(s): 3, 5 rung(s): 1
- ladders violating nesting (must be 0): 0
- rungs duplicating the advanced chunking (must be 0): 0
- duplicate adjacent rungs (must be 0): 0
