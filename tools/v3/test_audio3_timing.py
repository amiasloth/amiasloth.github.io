"""Unit tests for audio3.synth_with_timing's run-timing extraction.

Pure-logic tests with a fake voice — no piper, no opus-tools needed
(the BOS/EOS import inside synth_with_timing falls back to '^'/'$').
Run: python3 -m pytest tools/v3/test_audio3_timing.py
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio3 import run_ends_from_words, synth_with_timing  # noqa: E402

RATE = 22050


class Align:
    def __init__(self, phoneme, num_samples):
        self.phoneme = phoneme
        self.num_samples = num_samples


class Chunk:
    def __init__(self, aligns):
        self.phoneme_alignments = aligns
        n = sum(a.num_samples for a in aligns) if aligns else 100
        self.audio_int16_bytes = b"\x00\x00" * n
        self.audio_int16_array = [0] * n


class FakeVoice:
    def __init__(self, chunks):
        self.config = types.SimpleNamespace(sample_rate=RATE)
        self._chunks = chunks

    def synthesize(self, text, include_alignments=False):
        return iter(self._chunks)


def W(*samples):        # a word: one alignment entry per phoneme
    return [Align("x", s) for s in samples]


def test_two_words(tmp_path):
    # ^ [w1] ' ' [w2] $  ->  ends at w1-end and w2-end
    chunks = [Chunk([Align("^", 10)] + W(100, 50) + [Align(" ", 40)]
                    + W(200) + [Align("$", 20)])]
    dur, ends = synth_with_timing(FakeVoice(chunks), "Hallo Welt",
                                  tmp_path / "t.wav")
    assert ends == [round(160 / RATE, 3), round(400 / RATE, 3)]
    assert dur == round(420 / RATE, 2)


def test_glued_punctuation_belongs_to_word(tmp_path):
    # "sah," phonemizes as word phonemes + ',' pause — one run
    chunks = [Chunk([Align("^", 0)] + W(80) + [Align(",", 30)]
                    + [Align(" ", 10)] + W(60) + [Align("$", 0)])]
    dur, ends = synth_with_timing(FakeVoice(chunks), "sah, dann",
                                  tmp_path / "t.wav")
    assert ends == [round(110 / RATE, 3), round(180 / RATE, 3)]


def test_multi_chunk_sentence_split(tmp_path):
    # piper re-splits on sentence punctuation: chunk boundary closes
    # the word even without a trailing space phoneme
    chunks = [Chunk([Align("^", 0)] + W(100) + [Align("$", 20)]),
              Chunk([Align("^", 5)] + W(100) + [Align("$", 0)])]
    dur, ends = synth_with_timing(FakeVoice(chunks), "Ja. Nein.",
                                  tmp_path / "t.wav")
    assert ends == [round(100 / RATE, 3), round(225 / RATE, 3)]


def test_run_count_mismatch_returns_none(tmp_path):
    # espeak dropped a unit (e.g. bare em-dash run) -> no timing
    chunks = [Chunk([Align("^", 0)] + W(100) + [Align("$", 0)])]
    dur, ends = synth_with_timing(FakeVoice(chunks), "wort — hier",
                                  tmp_path / "t.wav")
    assert ends is None
    assert dur is not None


def test_no_alignments_returns_none(tmp_path):
    chunks = [Chunk(None)]
    dur, ends = synth_with_timing(FakeVoice(chunks), "Hallo",
                                  tmp_path / "t.wav")
    assert ends is None
    assert dur is not None


def test_double_space_phoneme(tmp_path):
    # consecutive space phonemes must not create a phantom word
    chunks = [Chunk([Align("^", 0)] + W(50) + [Align(" ", 10), Align(" ", 10)]
                    + W(50) + [Align("$", 0)])]
    dur, ends = synth_with_timing(FakeVoice(chunks), "a b",
                                  tmp_path / "t.wav")
    assert ends == [round(50 / RATE, 3), round(120 / RATE, 3)]


# ---- word->run mapping (espeak fusion/expansion; run_ends_from_words) ----

class PhonemizingVoice(FakeVoice):
    """FakeVoice + a solo phonemizer: each run maps to a fixed list of
    single-char phonemes (what espeak would say for the run alone)."""

    def __init__(self, chunks, solo):
        super().__init__(chunks)
        self._solo = solo

    def phonemize(self, text):
        return [list(self._solo[text])]


def test_fusion_two_runs_one_spoken_word(tmp_path):
    # espeak fuses "in the" -> one 4-phoneme word ('ɪnðə' style);
    # "house" is 1:1. Fused runs interpolate inside the word by their
    # solo phoneme lengths (2/2 -> midpoint), word edge stays exact.
    chunks = [Chunk([Align("^", 0)]
                    + W(100, 100, 100, 100) + [Align(" ", 0)]  # 'xxxx'
                    + W(100, 100, 100, 100, 100)               # 'xxxxx'
                    + [Align("$", 0)])]
    voice = PhonemizingVoice(chunks, {"in": "xx", "the": "xx",
                                      "house": "xxxxx"})
    dur, ends = synth_with_timing(voice, "in the house", tmp_path / "t.wav")
    t_fused, t_house = 400 / RATE, 900 / RATE
    assert ends == [round(t_fused / 2, 3), round(t_fused, 3),
                    round(t_house, 3)]


def test_expansion_number_three_words_one_run(tmp_path):
    # "1922" -> three spoken words; the run ends when the LAST one does
    chunks = [Chunk([Align("^", 0)]
                    + W(100, 100, 100, 100, 100, 100) + [Align(" ", 0)]
                    + W(100, 100, 100, 100, 100, 100) + [Align(" ", 0)]
                    + W(100, 100, 100, 100, 100, 100) + [Align(" ", 0)]
                    + W(100, 100) + [Align("$", 0)])]
    voice = PhonemizingVoice(chunks, {"1922": "x" * 18, "ok": "xx"})
    dur, ends = synth_with_timing(voice, "1922 ok", tmp_path / "t.wav")
    assert ends == [round(1800 / RATE, 3), round(2000 / RATE, 3)]


def test_punct_only_run_sticks_to_previous_end():
    # '«' produces no spoken word: it inherits the preceding end
    # (0.0 at sentence start), alnum runs map 1:1
    ends = run_ends_from_words(["abc", "de"], [1.0, 2.0],
                               ["«", "wort", "—", "gut"],
                               lambda r: {"wort": 3, "gut": 2}.get(r, 0))
    assert ends == [0.0, 1.0, 1.0, 2.0]


def test_implausible_alignment_rejected():
    # one 20-phoneme word vs two 1-phoneme runs: cost blows the
    # per-word budget -> no timing rather than a wrong slice
    ends = run_ends_from_words(["x" * 20], [1.0], ["a", "b"],
                               lambda r: 1)
    assert ends is None
