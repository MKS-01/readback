"""Offline long-form synthesis: article text → one audio buffer / WAV.

Offline (not real-time), so RTF is irrelevant — we synthesize every chunk fully
and concatenate. That's the whole point of the reader pivot: no underrun.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("readback.pipeline")

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# Cap chars per TTS call.
#
# ⚠ DO NOT narrow this band for "finer expression". It was tried: batching made
# small chunks cheap, so the band was moved to [120, 200] to give
# _expressive_temperature a per-sentence window instead of a per-paragraph one.
# The result was AUDIBLY WORSE — delivery shifted tone every sentence or two
# instead of settling, reported as "audio is not stable, tone keeps changing".
# Reverted to [280, 400], the band that produced the reference-quality reads.
# Chunk size is a DELIVERY setting, not a speed setting — speed comes from
# tts.csm.batch_size (see CsmEngine.synthesize_batch), which does not change how
# the text is divided.
#
# ⚠ Note the interaction with the engine's max_audio_length_ms (20 s): a
# 370-char chunk measured 19.84 s of audio against that cap, i.e. right at the
# edge of being clipped mid-sentence (the same text yields 21.84 s given room).
# 400-char chunks with dense punctuation can reach it. Raise the cap rather than
# shrinking this band.
_MAX_CHARS = 400
# Each chunk's actual cap is drawn fresh from [_MIN_CHUNK_CHARS, _MAX_CHARS]
# instead of always hitting _MAX_CHARS — a fixed cap produces a mechanical,
# same-length-every-time breath cadence; real speech doesn't chunk that
# uniformly. This also gives _expressive_temperature more varied windows: a
# short random cap is more likely to land on a single sentence (its own
# temperature) rather than merging it with a differently-toned neighbor.
_MIN_CHUNK_CHARS = 280
_MIN_CHARS = 8


def _next_chunk_cap() -> int:
    return random.randint(_MIN_CHUNK_CHARS, _MAX_CHARS)


def _hard_split(piece: str) -> list[str]:
    """Last-resort split for a comma-less run longer than _MAX_CHARS: break on
    spaces into ≤_MAX_CHARS runs. An over-cap chunk risks hitting the engine's
    max_audio_length_ms bound and getting cut off mid-sentence in the audio."""
    if len(piece) <= _MAX_CHARS:
        return [piece]
    out: list[str] = []
    cur = ""
    for word in piece.split(" "):
        if cur and len(cur) + 1 + len(word) > _MAX_CHARS:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out


def chunk_text(text: str) -> list[str]:
    """Split article text into TTS-sized chunks: sentence-aware, merged up to a
    per-chunk cap randomized within [_MIN_CHUNK_CHARS, _MAX_CHARS] (never above
    _MAX_CHARS), paragraph boundaries respected (so prosody resets per para)."""
    chunks: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        buf = ""
        cap = _next_chunk_cap()
        for sent in _SENTENCE_RE.split(para):
            sent = sent.strip()
            if not sent:
                continue
            # Hard-split an over-long single sentence on commas as a fallback,
            # then on spaces if a comma-free run still exceeds the cap. Always
            # measured against _MAX_CHARS (not the current random cap) — this
            # is a hard safety split, not the pacing variation.
            pieces = [sent]
            if len(sent) > _MAX_CHARS:
                pieces = [q for p in re.split(r",\s+", sent) if p.strip()
                          for q in _hard_split(p.strip())]
            for piece in pieces:
                if len(buf) + len(piece) + 1 <= cap:
                    buf = (buf + " " + piece).strip()
                elif len(buf) >= _MIN_CHARS:
                    chunks.append(buf)
                    buf = piece
                    cap = _next_chunk_cap()
                elif len(buf) + len(piece) + 1 <= _MAX_CHARS:
                    # A sub-_MIN_CHARS buf ("Wow!") can't stand alone — carry it
                    # into this piece instead of dropping it (a low random cap
                    # made silent mid-paragraph drops reachable otherwise).
                    buf = (buf + " " + piece).strip()
                    cap = _next_chunk_cap()
                else:
                    # Piece is near the hard cap: emit the fragment as its own
                    # tiny chunk rather than drop it or exceed _MAX_CHARS.
                    chunks.append(buf)
                    buf = piece
                    cap = _next_chunk_cap()
        if len(buf) >= _MIN_CHARS:
            chunks.append(buf)
        elif buf and chunks:
            chunks[-1] = (chunks[-1] + " " + buf).strip()
    return chunks


def _tidy_silence(audio: np.ndarray, sr: int, *, thresh_db: float = -40.0,
                  pad_ms: int = 40, max_pause_ms: int = 300) -> np.ndarray:
    """Make pacing natural: strip leading/trailing silence AND cap any internal
    silent run to `max_pause_ms`. CSM (conditioned on the casual, disfluent
    Sesame prompt) sprinkles long mid-utterance pauses — collapsing them is what
    removes the 'broken'/halting feel. Model-agnostic post-processing."""
    if audio.size == 0:
        return audio
    import itertools

    thr = 10.0 ** (thresh_db / 20.0)
    voiced = np.abs(audio) >= thr
    if not voiced.any():
        return np.zeros(0, dtype=np.float32)   # all silence — drop the chunk
    first = int(np.argmax(voiced))
    last = len(voiced) - int(np.argmax(voiced[::-1]))
    pad = int(pad_ms * sr / 1000)
    audio = audio[max(0, first - pad): min(len(audio), last + pad)]
    voiced = voiced[max(0, first - pad): min(len(voiced), last + pad)]

    # Cap every internal silent run to max_pause.
    max_pause = int(max_pause_ms * sr / 1000)
    pieces: list[np.ndarray] = []
    pos = 0
    for is_voiced, grp in itertools.groupby(voiced):
        ln = sum(1 for _ in grp)
        seg = audio[pos: pos + ln]
        if not is_voiced and ln > max_pause:
            seg = seg[:max_pause]
        pieces.append(seg)
        pos += ln
    return np.concatenate(pieces) if pieces else audio


def _peak_normalize(audio: np.ndarray, target: float = 0.95) -> np.ndarray:
    """Scale the whole buffer so its peak hits `target`. CSM matches the energy
    of its reference clip, so clone voices (quiet references) come out ~18 dB
    softer than the near-full-scale built-in prompts; normalizing the final buffer
    levels every voice to the same loudness. CSM output is clean speech with no
    stray transients, so a single peak scale is safe (no limiter needed)."""
    if audio.size == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak <= 0.0:
        return audio
    return (audio * (target / peak)).astype(np.float32)


def _fade_out_tail(audio: np.ndarray, sr: int, fade_ms: int = 100) -> np.ndarray:
    """Light linear fade-out on the last `fade_ms` of audio so the transition
    into the inter-chunk silence gap is smooth (no hard cut → click)."""
    n = min(int(fade_ms * sr / 1000), audio.size)
    if n < 2:
        return audio
    audio = audio.copy()
    audio[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return audio


def _expressive_temperature(chunk: str, base: float) -> float:
    """Nudge the delivery temperature for one chunk based on its punctuation, so
    expression shifts with the content instead of staying flat for the whole
    read. CSM exposes no direct emotion/prosody control — sampling temperature
    (more variation in pitch/pacing at higher values) is the one delivery knob
    it does have, and punctuation is a real signal the model was trained on, so
    small, content-driven nudges here are the practical lever available.
    Clamped to stay within CSM's stable range (below ~0.55 a short clone
    reference can destabilize; above ~0.95 delivery gets erratic)."""
    temp = base
    if "!" in chunk:
        temp += 0.08          # emphatic / lively line
    elif "?" in chunk:
        temp += 0.04          # questioning / curious line
    elif chunk.count(",") >= 3:
        temp -= 0.03          # dense, measured explanatory line
    return max(0.55, min(0.95, temp))


def _batches(order: list[int], size: int) -> list[list[int]]:
    """Split chunk indices into EVENLY-sized groups of at most `size`.

    ⚠ Not a plain stride: 11 chunks at size 8 is split 6+5, not 8+3. A batch's
    cost is dominated by its frame loop, which is nearly flat in batch size, so a
    3-row tail batch costs about as much wall time as a full one — measured, an
    8+3 split gave RTF 0.33 where the same text in one balanced pass gave 0.24.
    Evening out the groups keeps every batch earning its frame loop.
    """
    n = len(order)
    if n == 0:
        return []
    n_groups = -(-n // size)                  # ceil
    base, extra = divmod(n, n_groups)
    out, i = [], 0
    for g in range(n_groups):
        take = base + (1 if g < extra else 0)
        out.append(order[i:i + take])
        i += take
    return out


def _length_buckets(chunks: list[str], size: int) -> list[list[int]]:
    """Group chunk indices into batches of near-equal TEXT LENGTH.

    Two reasons, both about the batched frame loop:
      - prompts are left-padded to the batch's longest, and padding occupies
        causal positions, so we want the pads small;
      - the loop runs until EVERY row hits EOS, so a short row batched with a
        long one just idles. Equal-length rows finish together.
    Returns batches of ORIGINAL indices; the caller reassembles by index, so
    document order is unaffected by this regrouping.
    """
    by_len = sorted(range(len(chunks)), key=lambda i: len(chunks[i]))
    return _batches(by_len, size)


def _synthesize_batched(
    synth,
    chunks: list[str],
    temps: list[Optional[float]],
    sr: int,
    progress: Optional[Callable[[int, int], None]],
    should_stop: Optional[Callable[[], bool]],
) -> Optional[list[np.ndarray]]:
    """Synthesize every chunk via `synth.synthesize_batch`, tidied, in order.

    Returns per-chunk audio (empty array for a chunk that failed), or None if the
    engine has no batch path / it blew up — the caller then falls back to the
    sequential loop, so a csm-mlx change degrades to slow rather than broken.
    """
    batch_fn = getattr(synth, "synthesize_batch", None)
    if batch_fn is None:
        return None
    size = max(1, int(getattr(synth, "batch_size", 1) or 1))
    if size == 1:
        return None

    audio: list[np.ndarray] = [np.zeros(0, dtype=np.float32)] * len(chunks)
    done_count = 0
    retry: list[int] = []
    try:
        for group in _length_buckets(chunks, size):
            if should_stop is not None and should_stop():
                log.info("synth aborted after %d/%d chunks", done_count, len(chunks))
                break
            items = [(chunks[i], temps[i] if temps[i] is not None else 0.0) for i in group]
            for idx, raw in zip(group, batch_fn(items)):
                tidied = _tidy_silence(raw, sr)
                if tidied.size == 0:
                    retry.append(idx)      # all silence — one more go below
                audio[idx] = tidied
                done_count += 1
                if progress is not None:
                    progress(done_count, len(chunks))
        # Degenerate-chunk guard, batched: one retry for chunks that came back
        # as pure silence (same policy as the sequential path).
        if retry and not (should_stop is not None and should_stop()):
            log.info("retrying %d all-silence chunk(s)", len(retry))
            for group in _batches(retry, size):
                items = [(chunks[i], temps[i] if temps[i] is not None else 0.0) for i in group]
                for idx, raw in zip(group, batch_fn(items)):
                    audio[idx] = _tidy_silence(raw, sr)
    except Exception:
        log.exception("batched synthesis failed — falling back to sequential")
        return None
    return audio


def synthesize_article(
    synth,
    text: str,
    *,
    gap_sec: float = 0.18,
    base_temperature: Optional[float] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> np.ndarray:
    """Synthesize `text` chunk-by-chunk into one float32 buffer (engine sample
    rate). Each chunk is silence-trimmed, then joined with a short uniform gap so
    pacing is natural (no stacked CSM trailing-silence). `progress(done, total)`
    fires after each chunk; `should_stop()` aborts early (e.g. client gone).
    `base_temperature`, when given, is the reading tone's delivery temperature —
    each chunk's actual temperature is nudged around it per `_expressive_temperature`
    so delivery varies with content rather than staying uniform for the whole read."""
    sr = synth.sample_rate
    gap = np.zeros(int(gap_sec * sr), dtype=np.float32)
    chunks = chunk_text(text)
    if not chunks:
        return np.zeros(0, dtype=np.float32)

    # Fast path: synthesize the chunks in batches through one CSM frame loop.
    # Each chunk keeps its own _expressive_temperature (per-row sampler), so
    # batching is a pure throughput change, not a delivery change.
    temps: list[Optional[float]] = [
        _expressive_temperature(c, base_temperature) if base_temperature is not None
        else None
        for c in chunks
    ]
    batched = _synthesize_batched(synth, chunks, temps, sr, progress, should_stop)
    if batched is not None:
        out: list[np.ndarray] = []
        for audio in batched:
            if audio.size:
                out.append(_fade_out_tail(audio, sr))
                out.append(gap)
        if not out:
            return np.zeros(0, dtype=np.float32)
        return _peak_normalize(np.concatenate(out))

    # Sequential fallback: no batch path on this engine, batch_size=1, or the
    # batched attempt raised.
    out = []
    for i, chunk in enumerate(chunks):
        if should_stop is not None and should_stop():
            log.info("synth aborted at chunk %d/%d", i + 1, len(chunks))
            break
        if base_temperature is not None:
            synth.set_temperature(_expressive_temperature(chunk, base_temperature))
        try:
            audio = _tidy_silence(synth.synthesize(chunk), sr)
            if audio.size == 0:
                log.info("chunk %d/%d all silence — retrying once", i + 1, len(chunks))
                audio = _tidy_silence(synth.synthesize(chunk), sr)
        except Exception:
            log.exception("synth failed on chunk %d/%d", i + 1, len(chunks))
            audio = np.zeros(0, dtype=np.float32)
        if audio.size:
            out.append(_fade_out_tail(audio, sr))
            out.append(gap)
        if progress is not None:
            progress(i + 1, len(chunks))
    if not out:
        return np.zeros(0, dtype=np.float32)
    return _peak_normalize(np.concatenate(out))


def write_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    import soundfile as sf

    sf.write(path, audio, sample_rate)
