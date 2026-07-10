# Chunking experiment metrics — current vs candidate B

Book: Die Verwandlung (kafka), 878 sentences, 3 sections. Alignment mismatches: 0 (should be 0).

| level | variant | chunks | words/chunk mean | stdev | CV | adj. fluctuation | % under min | % over max | max |
|---|---|---|---|---|---|---|---|---|---|
| starter | current | 7039 | 2.72 | 0.89 | 0.33 | 0.98 | 4.4% | 19.8% | 7 |
| starter | candB | 7168 | 2.67 | 0.83 | 0.31 | 0.91 | 5.1% | 18.1% | 4 |
| beginner | current | 5714 | 3.35 | 1.12 | 0.33 | 1.27 | 0.6% | 2.5% | 7 |
| beginner | candB | 5367 | 3.57 | 1.03 | 0.29 | 1.17 | 0.6% | 2.3% | 6 |
| intermediate | current | 4359 | 4.40 | 1.68 | 0.38 | 1.88 | 0.2% | 0.1% | 9 |
| intermediate | candB | 3513 | 5.45 | 1.51 | 0.28 | 1.79 | 0.2% | 0.1% | 9 |
| advanced | current | 3136 | 6.11 | 2.29 | 0.38 | 2.41 | 0.4% | 0.0% | 12 |
| advanced | candB | 2291 | 8.36 | 2.11 | 0.25 | 2.19 | 0.5% | 0.0% | 12 |

*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a sentence — the “2–6–2” complaint, lower is steadier.

## Long sentences (≥ 25 words): worst chunk at intermediate/advanced

- sentences counted: 290
- current: mean worst-chunk 9.1 words, absolute worst 12
- candidate B: mean worst-chunk 10.7 words, absolute worst 12

## Nesting (coarser boundaries ⊆ finer boundaries)

- candidate B violations: 0 (must be 0 — nested by construction)
- current chunker violations: 81 (levels cut independently; expected > 0 — this is what blocks adaptive progressive rungs today)

## Progressive rungs (candidate B, merge ladder over advanced)

- sentences with a rung ladder: 360
- ladder depth distribution: 1 rung(s): 229, 2 rung(s): 116, 3 rung(s): 15
- ladders violating nesting (must be 0): 0
- rungs duplicating the advanced chunking (must be 0): 0
- duplicate adjacent rungs (must be 0): 0
