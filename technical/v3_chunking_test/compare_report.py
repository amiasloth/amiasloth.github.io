#!/usr/bin/env python3
"""
Side-by-side comparison: current chunker output (docs/data/de/kafka_*.json)
vs candidate B (out/hierarchy_kafka.json), plus the metrics the owner
wants to judge (00_v3_overview.md experiment plan):

  (1) boundary quality vs current      -> read the HTML side-by-side
  (2) length variance at intermediate/advanced -> metrics table
  (3) long-sentence behavior under the hard cap -> metrics table
  (4) whether nesting visibly hurts any level  -> read HTML + nesting check

Outputs:
  out/compare_section_<n>.html   side-by-side reading view per section
  out/metrics.md                 aggregate numbers
"""

import argparse
import html
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
LEVELS = ["starter", "beginner", "intermediate", "advanced"]
BOUNDS = {"starter": (2, 3), "beginner": (2, 5),
          "intermediate": (2, 8), "advanced": (3, 12)}
TARGETS = {"starter": 2, "beginner": 3, "intermediate": 5, "advanced": 8}


def norm(s):
    return "".join(s.split())


# ------------------------------------------------- load + align baseline

def load_baseline(data_dir, book):
    """{level: [sections]}, section = list of chunk texts."""
    out = {}
    for lvl in LEVELS:
        d = json.loads((data_dir / f"{book}_{lvl}.json").read_text())
        out[lvl] = [[c["t"] for c in sec["chunks"]] for sec in d["sections"]]
    return out


def map_chunks_to_sentences(cand_sents, chunks):
    """Assign each baseline chunk to a candidate sentence by position in
    the normalized section text (both cover the same text in order)."""
    sent_norms = [norm(s["text"]) for s in cand_sents]
    starts, pos = [], 0
    for sn in sent_norms:
        starts.append(pos)
        pos += len(sn)
    total = pos

    per_sent = [[] for _ in cand_sents]
    cpos, mismatch = 0, False
    for t in chunks:
        tn = norm(t)
        # which sentence contains this chunk's start?
        si = 0
        for i, st in enumerate(starts):
            if st <= cpos:
                si = i
            else:
                break
        per_sent[si].append(t)
        cpos += len(tn)
    if cpos != total:
        mismatch = True
    return per_sent, mismatch


# ------------------------------------------------- metrics

def wc(t):
    """Words = whitespace pieces containing a letter/digit ("—," = 0)."""
    return sum(1 for w in t.split() if any(ch.isalnum() for ch in w))


def chunk_stats(sent_chunk_lists, lvl):
    """sent_chunk_lists: list (per sentence) of chunk-text lists."""
    mn, mx = BOUNDS[lvl]
    lens = [wc(c) for s in sent_chunk_lists for c in s]
    fluct = []
    for s in sent_chunk_lists:
        ws = [wc(c) for c in s]
        fluct += [abs(a - b) for a, b in zip(ws, ws[1:])]
    if not lens:
        return None
    return {
        "chunks": len(lens),
        "mean": statistics.mean(lens),
        "stdev": statistics.pstdev(lens),
        "cv": statistics.pstdev(lens) / statistics.mean(lens),
        "fluct": statistics.mean(fluct) if fluct else 0.0,
        "runts": sum(1 for w in lens if w < mn) / len(lens),
        "over": sum(1 for w in lens if w > mx) / len(lens),
        "max": max(lens),
    }


def cut_offsets(chunks):
    """Cut positions as normalized-char offsets (internal boundaries)."""
    offs, pos = set(), 0
    for c in chunks[:-1]:
        pos += len(norm(c))
        offs.add(pos)
    return offs


def nesting_violations(per_level_chunks):
    """coarser boundaries must be a subset of finer boundaries.
    order: advanced ⊆ intermediate ⊆ beginner ⊆ starter."""
    v = 0
    order = ["advanced", "intermediate", "beginner", "starter"]
    for coarse, fine in zip(order, order[1:]):
        v += len(cut_offsets(per_level_chunks[coarse])
                 - cut_offsets(per_level_chunks[fine]))
    return v


