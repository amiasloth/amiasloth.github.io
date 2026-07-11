/* Node test for js/data3.js against the real docs/data3 files.
 * Run from docs/v3: node test_data3.js
 * Checks, per book and level:
 *  - chunk count equals books.json stats.chunks[level]
 *  - reconstruction: raw chunk slices concatenate to join(toks, sp)
 *  - every chunk has at least one letter/digit (no punct-only chunk)
 *  - cont/sentStart/sentEnd/ci are mutually consistent
 *  - findPosition round-trips every (sid, occ, ci)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const Data3 = require("./js/data3.js");

const ROOT = path.join(__dirname, "..", "data3");
const index = JSON.parse(fs.readFileSync(path.join(ROOT, "books.json"), "utf8"));
let fails = 0;
const bad = (msg) => { fails++; console.error("FAIL " + msg); };

for (const meta of index.books) {
  const book = JSON.parse(fs.readFileSync(
    path.join(ROOT, meta.lang, meta.id + ".json"), "utf8"));
  for (const lv of meta.levels) {
    const flat = Data3.flatten(book, lv);
    const tag = meta.id + "/" + lv;

    // chunk count vs stats
    const want = meta.stats.chunks[lv];
    if (flat.length !== want)
      bad(tag + ": " + flat.length + " chunks, books.json says " + want);

    // reconstruction + punct-only + structure
    let fi = 0;
    book.sections.forEach((s, si) => {
      s.sentences.forEach((sent) => {
        const b = Data3.boundaries(sent, lv);
        const full = Data3.sliceText(sent.toks, sent.sp, 0, sent.toks.length, true);
        let joined = "";
        const sentStart = fi;
        for (let c = 0; c + 1 < b.length; c++, fi++) {
          const item = flat[fi];
          joined += Data3.sliceText(sent.toks, sent.sp, b[c], b[c + 1], true);
          if (!/[\p{L}\p{N}]/u.test(item.t))
            bad(tag + " " + sent.id + ": punct-only chunk '" + item.t + "'");
          if (item.sid !== sent.id || item.occ !== (sent.occ || 0))
            bad(tag + " " + sent.id + ": wrong sid/occ on flat[" + fi + "]");
          if (item.ci !== c || item.sec !== si || item.i !== fi)
            bad(tag + " " + sent.id + ": ci/sec/i mismatch at flat[" + fi + "]");
          if (item.sentStart !== sentStart || item.sentEnd !== sentStart + b.length - 2)
            bad(tag + " " + sent.id + ": sentStart/sentEnd mismatch");
          if (!!item.cont !== (c + 2 < b.length))
            bad(tag + " " + sent.id + ": cont flag mismatch");
          // token-range fields for the renderer (verb/name spans)
          if (item.a !== b[c] || item.b !== b[c + 1] || item.sent !== sent)
            bad(tag + " " + sent.id + ": a/b/sent mismatch at flat[" + fi + "]");
          // span-rendering invariant: per-token spans (trailing space
          // inside each span, none after the last) rejoin to chunk text
          let spanJoin = "";
          for (let k = item.a; k < item.b; k++) {
            spanJoin += sent.toks[k];
            if (k + 1 < item.b && sent.sp.charAt(k) === "1") spanJoin += " ";
          }
          if (spanJoin !== item.t)
            bad(tag + " " + sent.id + ": span join != chunk text");
          // pos/ents indices stay inside the token list
          if (sent.pos && sent.pos.length !== sent.toks.length)
            bad(tag + " " + sent.id + ": pos length != toks length");
          (sent.ents || []).forEach((e) => {
            if (e[0] < 0 || e[1] > sent.toks.length || e[0] >= e[1])
              bad(tag + " " + sent.id + ": bad ent span " + JSON.stringify(e));
          });
        }
        if (joined !== full)
          bad(tag + " " + sent.id + ": reconstruction mismatch");
      });
    });
    if (fi !== flat.length) bad(tag + ": walked " + fi + " of " + flat.length);

    // findPosition round-trip (sampled: every 7th chunk + first/last)
    for (let k = 0; k < flat.length; k += (k % 7 === 6 ? 1 : 7)) {
      const c = flat[k];
      const at = Data3.findPosition(flat, { sid: c.sid, occ: c.occ, ci: c.ci });
      if (at !== k) bad(tag + ": findPosition(" + c.sid + "," + c.occ + "," +
                        c.ci + ") = " + at + ", want " + k);
    }
    console.log("ok  " + tag + "  " + flat.length + " chunks");
  }
}
// ---------------- gloss lookup ----------------
// Every word token of every book must resolve through the runtime chain
// (orth → nfcLower → forms/words) unless it is an entity token or an
// out-of-vocabulary miss the build also reported. Spot-check semantics
// on kafka, then assert the bulk invariant: lookups never throw and
// entity tokens never produce entries.
for (const meta of index.books) {
  const book = JSON.parse(fs.readFileSync(
    path.join(ROOT, meta.lang, meta.id + ".json"), "utf8"));
  let gloss;
  try {
    gloss = JSON.parse(fs.readFileSync(
      path.join(ROOT, "gloss", meta.id + ".json"), "utf8"));
  } catch (e) { bad(meta.id + ": no gloss file"); continue; }
  let words = 0, lemmaHits = 0, entryHits = 0, entTok = 0;
  book.sections.forEach((s) => s.sentences.forEach((sent) => {
    for (let k = 0; k < sent.toks.length; k++) {
      if (!/[\p{L}\p{N}]/u.test(sent.toks[k])) continue;
      words++;
      const r = Data3.glossLookup(gloss, sent, k);
      if (r.isEnt) { entTok++; continue; }
      if (r.lemma) lemmaHits++;
      if (r.entry) {
        entryHits++;
        if (typeof r.entry.g_en !== "string")
          bad(meta.id + " " + sent.id + ": entry without g_en for '" +
              sent.toks[k] + "'");
      }
    }
  }));
  console.log("ok  gloss " + meta.id + "  " + words + " word tokens, " +
    lemmaHits + " lemma hits, " + entryHits + " glossed, " + entTok + " in ents");
  if (lemmaHits / (words - entTok) < 0.9)
    bad(meta.id + ": lemma coverage below 90% — forms map not book-complete?");
}

// semantic spot checks (kafka sentence 1) + override merge
{
  const gloss = JSON.parse(fs.readFileSync(path.join(ROOT, "gloss", "kafka.json"), "utf8"));
  const book = JSON.parse(fs.readFileSync(path.join(ROOT, "de", "kafka.json"), "utf8"));
  const sent = book.sections[0].sentences[0];   // "Als Gregor Samsa …"
  const t = (k) => Data3.glossLookup(gloss, sent, k);
  if (!t(1).isEnt || !t(2).isEnt) bad("kafka s1: Gregor Samsa not flagged as ents");
  if (t(10).lemma !== "finden") bad("kafka s1: 'fand' → " + t(10).lemma + ", want finden");
  const ung = t(19);   // "Ungeziefer"
  if (!ung.entry || !/vermin/.test(ung.entry.g_en))
    bad("kafka s1: 'Ungeziefer' entry wrong: " + JSON.stringify(ung.entry));
  // override layer: per-occurrence sense exception wins over the default
  const g2 = JSON.parse(JSON.stringify(gloss));
  g2.overrides[sent.id] = { ungeziefer: { g_en: "OVERRIDDEN", e: "🪲" } };
  const ov = Data3.glossLookup(g2, sent, 19);
  if (ov.entry.g_en !== "OVERRIDDEN" || ov.entry.e !== "🪲" || ov.entry.l !== "Ungeziefer")
    bad("override merge broken: " + JSON.stringify(ov.entry));
  // orth layer: archaic surface looks up by the modern form
  const sFake = { id: "x", toks: ["Thür"], sp: "0", orth: { "0": "Tür" } };
  const gFake = { forms: { "tür": "tür" }, words: { "tür": { l: "Tür", g_en: "door", e: "" } }, overrides: {} };
  const th = Data3.glossLookup(gFake, sFake, 0);
  if (th.lemma !== "tür" || th.entry.g_en !== "door")
    bad("orth lookup broken: " + JSON.stringify(th));
  console.log("ok  gloss semantics (ents, lemma, entry, override, orth)");
}

console.log(fails ? fails + " FAILURES" : "ALL CHECKS PASSED");
process.exit(fails ? 1 : 0);
