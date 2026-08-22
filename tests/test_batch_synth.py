"""Batched synthesis drive loop — order, progress, cancel, retry, fallback.

Pure logic: a fake synth stands in for CsmEngine, so these run on CI (no MLX).
"""
import numpy as np
import pytest

from readback.pipeline.speak import (
    _batches,
    _expressive_temperature,
    _length_buckets,
    _synthesize_batched,
    synthesize_article,
)

SR = 24000


def _voiced(n=2000):
    """Audio loud enough to survive _tidy_silence's -40 dB gate."""
    return np.full(n, 0.5, dtype=np.float32)


def _silence(n=2000):
    return np.zeros(n, dtype=np.float32)


class _BatchSynth:
    """Fake batching synth. Records every batch it was handed."""
    sample_rate = SR

    def __init__(self, batch_size=4, per_chunk=None, raises=False):
        self.batch_size = batch_size
        self.calls: list[list[tuple[str, float]]] = []
        self._per_chunk = per_chunk or {}
        self._raises = raises
        self._seen: dict[str, int] = {}

    def synthesize_batch(self, items):
        if self._raises:
            raise RuntimeError("engine exploded")
        self.calls.append(list(items))
        out = []
        for text, _temp in items:
            n = self._seen.get(text, 0)
            self._seen[text] = n + 1
            scripted = self._per_chunk.get(text)
            out.append(scripted[n] if scripted else _voiced())
        return out

    # sequential fallback surface
    def synthesize(self, _text):
        return _voiced()

    def set_temperature(self, _t):
        pass


def test_audio_returned_in_document_order_not_batch_order():
    # Lengths deliberately out of order so bucketing regroups them.
    chunks = ["a" * 10, "b" * 200, "c" * 50, "d" * 120]
    lengths = {c: 1000 * (i + 1) for i, c in enumerate(chunks)}
    synth = _BatchSynth(batch_size=2, per_chunk={c: [np.full(lengths[c], 0.5, np.float32)] for c in chunks})
    out = _synthesize_batched(synth, chunks, [None] * 4, SR, None, None)
    assert [a.size for a in out] == [1000, 2000, 3000, 4000]


def test_length_buckets_group_similar_lengths():
    chunks = ["x" * 10, "x" * 200, "x" * 20, "x" * 190]
    groups = _length_buckets(chunks, 2)
    assert sorted(len(g) for g in groups) == [2, 2]
    # shortest two together, longest two together
    assert set(groups[0]) == {0, 2}
    assert set(groups[1]) == {1, 3}


def test_batches_are_evened_out_not_strided():
    # 11 at size 8 must be 6+5, never 8+3: a runty tail batch costs nearly a
    # full batch's wall time (measured RTF 0.33 vs 0.26).
    assert [len(g) for g in _batches(list(range(11)), 8)] == [6, 5]
    assert [len(g) for g in _batches(list(range(17)), 8)] == [6, 6, 5]
    assert [len(g) for g in _batches(list(range(16)), 8)] == [8, 8]
    assert [len(g) for g in _batches(list(range(3)), 8)] == [3]
    assert _batches([], 8) == []
    # every chunk appears exactly once, order preserved
    flat = [i for g in _batches(list(range(11)), 4) for i in g]
    assert flat == list(range(11))


def test_frame_bounds_are_per_row_not_batch_wide():
    """A short row must keep its OWN generation budget inside a batch.

    Regression: the batch used one bound (the max over rows), so a short chunk
    that never emitted EOS kept generating on the longest chunk's budget and
    tailed off into babble — reported as "the ending is broken".
    """
    from readback.tts.csm_engine import frame_bounds

    items = [("short.", 0.8), ("x" * 400, 0.8)]
    bounds = frame_bounds(items, 30000)
    assert bounds[0] < bounds[1], "short row must not inherit the long row's budget"
    assert bounds[0] == 3000 // 80          # the floor, for a tiny chunk
    assert bounds[1] == 30000 // 80         # clamped by max_audio_length_ms
    # The cap has to clear a full-size chunk: 400 chars * 120 ms = 48 s of budget
    # demanded, so the configured ceiling is what bounds it.
    assert frame_bounds([("y" * 400, 0.8)], 20000)[0] == 20000 // 80


