# Chunking experiment metrics — current vs candidate B

Book: Die Verwandlung (kafka), 870 sentences, 3 sections. Alignment mismatches: 0 (should be 0).

| level | variant | chunks | words/chunk mean | stdev | CV | adj. fluctuation | % under min | % over max | max |
|---|---|---|---|---|---|---|---|---|---|
| starter | current | 7039 | 2.72 | 0.89 | 0.33 | 0.98 | 4.4% | 19.8% | 7 |
| starter | candB | 7139 | 2.68 | 0.78 | 0.29 | 0.84 | 3.3% | 16.7% | 4 |
| beginner | current | 5714 | 3.35 | 1.12 | 0.33 | 1.27 | 0.6% | 2.5% | 7 |
| beginner | candB | 5395 | 3.55 | 1.01 | 0.29 | 1.17 | 0.5% | 2.0% | 6 |
| intermediate | current | 4359 | 4.40 | 1.68 | 0.38 | 1.88 | 0.2% | 0.1% | 9 |
| intermediate | candB | 3526 | 5.43 | 1.50 | 0.28 | 1.75 | 0.1% | 0.1% | 9 |
| advanced | current | 3136 | 6.11 | 2.29 | 0.38 | 2.43 | 0.4% | 0.0% | 12 |
| advanced | candB | 2281 | 8.40 | 2.07 | 0.25 | 2.19 | 0.3% | 0.0% | 12 |

*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a sentence — the “2–6–2” complaint, lower is steadier.

## Long sentences (≥ 25 words): worst chunk at intermediate/advanced

- sentences counted: 288
- current: mean worst-chunk 9.1 words, absolute worst 12
- candidate B: mean worst-chunk 10.7 words, absolute worst 12

## Nesting (coarser boundaries ⊆ finer boundaries)

- candidate B violations: 0 (must be 0 — nested by construction)
- current chunker violations: 117 (levels cut independently; expected > 0 — this is what blocks adaptive progressive rungs today)
