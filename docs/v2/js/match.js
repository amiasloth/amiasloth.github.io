/* Zzzpeak v2 — Check mode text scoring (Phase 04).
 *
 * PURE functions, no DOM, no globals beyond the exported `Match`. Runs in
 * the browser (attaches window.Match) and in Node (module.exports) so the
 * same code is unit-tested — see docs/v2/test_match.html.
 *
 * Semantics are deliberately FORGIVING: this checks word RECALL, not
 * pronunciation. Dictation returns modern spellings and sometimes digits,
 * so archaic forms (Thür/Tür, daß/dass, gieng/ging) and number words
 * (drei == 3) are treated as matches.
 */
(function (global) {
  "use strict";

  // Spoken-number ↔ digit equivalence, 0–12, de + en. Keys are already in
  // normWord() form (lowercase, umlauts kept, ß→ss).
  var NUMS = {
    // de
    "null": 0, "eins": 1, "ein": 1, "eine": 1, "zwei": 2, "drei": 3,
    "vier": 4, "fünf": 5, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "zwoelf": 12,
    // en
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12
  };

  // Normalize ONE token: NFC, lowercase, ß→ss, keep a–z 0–9 and umlauts,
  // drop everything else (punctuation, quotes, dashes). May return "".
  function normWord(w) {
    if (w == null) return "";
    w = String(w).normalize("NFC").toLowerCase().replace(/ß/g, "ss");
    return w.replace(/[^a-z0-9äöü]/g, "");
  }

  // Normalize a whole string into an array of word tokens.
  function normalizeWords(text) {
    if (text == null) return [];
    var s = String(text).normalize("NFC").toLowerCase().replace(/ß/g, "ss");
    s = s.replace(/[^a-z0-9äöü]+/g, " ").trim();
    return s ? s.split(" ") : [];
  }

  function numCanon(w) {
    if (/^\d+$/.test(w)) return String(parseInt(w, 10));
    if (Object.prototype.hasOwnProperty.call(NUMS, w)) return String(NUMS[w]);
    return null;
  }

  function levenshtein(a, b) {
    if (a === b) return 0;
    var la = a.length, lb = b.length;
    if (!la) return lb;
    if (!lb) return la;
    var prev = new Array(lb + 1), cur = new Array(lb + 1), i, j;
    for (j = 0; j <= lb; j++) prev[j] = j;
    for (i = 1; i <= la; i++) {
      cur[0] = i;
      var ca = a.charCodeAt(i - 1);
      for (j = 1; j <= lb; j++) {
        var cost = ca === b.charCodeAt(j - 1) ? 0 : 1;
        var m = prev[j] + 1;               // deletion
        var d = cur[j - 1] + 1;            // insertion
        var s = prev[j - 1] + cost;        // substitution
        cur[j] = m < d ? (m < s ? m : s) : (d < s ? d : s);
      }
      var tmp = prev; prev = cur; cur = tmp;
    }
    return prev[lb];
  }

  /* Does a reference word match a hypothesis word? Forgiving:
   *  - exact after normalization, OR
   *  - same number value (drei == 3), OR
   *  - within edit distance 1 for ref words ≤5 chars, distance 2 for longer.
   * Threshold keys off the reference word length. */
  function wordMatch(refW, hypW) {
    if (!refW || !hypW) return false;
    if (refW === hypW) return true;
    var nr = numCanon(refW), nh = numCanon(hypW);
    if (nr !== null && nh !== null) return nr === nh;
    var thr = refW.length <= 5 ? 1 : 2;
    return levenshtein(refW, hypW) <= thr;
  }

  /* Word-level alignment (WER-style DP). Returns a boolean array over the
   * reference words: true = matched to some hypothesis word, false = missed
   * (deleted or substituted). Insertions in the hypothesis are ignored. */
  // A genuine substitution (two different real words) costs MORE than an
  // insert+delete pair, so the DP never "wastes" a mismatched alignment on
  // words that could match later. Net effect: a reference word is marked
  // matched only when some hypothesis word actually matches it in order;
  // everything else is a deletion (miss). Handles word-order slips well.
  var SUB = 3, INDEL = 1;

  function alignMarks(refWords, hypWords) {
    var n = refWords.length, m = hypWords.length, i, j;
    if (!n) return [];
    var dp = [];
    for (i = 0; i <= n; i++) { dp[i] = new Array(m + 1); dp[i][0] = i * INDEL; }
    for (j = 0; j <= m; j++) dp[0][j] = j * INDEL;
    for (i = 1; i <= n; i++) {
      for (j = 1; j <= m; j++) {
        var diag = dp[i - 1][j - 1] + (wordMatch(refWords[i - 1], hypWords[j - 1]) ? 0 : SUB);
        var del = dp[i - 1][j] + INDEL;   // ref word unmatched
        var ins = dp[i][j - 1] + INDEL;   // extra hyp word
        dp[i][j] = diag < del ? (diag < ins ? diag : ins) : (del < ins ? del : ins);
      }
    }
    var marks = new Array(n);
    i = n; j = m;
    while (i > 0 || j > 0) {
      if (i > 0 && j > 0 && wordMatch(refWords[i - 1], hypWords[j - 1]) &&
          dp[i][j] === dp[i - 1][j - 1]) {
        marks[i - 1] = true; i--; j--; continue;   // real match
      }
      if (i > 0 && dp[i][j] === dp[i - 1][j] + INDEL) { marks[i - 1] = false; i--; continue; }
      if (j > 0 && dp[i][j] === dp[i][j - 1] + INDEL) { j--; continue; }
      // fallback: forced substitution (only when no cheaper path existed)
      marks[i - 1] = false; i--; j--;
    }
    return marks;
  }

  /* Score a spoken hypothesis against the reference text.
   * Returns:
   *   { score, matched, total, tokens }
   * where `tokens` covers every whitespace-split token of the ORIGINAL
   * reference (so it can be rendered verbatim). Each token:
   *   { display, ok }  ok === true|false for scorable words,
   *                    ok === null for punctuation-only tokens (not scored). */
  function score(reference, hypothesis) {
    var display = String(reference == null ? "" : reference).split(/\s+/).filter(Boolean);
    var refNorm = display.map(normWord);
    var scorableIdx = [];
    for (var k = 0; k < refNorm.length; k++) if (refNorm[k]) scorableIdx.push(k);
    var refWords = scorableIdx.map(function (i) { return refNorm[i]; });
    var hypWords = normalizeWords(hypothesis);

    var marks = alignMarks(refWords, hypWords);
    var matched = 0;
    for (var a = 0; a < marks.length; a++) if (marks[a]) matched++;
    var total = refWords.length;
    var scoreVal = total ? matched / total : 1;

    // Map marks back onto the display tokens.
    var pos = 0;
    var tokens = display.map(function (d, i) {
      if (!refNorm[i]) return { display: d, ok: null };
      var ok = marks[pos]; pos++;
      return { display: d, ok: !!ok };
    });

    return { score: scoreVal, matched: matched, total: total, tokens: tokens };
  }

  var Match = {
    PASS: 0.75,
    score: score,
    // exposed for unit tests
    normWord: normWord,
    normalizeWords: normalizeWords,
    wordMatch: wordMatch,
    levenshtein: levenshtein,
    numCanon: numCanon
  };

  global.Match = Match;
  if (typeof module !== "undefined" && module.exports) module.exports = Match;
})(typeof window !== "undefined" ? window : this);
