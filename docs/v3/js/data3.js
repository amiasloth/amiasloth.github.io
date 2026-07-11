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

  /* Same normalisation as the build side (gloss3.py nfc_lower). */
  function nfcLower(s) {
    return String(s).normalize("NFC").toLowerCase();
  }

  // own-property map read (never fish helpers off Object.prototype)
  function get(map, key) {
    return map && Object.prototype.hasOwnProperty.call(map, key)
      ? map[key] : undefined;
  }

  /* Gloss lookup for token k of a sentence, mirroring the build:
   * orth-modernised surface → nfcLower → forms → lemma → words[lemma],
   * with the per-occurrence `overrides[sid][lemma]` layer merged on top
   * (sense exceptions, per the pinned schema — empty today).
   * Returns { surface, modern, lemma, entry, isEnt }:
   *   surface = token as printed; modern = orth form used for lookup;
   *   lemma   = normalised lemma or null (forms is book-complete, so a
   *             miss usually means punctuation or an entity);
   *   entry   = {l, g_en, g_de?, e} or null (words holds only rare
   *             lemmas — common words gloss to lemma-only);
   *   isEnt   = token sits inside a named-entity span (gloss skips
   *             names by design; ents is the single source of truth). */
  function glossLookup(gloss, sent, k) {
    var isEnt = false;
    if (sent.ents) {
      for (var i = 0; i < sent.ents.length; i++)
        if (k >= sent.ents[i][0] && k < sent.ents[i][1]) { isEnt = true; break; }
    }
    var raw = sent.toks[k];
    var modern = get(sent.orth, String(k)) || raw;
    var key = nfcLower(modern);
    var lemma = get(gloss.forms, key);
    if (lemma === undefined) lemma = get(gloss.words, key) ? key : null;
    var entry = null;
    if (lemma) {
      var base = get(gloss.words, lemma);
      var ov = get(get(gloss.overrides, sent.id), lemma);
      if (base || ov) {
        entry = {};
        var f;
        for (f in base || {}) entry[f] = base[f];
        for (f in ov || {}) entry[f] = ov[f];
      }
    }
    return { surface: raw, modern: modern, lemma: lemma, entry: entry, isEnt: isEnt };
  }

  var WORD_RE = /[\p{L}\p{N}]/u;   // token contains a letter/digit

  /* Chunk emoji, computed at runtime (02 schema notes): the emoji of
   * the chunk's RAREST glossed non-entity word that HAS a non-empty
   * emoji — rarity (lemma zipf, missing/OOV = 0 = rarest) is the proxy
   * for "the word the learner most likely does not know". Repeated
   * lemmas are deduplicated; zipf ties (OOV compounds) break by word
   * order (first wins); per-occurrence sense overrides are honoured via
   * glossLookup. Returns "" when no candidate has an emoji — empty
   * beats bad. */
  function chunkEmoji(gloss, sent, a, b) {
    var seen = {}, bestE = "", bestZ = Infinity;
    for (var k = a; k < b; k++) {
      if (!WORD_RE.test(sent.toks[k])) continue;
      var r = glossLookup(gloss, sent, k);
      if (r.isEnt || !r.lemma || !r.entry) continue;   // glossed words only
      if (seen[r.lemma]) continue;
      seen[r.lemma] = 1;
      if (!r.entry.e) continue;               // fall through to next rarest
      var z = get(gloss.freq, r.lemma);
      if (z == null) z = 0;                   // OOV = maximally rare
      if (z < bestZ) { bestZ = z; bestE = r.entry.e; }   // strict <: first wins ties
    }
    return bestE;
  }

  /* Display runs of the token slice [a, b): the whitespace-separated
   * units the reader shows (tokens glue to the next one when their sp
   * bit is 0 — "sah" + "," renders as "sah,"). Per run: the original
   * text, the orth-modernised text, and whether any glued token sits in
   * an entity span. Check mode builds its reference (modern), its
   * entity-discount vector and its diff display (orig or modern) from
   * ONE runs array, so the three always align token-for-token. */
  function displayRuns(sent, a, b) {
    var ents = null;
    if (sent.ents && sent.ents.length) {
      ents = {};
      sent.ents.forEach(function (sp) {
        for (var k = sp[0]; k < sp[1]; k++) ents[k] = 1;
      });
    }
    var runs = [], orig = "", modern = "", ent = false;
    for (var k = a; k < b; k++) {
      orig += sent.toks[k];
      modern += get(sent.orth, String(k)) || sent.toks[k];
      if (ents && ents[k]) ent = true;
      if (sent.sp.charAt(k) === "1" || k === b - 1) {
        if (orig) runs.push({ orig: orig, modern: modern, ent: ent });
        orig = ""; modern = ""; ent = false;
      }
    }
    return runs;
  }

  /* Progressive-rung ladder for one sentence at one level: the token
   * ranges [a, b) to practice AFTER the level's own chunks, in order.
   * Rungs are stored coarse→fine ([[18],[18,29]] = halves, thirds) and
   * hold only distinct intermediate steps — so the ladder walks them in
   * REVERSE (fine→coarse: thirds before halves), skips a rung equal to
   * the level's own cut set (nothing repeats), and always ends with the
   * whole sentence. Valid from any level: every rung ⊆ cuts.advanced ⊆
   * every finer level's cuts. */
  function ladderRanges(sent, level) {
    var n = sent.toks.length;
    var out = [];
    var lvl = JSON.stringify((sent.cuts && sent.cuts[level]) || []);
    var rungs = sent.rungs || [];
    for (var i = rungs.length - 1; i >= 0; i--) {
      if (JSON.stringify(rungs[i]) === lvl) continue;
      var bnd = [0].concat(rungs[i], [n]);
      for (var j = 0; j + 1 < bnd.length; j++) out.push([bnd[j], bnd[j + 1]]);
    }
    out.push([0, n]);
    return out;
  }

  var Data3 = {
    sliceText: sliceText,
    displayRuns: displayRuns,
    ladderRanges: ladderRanges,
    boundaries: boundaries,
    flatten: flatten,
    findPosition: findPosition,
    nfcLower: nfcLower,
    glossLookup: glossLookup,
    chunkEmoji: chunkEmoji,
  };

  global.Data3 = Data3;
  if (typeof module !== "undefined" && module.exports) module.exports = Data3;
})(typeof window !== "undefined" ? window : this);
