# Chunking experiment metrics — current vs candidate B

Book: kafka, 878 sentences, 3 sections. Alignment mismatches: 0 (should be 0).

| level | variant | chunks | words/chunk mean | stdev | CV | adj. fluctuation | % under min | % over max | max |
|---|---|---|---|---|---|---|---|---|---|
| starter | current | 7039 | 2.72 | 0.89 | 0.33 | 0.98 | 4.4% | 19.8% | 7 |
| starter | candB | 7146 | 2.68 | 0.79 | 0.30 | 0.86 | 3.7% | 17.0% | 4 |
| beginner | current | 5714 | 3.35 | 1.12 | 0.33 | 1.27 | 0.6% | 2.5% | 7 |
| beginner | candB | 5672 | 3.38 | 1.02 | 0.30 | 1.17 | 0.5% | 2.2% | 6 |
| intermediate | current | 4359 | 4.40 | 1.68 | 0.38 | 1.88 | 0.2% | 0.1% | 9 |
| intermediate | candB | 3600 | 5.32 | 1.52 | 0.28 | 1.82 | 0.2% | 0.2% | 9 |
| advanced | current | 3136 | 6.11 | 2.29 | 0.38 | 2.41 | 0.4% | 0.0% | 12 |
| advanced | candB | 2342 | 8.18 | 2.11 | 0.26 | 2.25 | 0.5% | 0.0% | 12 |

*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a sentence — the “2–6–2” complaint, lower is steadier.

## Long sentences (≥ 25 words): worst chunk at intermediate/advanced

- sentences counted: 290
- current: mean worst-chunk 9.1 words, absolute worst 12
- candidate B: mean worst-chunk 10.6 words, absolute worst 12

## Nesting (coarser boundaries ⊆ finer boundaries)

- candidate B violations: 0 (must be 0 — nested by construction)
- current chunker violations: 81 (levels cut independently; expected > 0 — this is what blocks adaptive progressive rungs today)

## Progressive rungs (candidate B, merge ladder over advanced)

- sentences with a rung ladder: 372
- ladder depth distribution: 1 rung(s): 236, 2 rung(s): 119, 3 rung(s): 17
- ladders violating nesting (must be 0): 0
- rungs duplicating the advanced chunking (must be 0): 0
- duplicate adjacent rungs (must be 0): 0
