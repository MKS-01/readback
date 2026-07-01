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
# Cap chars per TTS call — fewer, larger chunks = fewer CSM reference-prefills =
# faster total synthesis, but coarser prosody AND coarser expressive-temperature
# granularity (_expressive_temperature nudges the WHOLE chunk from whichever
# punctuation rule matches first, so a big chunk can bury a measured sentence
# inside a livelier neighbor's chunk). 400 stays well under CSM's 2048-token
# budget either way (the _max_ms_for safety bound caps runaway generation per
# chunk).
#
# Speed vs prosody tradeoff:
#   400 — fast (fewer prefills, ~30% fewer chunks than 280)
#   280 — balanced (more natural sentence-boundary breaks)
#   200 — max prosody + finest expressive-temperature granularity, slowest
_MAX_CHARS = 200
# Each chunk's actual cap is drawn fresh from [_MIN_CHUNK_CHARS, _MAX_CHARS]
# instead of always hitting _MAX_CHARS — a fixed cap produces a mechanical,
# same-length-every-time breath cadence; real speech doesn't chunk that
# uniformly. This also gives _expressive_temperature more varied windows: a
# short random cap is more likely to land on a single sentence (its own
# temperature) rather than merging it with a differently-toned neighbor.
_MIN_CHUNK_CHARS = 120
_MIN_CHARS = 8


def _next_chunk_cap() -> int:
    return random.randint(_MIN_CHUNK_CHARS, _MAX_CHARS)


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
            # Hard-split an over-long single sentence on commas as a fallback.
            # Always measured against _MAX_CHARS (not the current random cap) —
            # this is a hard safety split, not the pacing variation.
            pieces = [sent]
            if len(sent) > _MAX_CHARS:
                pieces = [p.strip() for p in re.split(r",\s+", sent) if p.strip()]
            for piece in pieces:
                if len(buf) + len(piece) + 1 <= cap:
                    buf = (buf + " " + piece).strip()
                else:
                    if len(buf) >= _MIN_CHARS:
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
    out: list[np.ndarray] = []
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
