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

// ---------------- study lists ----------------
// study_by_sent keys must be real sentence ids; every study lemma must
// have a words entry (they are the rare *glossed* lemmas); gloss
// sections must align 1:1 with book sections, and each section's
// pre-study list must equal the first-occurrence dedup of its
// sentences' study_by_sent entries (the 02 schema derivation).
for (const meta of index.books) {
  const book = JSON.parse(fs.readFileSync(
    path.join(ROOT, meta.lang, meta.id + ".json"), "utf8"));
  const gloss = JSON.parse(fs.readFileSync(
    path.join(ROOT, "gloss", meta.id + ".json"), "utf8"));
  if ((gloss.sections || []).length !== book.sections.length)
    bad(meta.id + ": gloss sections " + (gloss.sections || []).length +
        " != book sections " + book.sections.length);
  const ids = new Set();
  book.sections.forEach((s) => s.sentences.forEach((x) => ids.add(x.id)));
  for (const sid in gloss.study_by_sent) {
    if (!ids.has(sid)) bad(meta.id + ": study_by_sent unknown sid " + sid);
    gloss.study_by_sent[sid].forEach((l) => {
      if (!Object.prototype.hasOwnProperty.call(gloss.words, l))
        bad(meta.id + ": study lemma '" + l + "' has no words entry");
    });
  }
  book.sections.forEach((s, si) => {
    const derived = [], seen = new Set();
    s.sentences.forEach((sent) => {
      (gloss.study_by_sent[sent.id] || []).forEach((l) => {
        if (!seen.has(l)) { seen.add(l); derived.push(l); }
      });
    });
    const stored = (gloss.sections[si] && gloss.sections[si].study) || [];
    if (JSON.stringify(derived) !== JSON.stringify(stored))
      bad(meta.id + " section " + si + ": stored study list != " +
          "first-occurrence derivation (" + stored.length + " vs " +
          derived.length + ")");
  });
  console.log("ok  study " + meta.id + "  " +
    Object.keys(gloss.study_by_sent).length + " sentences, " +
    gloss.sections.map((s) => s.study.length).join("/") + " per section");
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

// ---------------- chunk emoji pick ----------------
// Unit checks of the 02-schema pick rules on a synthetic gloss, then an
// end-to-end estimate on grimm with the GENERATED test map merged
// in-memory (predicts what the UI shows once the gloss is rebuilt with
// the build-script fallback — docs/data3 itself is not touched).
{
  const sent = {
    id: "s1",
    toks: ["Anna", "sah", "das", "Schloss", "und", "das", "Einhorn",
           "und", "das", "Schloss", "."],
    sp: "11111111100",
    ents: [[0, 1, "PER"]],
  };
  const g = {
    forms: { anna: "anna", sah: "sehen", schloss: "schloss", einhorn: "einhorn" },
    words: {
      sehen: { l: "sehen", g_en: "to see", e: "👁" },
      schloss: { l: "Schloss", g_en: "castle", e: "🏰" },
      einhorn: { l: "Einhorn", g_en: "unicorn", e: "🦄" },
      anna: { l: "Anna", g_en: "should never win", e: "🚫" },
    },
    freq: { sehen: 5.5, schloss: 3.0 },     // einhorn missing = OOV = 0
    overrides: {},
  };
  const E = (a, b, gg) => Data3.chunkEmoji(gg || g, sent, a, b);
  // rarest wins: einhorn (OOV=0) < schloss (3.0) < sehen (5.5)
  if (E(1, 10) !== "🦄") bad("chunkEmoji: rarest pick, got " + E(1, 10));
  // entity token never a candidate even though glossed
  if (E(0, 2) !== "👁") bad("chunkEmoji: ent skip, got " + E(0, 2));
  // rarest-WITH-emoji fallback: strip einhorn's e -> schloss's 🏰
  const g2 = JSON.parse(JSON.stringify(g));
  g2.words.einhorn.e = "";
  if (E(1, 10, g2) !== "🏰") bad("chunkEmoji: empty-e fallthrough, got " + E(1, 10, g2));
  // zipf-0 tie: two OOV lemmas -> first in word order wins
  const g3 = JSON.parse(JSON.stringify(g));
  delete g3.freq.schloss;                    // schloss now OOV too
  if (E(1, 10, g3) !== "🏰") bad("chunkEmoji: zipf-0 order tie, got " + E(1, 10, g3));
  // no candidate has an emoji -> "" (empty beats bad)
  const g4 = JSON.parse(JSON.stringify(g));
  for (const k in g4.words) g4.words[k].e = "";
  if (E(0, 11, g4) !== "") bad("chunkEmoji: all-empty must be \"\"");
  // per-occurrence override changes the winner's emoji
  const g5 = JSON.parse(JSON.stringify(g));
  g5.overrides.s1 = { einhorn: { e: "🔒" } };
  if (E(1, 10, g5) !== "🔒") bad("chunkEmoji: override emoji, got " + E(1, 10, g5));
  console.log("ok  chunkEmoji rules (rarity, ents, fallthrough, tie, empty, override)");

  // grimm estimate with the generated test map (in-memory merge)
  const gloss = JSON.parse(fs.readFileSync(path.join(ROOT, "gloss", "grimm.json"), "utf8"));
  const map = JSON.parse(fs.readFileSync(
    path.join(__dirname, "..", "..", "tools", "v3", "build", "emoji_map_grimm.json"), "utf8"));
  for (const l in map)
    if (gloss.words[l] && !gloss.words[l].e) gloss.words[l].e = map[l];
  const book = JSON.parse(fs.readFileSync(path.join(ROOT, "de", "grimm.json"), "utf8"));
  for (const lv of ["beginner", "advanced"]) {
    const flat = Data3.flatten(book, lv);
    let withE = 0;
    flat.forEach((c) => { if (Data3.chunkEmoji(gloss, c.sent, c.a, c.b)) withE++; });
    console.log("ok  grimm/" + lv + " with test map: " + withE + "/" + flat.length +
      " chunks would show an emoji (" + Math.round(100 * withE / flat.length) + "%)");
  }
}

// ---------------- displayRuns + check-mode grading ----------------
{
  const Match = require("./js/match.js");

  // runs invariant on real data (kafka + alice, every chunk, beginner):
  // orig runs joined by " " == the chunk display text
  for (const id of [["de", "kafka"], ["en", "alice"]]) {
    const book = JSON.parse(fs.readFileSync(
      path.join(ROOT, id[0], id[1] + ".json"), "utf8"));
    const flat = Data3.flatten(book, "beginner");
    flat.forEach((c) => {
      const runs = Data3.displayRuns(c.sent, c.a, c.b);
      if (runs.map((r) => r.orig).join(" ") !== c.t.replace(/\s+/g, " "))
        bad(id[1] + " " + c.sid + ": displayRuns orig != chunk text");
    });
    console.log("ok  displayRuns invariant " + id[1] + " (" + flat.length + " chunks)");
  }

  // orth: modern runs differ exactly at the mapped token
  const sent = {
    id: "x",
    toks: ["Die", "Thür", "gieng", "auf", ",", "sprach", "Gregor", "."],
    sp: "11101100",
    ents: [[6, 7, "PER"]],
    orth: { "1": "Tür", "2": "ging" },
  };
  const runs = Data3.displayRuns(sent, 0, 8);
  if (runs.map((r) => r.orig).join(" ") !== "Die Thür gieng auf, sprach Gregor.")
    bad("displayRuns orig: " + runs.map((r) => r.orig).join(" "));
  if (runs.map((r) => r.modern).join(" ") !== "Die Tür ging auf, sprach Gregor.")
    bad("displayRuns modern: " + runs.map((r) => r.modern).join(" "));
  if (runs.map((r) => +r.ent).join("") !== "000001")
    bad("displayRuns ent flags: " + runs.map((r) => +r.ent).join(""));

  // check grading: modern ref, entity discounted
  const ref = runs.map((r) => r.modern).join(" ");
  const disc = runs.map((r) => r.ent);
  // speaker says everything except the name -> perfect score, name ok:null
  let r1 = Match.score(ref, "die tür ging auf sprach", disc);
  if (r1.score !== 1) bad("discount: missing name should not cost, score " + r1.score);
  if (r1.tokens[5].ok !== null) bad("discount: missed name must be ok:null");
  // speaker says the name too -> still 1, name marked ok:true
  let r2 = Match.score(ref, "die tür ging auf sprach gregor", disc);
  if (r2.score !== 1 || r2.tokens[5].ok !== true)
    bad("discount: spoken name should mark ok:true");
  // dictation returns modern forms: grading vs the modern ref is exact,
  // no reliance on the edit-distance mercy
  let r3 = Match.score(ref, "die tür ging", disc);
  if (r3.matched !== 3 || r3.total !== 5)
    bad("modern ref grading off: " + r3.matched + "/" + r3.total);
  // all-discounted reference passes trivially
  let r4 = Match.score("Gregor", "x", [true]);
  if (r4.score !== 1) bad("all-discounted ref must score 1");
  // no-discount call keeps v2 behavior
  let r5 = Match.score("die Tür", "die tür");
  if (r5.score !== 1 || r5.total !== 2) bad("v2-compatible score broken");
  console.log("ok  check grading (modern ref, entity discount, v2 compat)");
}

// ---------------- rungs + ladder ----------------
// Data invariants (02 schema): every rung ⊆ cuts.advanced; successive
// rungs nest (coarse→fine); no rung is empty or equals the advanced cut
// set (the app appends both ends of the ladder). Then ladderRanges
// behavior: ranges tile the sentence per rung, rungs come out
// fine→coarse, the whole sentence is last, and a rung equal to the
// level's cuts is skipped.
{
  const sub = (x, y) => x.every((v) => y.includes(v));
  for (const meta of index.books) {
    const book = JSON.parse(fs.readFileSync(
      path.join(ROOT, meta.lang, meta.id + ".json"), "utf8"));
    let withRungs = 0;
    book.sections.forEach((s) => s.sentences.forEach((sent) => {
      const rungs = sent.rungs || [];
      if (!rungs.length) return;
      withRungs++;
      const adv = (sent.cuts && sent.cuts.advanced) || [];
      rungs.forEach((r, i) => {
        if (!r.length) bad(meta.id + " " + sent.id + ": empty rung");
        if (!sub(r, adv)) bad(meta.id + " " + sent.id + ": rung ⊄ advanced");
        if (JSON.stringify(r) === JSON.stringify(adv))
          bad(meta.id + " " + sent.id + ": rung == advanced cuts");
        if (i && !sub(rungs[i - 1], r))
          bad(meta.id + " " + sent.id + ": rungs do not nest");
      });
      // ladder from every level: tiles, fine→coarse, whole last
      for (const lv of meta.levels) {
        const ranges = Data3.ladderRanges(sent, lv);
        const last = ranges[ranges.length - 1];
        if (last[0] !== 0 || last[1] !== sent.toks.length)
          bad(meta.id + " " + sent.id + ": ladder must end with the whole sentence");
        let pos = 0, sizes = [];
        ranges.slice(0, -1).forEach((r) => {
          if (r[0] !== pos && r[0] !== 0)
            bad(meta.id + " " + sent.id + ": ladder ranges do not tile");
          if (r[0] === 0) { if (pos !== 0) sizes.push(pos); }  // new rung started
          pos = r[1];
        });
        // piece count per rung must strictly DECREASE (fine→coarse)
        const counts = [];
        let cnt = 0;
        ranges.slice(0, -1).forEach((r) => {
          if (r[0] === 0 && cnt) { counts.push(cnt); cnt = 0; }
          cnt++;
        });
        if (cnt) counts.push(cnt);
        for (let i = 1; i < counts.length; i++)
          if (counts[i] >= counts[i - 1])
            bad(meta.id + " " + sent.id + "/" + lv + ": ladder not fine→coarse: " + counts);
      }
    }));
    console.log("ok  rungs " + meta.id + "  " + withRungs + " sentences with a ladder");
  }

  // level-dedup: a synthetic rung equal to the level's cuts is skipped
  const sent = { toks: "a b c d e f".split(" "), sp: "111110",
                 cuts: { advanced: [3], beginner: [3] }, rungs: [[3]] };
  const r = Data3.ladderRanges(sent, "beginner");
  if (r.length !== 1 || r[0][0] !== 0 || r[0][1] !== 6)
    bad("ladder level-dedup: rung equal to level cuts must be skipped, got " +
        JSON.stringify(r));
  // no rungs at all -> just the whole sentence
  const r2 = Data3.ladderRanges({ toks: ["x", "y"], sp: "10", cuts: {} }, "starter");
  if (r2.length !== 1) bad("ladder without rungs must be [whole]");
  console.log("ok  ladderRanges semantics (tiling, order, dedup, no-rungs)");
}

console.log(fails ? fails + " FAILURES" : "ALL CHECKS PASSED");
process.exit(fails ? 1 : 0);
