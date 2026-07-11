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
console.log(fails ? fails + " FAILURES" : "ALL CHECKS PASSED");
process.exit(fails ? 1 : 0);