# ------------------------------------------------- html

CSS = """
body{font-family:Georgia,serif;max-width:1200px;margin:24px auto;
     padding:0 16px;color:#222;background:#faf8f4}
h1{font-size:1.3em} h2{font-size:1.05em;color:#555;margin-top:2em}
.sent{border:1px solid #ddd;border-radius:8px;background:#fff;
      margin:18px 0;padding:10px 14px}
.stext{font-style:italic;color:#444;margin-bottom:8px}
table{border-collapse:collapse;width:100%}
td,th{vertical-align:top;padding:4px 8px;border-top:1px solid #eee;
      font-size:.92em}
th{text-align:left;color:#777;font-weight:normal;width:7em}
.col{width:46%}
.ck{display:inline-block;background:#eef3f8;border-radius:4px;
    padding:1px 6px;margin:2px 3px 2px 0;line-height:1.5}
.b .ck{background:#eff8ee}
.n{color:#98a;font-size:.75em}
.runt .n{color:#c60} .runt{outline:1px solid #e9b}
.over{outline:2px solid #d33} .over .n{color:#d33;font-weight:bold}
.half .ck{background:#fdf3e3}
.legend{font-size:.85em;color:#666}
"""


def render_chunks(chunks, lvl, cls=""):
    mn, mx = BOUNDS[lvl]
    parts = []
    for c in chunks:
        w = wc(c)
        k = "ck"
        if w > mx:
            k += " over"
        elif w < mn:
            k += " runt"
        parts.append(f'<span class="{k}">{html.escape(c)} '
                     f'<span class="n">{w}</span></span>')
    return f'<span class="{cls}">' + "".join(parts) + "</span>"


def render_section(title, cand_sents, base_per_sent, out_path, sec_no):
    rows = []
    for i, cs in enumerate(cand_sents):
        lvl_rows = []
        for lvl in LEVELS:
            cur = base_per_sent[lvl][i]
            cand = cs["levels"][lvl]
            lvl_rows.append(
                f"<tr><th>{lvl}</th>"
                f'<td class="col">{render_chunks(cur, lvl)}</td>'
                f'<td class="col b">{render_chunks(cand, lvl)}</td></tr>')
        halves = ""
        for ri, rung in enumerate(cs.get("rungs") or []):
            hh = "".join(f'<span class="ck">{html.escape(h)} '
                         f'<span class="n">{wc(h)}</span></span>'
                         for h in rung)
            halves += (f'<tr><th>rung {ri + 1}</th><td></td>'
                       f'<td class="col half">{hh}</td></tr>')
        rows.append(
            f'<div class="sent"><div class="stext">'
            f'{i + 1}. {html.escape(cs["text"])}</div>'
            f'<table><tr><th></th><th class="col">current chunker</th>'
            f'<th class="col">candidate B (nested hierarchy)</th></tr>'
            + "".join(lvl_rows) + halves + "</table></div>")
    out_path.write_text(
        f"<!doctype html><meta charset='utf-8'><style>{CSS}</style>"
        f"<h1>Die Verwandlung — section {sec_no} ({html.escape(title)}) — "
        f"current vs candidate B</h1>"
        f"<p class='legend'>numbers = words per chunk · "
        f"<span class='ck over'>red</span> over level max · "
        f"<span class='ck runt'>pink</span> under level min · "
        f"<span class='ck' style='background:#fdf3e3'>orange</span> "
        f"adaptive progressive rungs (long sentences, candidate B only)</p>"
        + "".join(rows), encoding="utf-8")


