# Chunking experiment metrics — current vs candidate B

Book: Die Verwandlung (kafka), 874 sentences, 3 sections. Alignment mismatches: 0 (should be 0).

| level | variant | chunks | words/chunk mean | stdev | CV | adj. fluctuation | % under min | % over max | max |
|---|---|---|---|---|---|---|---|---|---|
| starter | current | 7039 | 2.74 | 0.91 | 0.33 | 0.99 | 4.3% | 20.5% | 7 |
| starter | candB | 7419 | 2.60 | 0.73 | 0.28 | 0.75 | 2.3% | 12.5% | 4 |
| beginner | current | 5714 | 3.38 | 1.13 | 0.33 | 1.27 | 0.6% | 2.9% | 8 |
| beginner | candB | 5494 | 3.51 | 0.97 | 0.28 | 1.11 | 0.2% | 0.7% | 6 |
| intermediate | current | 4359 | 4.42 | 1.69 | 0.38 | 1.89 | 0.2% | 0.2% | 11 |
| intermediate | candB | 3534 | 5.45 | 1.48 | 0.27 | 1.73 | 0.2% | 0.0% | 8 |
| advanced | current | 3136 | 6.15 | 2.31 | 0.38 | 2.44 | 0.4% | 0.3% | 14 |
| advanced | candB | 2256 | 8.54 | 2.05 | 0.24 | 2.13 | 0.4% | 0.0% | 12 |

*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a sentence — the “2–6–2” complaint, lower is steadier.

## Long sentences (≥ 25 words): worst chunk at intermediate/advanced

- sentences counted: 289
- current: mean worst-chunk 9.2 words, absolute worst 13
- candidate B: mean worst-chunk 10.8 words, absolute worst 12

## Nesting (coarser boundaries ⊆ finer boundaries)

- candidate B violations: 0 (must be 0 — nested by construction)
- current chunker violations: 117 (levels cut independently; expected > 0 — this is what blocks adaptive progressive rungs today)
