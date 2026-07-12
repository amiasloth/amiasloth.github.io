"""Unit tests for audio3.synth_with_timing's run-timing extraction.

Pure-logic tests with a fake voice — no piper, no opus-tools needed
(the BOS/EOS import inside synth_with_timing falls back to '^'/'$').
Run: python3 -m pytest tools/v3/test_audio3_timing.py
"""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio3 import synth_with_timing  # noqa: E402

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
