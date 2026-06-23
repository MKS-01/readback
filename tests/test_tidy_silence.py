"""_tidy_silence — leading/trailing trim + internal-pause capping."""
import numpy as np

from readback.pipeline.speak import _tidy_silence

SR = 1000  # 1 sample == 1 ms, keeps the math obvious


def _voiced(n):
    return np.ones(n, dtype=np.float32)


def _silent(n):
    return np.zeros(n, dtype=np.float32)


def test_all_silence_is_dropped():
    out = _tidy_silence(_silent(500), SR)
    assert out.size == 0


def test_leading_and_trailing_silence_trimmed():
    audio = np.concatenate([_silent(500), _voiced(100), _silent(500)])
    out = _tidy_silence(audio, SR, pad_ms=40)
    # voiced region (100) + at most a pad on each side, far less than the original.
    assert out.size < audio.size
    assert 100 <= out.size <= 100 + 2 * 40 + 2


def test_internal_pause_capped():
    # 1000 ms of internal silence between two voiced runs, capped to 300 ms.
    audio = np.concatenate([_voiced(100), _silent(1000), _voiced(100)])
    out = _tidy_silence(audio, SR, pad_ms=40, max_pause_ms=300)
    # ~ 100 + 300 + 100; allow a small slop for boundary handling.
    assert 480 <= out.size <= 520


def test_pure_voiced_is_left_intact():
    audio = _voiced(200)
    out = _tidy_silence(audio, SR)
    assert out.size == 200
    assert np.allclose(out, 1.0)
