# Chunking experiment metrics — current vs candidate B

Book: Die Verwandlung (kafka), 892 sentences, 3 sections. Alignment mismatches: 0 (should be 0).

| level | variant | chunks | words/chunk mean | stdev | CV | adj. fluctuation | % under min | % over max | max |
|---|---|---|---|---|---|---|---|---|---|
| starter | current | 7039 | 2.74 | 0.91 | 0.33 | 0.99 | 4.3% | 20.5% | 7 |
| starter | candB | 7431 | 2.60 | 0.73 | 0.28 | 0.75 | 2.5% | 12.4% | 4 |
| beginner | current | 5714 | 3.38 | 1.13 | 0.33 | 1.28 | 0.6% | 2.9% | 8 |
| beginner | candB | 5517 | 3.50 | 0.97 | 0.28 | 1.10 | 0.5% | 0.8% | 6 |
| intermediate | current | 4359 | 4.42 | 1.69 | 0.38 | 1.90 | 0.2% | 0.2% | 11 |
| intermediate | candB | 3556 | 5.43 | 1.51 | 0.28 | 1.77 | 0.6% | 0.0% | 8 |
| advanced | current | 3136 | 6.15 | 2.31 | 0.38 | 2.42 | 0.4% | 0.3% | 14 |
| advanced | candB | 2271 | 8.50 | 2.14 | 0.25 | 2.15 | 1.1% | 0.0% | 12 |

*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a sentence — the “2–6–2” complaint, lower is steadier.

## Long sentences (≥ 25 words): worst chunk at intermediate/advanced

- sentences counted: 292
- current: mean worst-chunk 9.1 words, absolute worst 13
- candidate B: mean worst-chunk 10.8 words, absolute worst 12

## Nesting (coarser boundaries ⊆ finer boundaries)

- candidate B violations: 0 (must be 0 — nested by construction)
- current chunker violations: 81 (levels cut independently; expected > 0 — this is what blocks adaptive progressive rungs today)