def test_progress_fires_once_per_chunk():
    chunks = ["one", "two", "three", "four", "five"]
    seen = []
    _synthesize_batched(_BatchSynth(batch_size=2), chunks, [None] * 5, SR,
                        lambda d, t: seen.append((d, t)), None)
    assert seen == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]


def test_should_stop_halts_between_batches():
    chunks = [f"chunk {i}" for i in range(8)]
    synth = _BatchSynth(batch_size=2)
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2      # allow two batches, then cancel

    out = _synthesize_batched(synth, chunks, [None] * 8, SR, None, stop)
    assert len(synth.calls) == 2
    assert sum(1 for a in out if a.size) == 4      # only the first two batches


def test_all_silence_chunk_is_retried_once():
    chunks = ["quiet one", "loud one"]
    synth = _BatchSynth(batch_size=2, per_chunk={"quiet one": [_silence(), _voiced()]})
    out = _synthesize_batched(synth, chunks, [None] * 2, SR, None, None)
    assert out[0].size > 0                      # recovered on retry
    assert len(synth.calls) == 2                # original batch + retry batch


def test_per_chunk_temperature_reaches_the_engine():
    chunks = ["Plain statement here.", "Wow, amazing!", "Really?"]
    base = 0.7
    temps = [_expressive_temperature(c, base) for c in chunks]
    synth = _BatchSynth(batch_size=8)
    _synthesize_batched(synth, chunks, temps, SR, None, None)
    handed = {text: temp for text, temp in synth.calls[0]}
    assert handed["Wow, amazing!"] == pytest.approx(0.78)   # "!" → +0.08
    assert handed["Really?"] == pytest.approx(0.74)         # "?" → +0.04
    assert handed["Plain statement here."] == pytest.approx(0.70)


def test_batch_size_one_uses_sequential_path():
    assert _synthesize_batched(_BatchSynth(batch_size=1), ["a"], [None], SR, None, None) is None


def test_engine_without_batch_support_uses_sequential_path():
    class _Plain:
        sample_rate = SR

        def synthesize(self, _t):
            return _voiced()

    assert _synthesize_batched(_Plain(), ["a"], [None], SR, None, None) is None


def test_batch_failure_falls_back_to_sequential():
    synth = _BatchSynth(batch_size=4, raises=True)
    # synthesize_article must still produce audio via the sequential loop.
    out = synthesize_article(synth, "A sentence that will be synthesized anyway.")
    assert out.size > 0


# ---- padding attention mask (needs MLX; skipped on CI/Linux) ----

def _mask_helpers():
    pytest.importorskip("mlx.core")
    from readback.tts.csm_engine import _pad_key_mask, _prefill_mask

    return _pad_key_mask, _prefill_mask


def test_pad_keys_are_masked_out_of_attention():
    """⚠ The quality fix: real tokens must NOT attend to a row's left pads.

    Unmasked, each pad contributes a zero-valued key scoring q·0 = 0, i.e. weight
    exp(0)=1 in every softmax — measured flattening of the codebook-0 top-1
    probability from 0.193 to 0.049 at 8 pads, heard as a muffled voice.
    """
    pad_key_mask, prefill_mask = _mask_helpers()
    import numpy as np

    pads = [0, 3]
    key_ok = np.asarray(pad_key_mask(pads, 6))
    assert key_ok.shape == (2, 1, 1, 6)
    assert key_ok[0, 0, 0].all()                       # unpadded row: every key valid
    assert not key_ok[1, 0, 0, :3].any()               # padded row: pads excluded
    assert key_ok[1, 0, 0, 3:].all()

    m = np.asarray(prefill_mask(pad_key_mask(pads, 6), 6))
    assert m.shape == (2, 1, 6, 6)
    assert not m[1, 0, 5, :3].any()                    # last real query ignores pads
    assert m[1, 0, 5, 3:].all()                        # ...and sees every real key


def test_pad_query_rows_are_never_fully_masked():
    """A fully-masked softmax row returns NaN, which would poison the whole batch
    through the next layer's K/V — so a pad query keeps its own (zero) diagonal."""
    pad_key_mask, prefill_mask = _mask_helpers()
    import numpy as np

    m = np.asarray(prefill_mask(pad_key_mask([0, 3], 6), 6))
    assert m.any(axis=-1).all(), "every query row must attend to at least one key"
    assert m[1, 0, 0, 0] and not m[1, 0, 0, 1:].any()   # pad attends to itself only