# ------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hierarchy", default=str(HERE / "out/hierarchy_kafka.json"))
    ap.add_argument("--data", default=str(ROOT / "docs/data/de"))
    ap.add_argument("--book", default="kafka")
    ap.add_argument("--outdir", default=str(HERE / "out"))
    args = ap.parse_args()

    cand = json.loads(Path(args.hierarchy).read_text())
    baseline = load_baseline(Path(args.data), args.book)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    agg = {("current", l): [] for l in LEVELS}
    agg.update({("candB", l): [] for l in LEVELS})
    long_max = {"current": [], "candB": []}   # max chunk len, sentences >=25w
    nest_viol = {"current": 0, "candB": 0}
    mismatches = 0

    for si, sec in enumerate(cand["sections"]):
        cs = sec["sentences"]
        base_per_sent = {}
        for lvl in LEVELS:
            per_sent, mism = map_chunks_to_sentences(cs, baseline[lvl][si])
            base_per_sent[lvl] = per_sent
            mismatches += mism

        render_section(sec["title"], cs, base_per_sent,
                       outdir / f"compare_section_{si + 1}.html", si + 1)

        for lvl in LEVELS:
            agg[("current", lvl)] += base_per_sent[lvl]
            agg[("candB", lvl)] += [s["levels"][lvl] for s in cs]

        for i, s in enumerate(cs):
            if wc(s["text"]) >= 25:
                long_max["candB"].append(
                    max((wc(c) for lv in ("intermediate", "advanced")
                         for c in s["levels"][lv]), default=0))
                long_max["current"].append(
                    max((wc(c) for lv in ("intermediate", "advanced")
                         for c in base_per_sent[lv][i]), default=0))
            nest_viol["candB"] += nesting_violations(s["levels"])
            nest_viol["current"] += nesting_violations(
                {lvl: base_per_sent[lvl][i] for lvl in LEVELS})

    # ---------------- metrics.md
    lines = ["# Chunking experiment metrics — current vs candidate B",
             "",
             f"Book: Die Verwandlung (kafka), "
             f"{sum(len(s['sentences']) for s in cand['sections'])} sentences, "
             f"{len(cand['sections'])} sections. "
             f"Alignment mismatches: {mismatches} (should be 0).", "",
             "| level | variant | chunks | words/chunk mean | stdev | CV | "
             "adj. fluctuation | % under min | % over max | max |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for lvl in LEVELS:
        for variant in ("current", "candB"):
            st = chunk_stats(agg[(variant, lvl)], lvl)
            lines.append(
                f"| {lvl} | {variant} | {st['chunks']} | {st['mean']:.2f} | "
                f"{st['stdev']:.2f} | {st['cv']:.2f} | {st['fluct']:.2f} | "
                f"{100 * st['runts']:.1f}% | {100 * st['over']:.1f}% | "
                f"{st['max']} |")
    lines += [
        "",
        "*adj. fluctuation* = mean |len(chunk i) − len(chunk i+1)| within a "
        "sentence — the “2–6–2” complaint, lower is steadier.",
        "",
        "## Long sentences (≥ 25 words): worst chunk at "
        "intermediate/advanced",
        "",
        f"- sentences counted: {len(long_max['current'])}",
        f"- current: mean worst-chunk {statistics.mean(long_max['current']):.1f}"
        f" words, absolute worst {max(long_max['current'])}",
        f"- candidate B: mean worst-chunk "
        f"{statistics.mean(long_max['candB']):.1f} words, absolute worst "
        f"{max(long_max['candB'])}",
        "",
        "## Nesting (coarser boundaries ⊆ finer boundaries)",
        "",
        f"- candidate B violations: {nest_viol['candB']} "
        "(must be 0 — nested by construction)",
        f"- current chunker violations: {nest_viol['current']} "
        "(levels cut independently; expected > 0 — this is what blocks "
        "adaptive progressive rungs today)",
    ]
    (outdir / "metrics.md").write_text("\n".join(lines) + "\n",
                                       encoding="utf-8")
    print(f"wrote {outdir}/compare_section_*.html and {outdir}/metrics.md")
    print(f"alignment mismatches: {mismatches}")


if __name__ == "__main__":
    main()
