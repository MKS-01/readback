"""synthesize_article — fade-out tail + degenerate-chunk retry."""
import numpy as np

from readback.pipeline.speak import _fade_out_tail, synthesize_article

SR = 24000


def test_fade_out_tail_ramps_to_zero():
    audio = np.ones(SR, dtype=np.float32)  # 1 second of DC
    out = _fade_out_tail(audio, SR, fade_ms=100)
    fade_n = int(0.1 * SR)
    # Untouched prefix
    np.testing.assert_array_equal(out[:-fade_n], 1.0)
    # Last sample should be ~0
    assert abs(out[-1]) < 1e-5
    # Monotonically decreasing in the fade region
    diffs = np.diff(out[-fade_n:])
    assert (diffs <= 0).all()


class _FakeSynth:
    """Minimal synth stub for synthesize_article tests."""
    sample_rate = SR

    def __init__(self, chunks):
        self._chunks = iter(chunks)

    def synthesize(self, _text):
        return next(self._chunks)


def test_degenerate_chunk_retried():
    voiced = np.ones(1000, dtype=np.float32)
    silence = np.zeros(1000, dtype=np.float32)
    # First call returns silence, second (retry) returns voiced audio.
    synth = _FakeSynth([silence, voiced])
    out = synthesize_article(synth, "Hello world test.")
    assert out.size > 0


def test_degenerate_chunk_dropped_after_two_failures():
    silence = np.zeros(1000, dtype=np.float32)
    synth = _FakeSynth([silence, silence])
    out = synthesize_article(synth, "Hello world test.")
    assert out.size == 0
