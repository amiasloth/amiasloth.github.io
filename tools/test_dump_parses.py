#!/usr/bin/env python3
"""End-to-end chunk_sentence tests on REAL parses, no model needed.

The German parses below are transcribed verbatim from
debug/parse_dump.out (de_core_news_lg, 2026-07-08) and rebuilt as
spaCy Docs by hand — so chunk_sentence runs exactly the path it runs
in production, in any environment (the models themselves cannot be
downloaded in the sandbox; spaCy the library installs fine).

These lock in the 2026-07 fixes:
  - fallback fusion veto      ("während an |", "nur durch |" gone)
  - max+1 stretch             ("Und wenn es ein Gitter wird," whole)
  - pronoun-clitic fusion     ("stand er", "verwandelte sich" atomic)
  - dash spacing in clean()   ("Herz,—und" cut apart, dash opens)
  - comma-transparent good_cut (no "und, |" strandings)

Run:  python test_dump_parses.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spacy
from spacy.tokens import Doc

from chunk import LANG_CFG, LEVELS, chunk_sentence, clean

DE = LANG_CFG["de"]
# a bare Vocab() has no German lexical attributes — is_punct would be
# False on "," and corrupt word counts; blank("de") needs no model
VOCAB = spacy.blank("de").vocab
failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
        print(f"  FAIL {name}:")
        for g in got:
            print(f"         {g!r}")
        print(f"       wanted:")
        for w in want:
            print(f"         {w!r}")
    else:
        print(f"  ok   {name}")


def build(rows):
    """rows: (text, space_follows, tag, pos, dep, head_index)"""
    doc = Doc(VOCAB,
              words=[r[0] for r in rows],
              spaces=[r[1] for r in rows],
              tags=[r[2] for r in rows],
              pos=[r[3] for r in rows],
              deps=[r[4] for r in rows],
              heads=[r[5] for r in rows])
    return doc


def chunks(doc, level):
    lv = LEVELS[level]
    return [c.strip() for c in chunk_sentence(
        doc[:], DE, lv["min_words"], lv["target_words"], lv["max_words"])]


# ----------------------------------------------------------- clean()
print("clean() dash spacing")
got = clean("sein Herz,--und eines Morgens")
check("glued ,--und is spaced apart", [got],
      ["sein Herz, — und eines Morgens"])
nlp = spacy.blank("de")
check("result tokenizes with a free-standing dash",
      [[t.text for t in nlp(got)][2:5]], [[",", "—", "und"]])


# --------------------------------------------- Birnbaum (dump parse)
# "Säcke, Citronen- und Apfelsinenkisten standen hier an der einen
#  Wand entlang, während an der andern übereinandergeschichtete
#  Fässer lagen, Ölfässer, deren stattliche Reihe nur durch eine zum
#  Keller hinunterführende Fallthür unterbrochen war."
BIRNBAUM = build([
    ("Säcke", False, "NN", "NOUN", "sb", 5),
    (",", True, "$,", "PUNCT", "punct", 0),
    ("Citronen-", True, "TRUNC", "X", "cj", 3),
    ("und", True, "KON", "CCONJ", "cd", 4),
    ("Apfelsinenkisten", True, "NN", "NOUN", "cj", 0),
    ("standen", True, "VVFIN", "VERB", "ROOT", 5),
    ("hier", True, "ADV", "ADV", "mo", 5),
    ("an", True, "APPR", "ADP", "mo", 5),
    ("der", True, "ART", "DET", "nk", 10),
    ("einen", True, "ART", "ADJ", "nk", 10),
    ("Wand", True, "NN", "NOUN", "nk", 7),
    ("entlang", False, "APPO", "ADP", "svp", 5),
    (",", True, "$,", "PUNCT", "punct", 5),
    ("während", True, "KOUS", "SCONJ", "cp", 19),
    ("an", True, "APPR", "ADP", "mo", 19),
    ("der", True, "ART", "DET", "nk", 18),
    ("andern", True, "ADJA", "ADJ", "nk", 18),
    ("übereinandergeschichtete", True, "ADJA", "ADJ", "nk", 18),
    ("Fässer", True, "NN", "NOUN", "nk", 14),
    ("lagen", False, "VVFIN", "VERB", "mo", 5),
    (",", True, "$,", "PUNCT", "punct", 5),
    ("Ölfässer", False, "NN", "NOUN", "cj", 5),
    (",", True, "$,", "PUNCT", "punct", 21),
    ("deren", True, "PRELAT", "DET", "ag", 25),
    ("stattliche", True, "ADJA", "ADJ", "nk", 25),
    ("Reihe", True, "NN", "NOUN", "sb", 34),
    ("nur", True, "ADV", "ADV", "mo", 27),
    ("durch", True, "APPR", "ADP", "mo", 33),
    ("eine", True, "ART", "DET", "nk", 32),
    ("zum", True, "APPRART", "ADP", "mo", 31),
    ("Keller", True, "NN", "NOUN", "nk", 29),
    ("hinunterführende", True, "ADJA", "ADJ", "nk", 32),
    ("Fallthür", True, "NN", "NOUN", "nk", 27),
    ("unterbrochen", True, "VVPP", "VERB", "oc", 34),
    ("war", False, "VAFIN", "AUX", "rc", 21),
    (".", False, "$.", "PUNCT", "punct", 5),
])

print("Birnbaum extended attribute (beginner)")
check("no 'während an |' and no 'nur durch |'",
      chunks(BIRNBAUM, "beginner"),
      ["Säcke, Citronen-",
       "und Apfelsinenkisten standen hier",
       "an der einen Wand entlang,",
       "während an der andern übereinandergeschichtete Fässer",
       "lagen,",
       "Ölfässer, deren stattliche Reihe",
       "nur durch eine zum Keller",
       "hinunterführende Fallthür",
       "unterbrochen war."])


# ------------------------------------------- 'Und wenn' (dump parse)
# "Und wenn es ein Gitter wird, so ist es gut, und wenn dieser durch
#  die Weinstube ging, wollen wir wenigstens eine Rabatte ziehen."
UNDWENN = build([
    ("Und", True, "KON", "CCONJ", "ju", 8),
    ("wenn", True, "KOUS", "SCONJ", "cp", 5),
    ("es", True, "PPER", "PRON", "sb", 5),
    ("ein", True, "ART", "DET", "nk", 4),
    ("Gitter", True, "NN", "NOUN", "pd", 5),
    ("wird", False, "VAFIN", "AUX", "re", 7),
    (",", True, "$,", "PUNCT", "punct", 7),
    ("so", True, "ADV", "ADV", "mo", 8),
    ("ist", True, "VAFIN", "AUX", "ROOT", 8),
    ("es", True, "PPER", "PRON", "sb", 8),
    ("gut", False, "ADJD", "ADV", "pd", 8),
    (",", True, "$,", "PUNCT", "punct", 8),
    ("und", True, "KON", "CCONJ", "cd", 8),
    ("wenn", True, "KOUS", "SCONJ", "cp", 18),
    ("dieser", True, "PDS", "PRON", "sb", 18),
    ("durch", True, "APPR", "ADP", "mo", 18),
    ("die", True, "ART", "DET", "nk", 17),
    ("Weinstube", True, "NN", "NOUN", "nk", 15),
    ("ging", False, "VVFIN", "VERB", "mo", 20),
    (",", True, "$,", "PUNCT", "punct", 20),
    ("wollen", True, "VMFIN", "AUX", "cj", 12),
    ("wir", True, "PPER", "PRON", "sb", 20),
    ("wenigstens", True, "ADV", "ADV", "mo", 25),
    ("eine", True, "ART", "DET", "nk", 24),
    ("Rabatte", True, "NN", "NOUN", "oa", 25),
    ("ziehen", False, "VVINF", "VERB", "oc", 20),
    (".", False, "$.", "PUNCT", "punct", 8),
])

print("'Und wenn' subordinate clauses (beginner)")
check("subordinate clause stays whole via max+1 stretch",
      chunks(UNDWENN, "beginner"),
      ["Und wenn es ein Gitter wird,",
       "so ist es gut,",
       "und wenn dieser durch die Weinstube",
       "ging,",
       "wollen wir",
       "wenigstens eine Rabatte ziehen."])


# ------------------------- Zarathustra with the dash FIX applied
# (plausible parse of the correctly tokenized sentence; the dump's
# parse had the glued 'Herz,—und' token)
ZARA = build([
    ("Endlich", True, "ADV", "ADV", "mo", 2),
    ("aber", True, "ADV", "ADV", "mo", 2),
    ("verwandelte", True, "VVFIN", "VERB", "mo", 18),
    ("sich", True, "PRF", "PRON", "oa", 2),
    ("sein", True, "PPOSAT", "DET", "nk", 5),
    ("Herz", False, "NN", "NOUN", "sb", 2),
    (",", True, "$,", "PUNCT", "punct", 2),
    ("—", True, "$(", "PUNCT", "punct", 8),
    ("und", True, "KON", "CCONJ", "cd", 2),
    ("eines", True, "ART", "DET", "nk", 10),
    ("Morgens", True, "NN", "NOUN", "mo", 11),
    ("stand", True, "VVFIN", "VERB", "cj", 8),
    ("er", True, "PPER", "PRON", "sb", 11),
    ("mit", True, "APPR", "ADP", "mo", 11),
    ("der", True, "ART", "DET", "nk", 15),
    ("Morgenröthe", True, "NN", "NOUN", "nk", 13),
    ("auf", False, "PTKVZ", "ADP", "svp", 11),
    (",", True, "$,", "PUNCT", "punct", 18),
    ("trat", True, "VVFIN", "VERB", "ROOT", 18),
    ("vor", True, "APPR", "ADP", "mo", 18),
    ("die", True, "ART", "DET", "nk", 21),
    ("Sonne", True, "NN", "NOUN", "nk", 19),
    ("hin", True, "PTKVZ", "ADV", "svp", 18),
    ("und", True, "KON", "CCONJ", "cd", 18),
    ("sprach", True, "VVFIN", "VERB", "cj", 23),
    ("zu", True, "APPR", "ADP", "mo", 24),
    ("ihr", True, "PPER", "PRON", "nk", 25),
    ("also", False, "ADV", "ADV", "mo", 24),
    (":", False, "$.", "PUNCT", "punct", 24),
])

print("Zarathustra opening (starter)")
check("clitics hug their verb; dash opens the next chunk",
      chunks(ZARA, "starter"),
      ["Endlich aber verwandelte sich",
       "sein Herz,",
       "— und eines Morgens",
       "stand er",
       "mit der Morgenröthe auf,",
       "trat",
       "vor die Sonne hin",
       "und sprach",
       "zu ihr also:"])

print("Zarathustra opening (beginner)")
check("no clause mixing: 'stand er' stays in clause 2",
      chunks(ZARA, "beginner"),
      ["Endlich aber verwandelte sich",
       "sein Herz,",
       "— und eines Morgens stand er",
       "mit der Morgenröthe auf,",
       "trat vor die Sonne hin",
       "und sprach zu ihr also:"])

print(f"\nfailures: {failures}")
sys.exit(1 if failures else 0)
