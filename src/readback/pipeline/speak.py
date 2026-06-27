"""Offline long-form synthesis: article text → one audio buffer / WAV.

Offline (not real-time), so RTF is irrelevant — we synthesize every chunk fully
and concatenate. That's the whole point of the reader pivot: no underrun.
"""
from __future__ import annotations

import logging
import re
from typing import Callable, Optional

import numpy as np

log = logging.getLogger("readback.pipeline")

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
# Cap chars per TTS call — fewer, larger chunks = fewer CSM reference-prefills =
# faster total synthesis. 400 stays well under CSM's 2048-token budget (the
# _max_ms_for safety bound caps runaway generation per chunk).
#
# Speed vs prosody tradeoff:
#   400 — fast (fewer prefills, ~30% fewer chunks than 280)
#   280 — balanced (more natural sentence-boundary breaks)
#   200 — max prosody (shortest chunks, best intonation, slowest)
_MAX_CHARS = 400
_MIN_CHARS = 8


def chunk_text(text: str) -> list[str]:
    """Split article text into TTS-sized chunks: sentence-aware, merged up to
    ~_MAX_CHARS, paragraph boundaries respected (so prosody resets per para)."""
    chunks: list[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        buf = ""
        for sent in _SENTENCE_RE.split(para):
            sent = sent.strip()
            if not sent:
                continue
            # Hard-split an over-long single sentence on commas as a fallback.
            pieces = [sent]
            if len(sent) > _MAX_CHARS:
                pieces = [p.strip() for p in re.split(r",\s+", sent) if p.strip()]
            for piece in pieces:
                if len(buf) + len(piece) + 1 <= _MAX_CHARS:
                    buf = (buf + " " + piece).strip()
                else:
                    if len(buf) >= _MIN_CHARS:
                        chunks.append(buf)
                    buf = piece
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


def synthesize_article(
    synth,
    text: str,
    *,
    gap_sec: float = 0.18,
    progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> np.ndarray:
    """Synthesize `text` chunk-by-chunk into one float32 buffer (engine sample
    rate). Each chunk is silence-trimmed, then joined with a short uniform gap so
    pacing is natural (no stacked CSM trailing-silence). `progress(done, total)`
    fires after each chunk; `should_stop()` aborts early (e.g. client gone)."""
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
