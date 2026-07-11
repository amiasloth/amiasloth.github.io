/* Zzzpeak v3 — data3 derivation layer.
 *
 * The v3 book file (docs/data3/<lang>/<book>.json, schema 3) stores tokens
 * once; every level is a set of cut positions into the same token list
 * (see technical/v3_discussion/02_v3_data_schema.md). This module turns
 * that into the flat chunk list the v2-derived reader consumes:
 *   { t, cont, sec, secTitle, i, sid, occ, ci, sentStart, sentEnd,
 *     a, b, sent }
 * a/b = token range [a, b) of the chunk; sent = reference to the sentence
 * object (toks/sp/pos/ents/orth) for token-level rendering.
 *
 * PURE functions, no DOM. Attaches window.Data3 in the browser and
 * module.exports in Node so the derivation is unit-testable against the
 * build's invariants (chunk counts, reconstruction).
 */
(function (global) {
  "use strict";

  /* Text of the token slice [a, b) with per-token trailing-space bits.
   * `raw` keeps the trailing space of the last token (used by the
   * reconstruction test); display use trims it. */
  function sliceText(toks, sp, a, b, raw) {
    var out = "";
    for (var k = a; k < b; k++) {
      out += toks[k];
      if (sp.charAt(k) === "1") out += " ";
    }
    return raw ? out : out.replace(/\s+$/, "");
  }

  /* Chunk boundaries of one sentence at one level: [0, ...cuts, n].
   * Missing level or missing `cuts` = whole sentence is one chunk
   * (schema rev 2.1 omit-when-empty rule). */
  function boundaries(sent, level) {
    var cuts = (sent.cuts && sent.cuts[level]) || [];
    var b = [0];
    for (var k = 0; k < cuts.length; k++) b.push(cuts[k]);
    b.push(sent.toks.length);
    return b;
  }

  /* Flatten a book at a level into the reader's chunk list. */
  function flatten(book, level) {
    var flat = [];
    (book.sections || []).forEach(function (s, si) {
      (s.sentences || []).forEach(function (sent) {
        var bnd = boundaries(sent, level);
        var sentStart = flat.length;
        var sentEnd = sentStart + (bnd.length - 2); // bnd has nChunks+1 entries
        for (var c = 0; c + 1 < bnd.length; c++) {
          flat.push({
            t: sliceText(sent.toks, sent.sp, bnd[c], bnd[c + 1]),
            cont: c + 2 < bnd.length ? 1 : 0,   // more chunks follow in sentence
            sec: si,
            secTitle: s.title,
            i: flat.length,
            sid: sent.id,
            occ: sent.occ || 0,
            ci: c,                              // chunk index within sentence
            sentStart: sentStart,
            sentEnd: sentEnd,
            a: bnd[c],                          // token range [a, b)
            b: bnd[c + 1],
            sent: sent,                         // toks/sp/pos/ents/orth ref
          });
        }
      });
    });
    return flat;
  }

  /* Find the flat index for a saved position {sid, occ, ci}; -1 if the
   * sentence is gone (book rebuilt). ci is clamped into the sentence —
   * cut counts differ per level, so the chunk offset is best-effort. */
  function findPosition(flat, pos) {
    if (!pos || !pos.sid) return -1;
    for (var k = 0; k < flat.length; k++) {
      var c = flat[k];
      if (c.sid === pos.sid && c.occ === (pos.occ || 0)) {
        var ci = Math.min(pos.ci || 0, c.sentEnd - c.sentStart);
        return c.sentStart + ci;
      }
    }
    return -1;
  }

  var Data3 = {
    sliceText: sliceText,
    boundaries: boundaries,
    flatten: flatten,
    findPosition: findPosition,
  };

  global.Data3 = Data3;
  if (typeof module !== "undefined" && module.exports) module.exports = Data3;
})(typeof window !== "undefined" ? window : this);
