# tools/v3/vendor — offline data for gloss3.py

Downloads are gitignored (see repo .gitignore); re-fetch with
`python3 tools/v3/gloss3.py --fetch`.

| file | source | fetched | license |
|---|---|---|---|
| freedict-deu-eng-1.9-fd1.dictd.tar.xz → `deu-eng/` | https://download.freedict.org/dictionaries/deu-eng/1.9-fd1/freedict-deu-eng-1.9-fd1.dictd.tar.xz | 2026-07-11 | GPL (see `deu-eng/COPYING`) |
| cldr/annotations_de.json, cldr/annotations_en.json | https://raw.githubusercontent.com/unicode-org/cldr-json/main/cldr-json/cldr-annotations-full/annotations/{de,en}/annotations.json | 2026-07-11 | Unicode License v3 |
| dict-wn_3.0-41_all.deb → `wn/` | http://ftp.debian.org/debian/pool/main/w/wordnet/dict-wn_3.0-41_all.deb | 2026-07-11 | WordNet 3.0 license (Princeton) |

WordNet (dictd build) is the eng-eng source for English books:
same-language definitions, same dictd container as FreeDict so the same
reader parses both. Known limitation: WordNet sense order is not
frequency order (first sense of "turtle" is the sweater).

FreeDict deu-eng was chosen as the primary gloss source (06 spec asked
to pick FreeDict vs kaikki after a coverage check): dictd format is
dependency-free to parse, entries carry clean one-line translations, and
kaikki's de extract is hundreds of MB for marginal gain at the "one-line
gloss" quality bar. `dict_version` in generated gloss files records this
snapshot; changing it is a regeneration trigger like `parse_model`.
