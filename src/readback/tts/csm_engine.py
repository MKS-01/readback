"""CSM-1B via csm-mlx (senstella/csm-mlx).

Dedicated MLX implementation of Sesame's Conversational Speech Model — same
author as parakeet-mlx. Replaces the mlx-audio "sesame" path in v0.7.x for
cleaner output. Output is float32 @ 24 kHz (Mimi-native), matching the WS
contract with no resample.

The two UI voices map to CSM speaker IDs: conversational_a → 0, conversational_b
→ 1. Each sentence is conditioned on the built-in Sesame prompt clip for the
active voice (cached `Segment`, see `_ref_for`) — CSM needs this reference to
sound good AND stay consistent; empty-context generation drifts to a different
voice each sentence and degrades quality. csm-mlx is efficient enough that the
~10 s prompt prefill still runs at RTF ~0.8 on M5 (no underrun).

MLX binds its GPU stream to the first thread that touches the device, so ALL
model work (load + synth) runs on a single owned executor thread; public methods
submit and block. `_impl` methods run ON that thread and must never re-submit.
"""
import concurrent.futures
from typing import Callable, TypeVar

import numpy as np

from readback.config import CsmTTSConfig

# (id, label) pairs for the UI picker → CSM speaker id. IDs kept stable for prefs
# back-compat, but they point at Sesame's READ-SPEECH prompts (fluent literary
# reading) — the casual "conversational_*" clips made CSM read in a halting,
# chatty tone that sounded unnatural for an article reader.
SUPPORTED_VOICES: tuple[tuple[str, str], ...] = (
    ("conversational_a", "Reading voice A ★"),
    ("conversational_b", "Reading voice B"),
)
_VOICE_SPEAKER: dict[str, int] = {"conversational_a": 0, "conversational_b": 1}


def voices_for(cfg: CsmTTSConfig) -> tuple[tuple[str, str], ...]:
    """Full (id, label) voice list: built-in reading voices + custom clone-condition
    clips from `cfg.voices`. Used by both the engine and the server's voice picker."""
    return SUPPORTED_VOICES + tuple((v.name, v.label) for v in cfg.voices)

_SAMPLE_RATE = 24000  # CSM/Mimi native rate — matches the WS Float32 contract.
_HF_REPO = "senstella/csm-1b-mlx"
_HF_FILE = "ckpt.safetensors"

# CSM needs a voice reference to sound good AND stay consistent — empty-context
# generation picks a fresh voice every sentence. These are Sesame's READ-SPEECH
# prompt clips (sesame/csm-1b), with their EXACT transcripts (transcribed once
# via Parakeet). Fluent literary reading → CSM reads in a natural, even tone. We
# cache a Segment per voice and pass it as context to every sentence.
_HF_PROMPT_REPO = "sesame/csm-1b"
_PROMPTS: dict[str, tuple[str, str]] = {
    "conversational_a": (
        "prompts/read_speech_a.wav",
        "and Lake turned round upon me, a little abruptly, with his odd yellowish "
        "eyes, a little like those of the sea eagle, and the ghost of his smile "
        "that flickered on his singularly pale face with a stern and insidious "
        "look, confronted me.",
    ),
    "conversational_b": (
        "prompts/read_speech_b.wav",
        "He was such a big boy that he wore high boots and carried a jackknife. He "
        "gazed and gazed at the cap, and could not keep from fingering the blue "
        "tassel.",
    ),
}

# precision name → mlx dtype attr (fp32 = leave as loaded).
_PRECISION_DTYPES = {"fp16": "float16", "bf16": "bfloat16"}

_T = TypeVar("_T")


def _max_ms_for(text: str, cap_ms: int) -> int:
    """Bound runaway generation if EOS never fires (keeps frames under CSM's 2048
    token budget). ~120 ms/char + floor, capped at cfg.max_audio_length_ms."""
    return min(cap_ms, max(3000, len(text) * 120))


def frame_bounds(items: list[tuple[str, float]], cap_ms: int) -> list[int]:
    """Per-row frame budget for a batch — one bound per (text, temperature) row.

    ⚠ Must stay PER ROW. `_max_ms_for` scales the runaway-generation bound with
    each chunk's own length; collapsing it to a single batch-wide max lets a
    SHORT row that never emits EOS keep generating on the LONGEST row's budget,
    which tails off into babble at the end of the audio.
    """
    return [int(_max_ms_for(text, cap_ms) / 80) for text, _ in items]


def _pad_key_mask(pads: list[int], total: int):
    """Key-validity mask for a LEFT-PADDED batch: (B, 1, 1, total), True = attend.

    ⚠ Load-bearing for audio quality. The batched path left-pads every prompt to
    the batch's longest, and `generate_frame`'s `token_mask` only zeroes the pad
    EMBEDDINGS — it does not stop real tokens from ATTENDING to those positions.
    A zero embedding stays exactly zero through every layer (RMSNorm(0) = 0, and
    the MLP/attention are bias-free), so each pad contributes a key of 0, scoring
    q·0 = 0 — i.e. weight exp(0) = 1 in every softmax denominator, against a
    value vector of 0. The pads therefore act as a bank of neutral sinks that
    DILUTE attention and flatten the output distribution. Measured on a 236-frame
    prompt (top-1 codebook-0 probability, unpadded → padded):

        1 pad  0.193 → 0.165     8 pads  0.193 → 0.049 (KL 0.72, argmax flips)
        4 pads 0.193 → 0.093    32 pads  0.193 → 0.023 (KL 1.49)

    A flatter distribution means the sampler draws noisier acoustic tokens, which
    is heard as a soft, MUFFLED, less articulate voice — the exact symptom that
    parked this branch. Masking the pads out restores the unpadded distribution
    (KL ~0), so batching becomes a pure throughput change.
    """
    import mlx.core as mx

    keys = mx.arange(total)[None, :]                    # (1, total)
    ok = keys >= mx.array(pads, dtype=mx.int32)[:, None]
    return ok.reshape(len(pads), 1, 1, total)


def _prefill_mask(key_ok, length: int):
    """Causal + padding mask for the prefill step: (B, 1, L, L), True = attend.

    ⚠ The diagonal is force-enabled. A pad QUERY has no valid key at or before
    it, and a fully-masked softmax row comes back NaN, which would poison the
    whole batch through the next layer's K/V. Letting a pad attend to itself
    yields 0 (its own zero value vector) and keeps it inert.
    """
    import mlx.core as mx

    q = mx.arange(length)[:, None]
    k = mx.arange(length)[None, :]
    causal = q >= k
    return (causal & key_ok[..., :length]) | (q == k)


def _to_numpy(audio) -> np.ndarray:
    """Coerce an mlx/np audio array to 1-D float32."""
    if audio is None:
        return np.zeros(0, dtype=np.float32)
    return np.asarray(audio, dtype=np.float32).reshape(-1)


class CsmEngine:
    name = "csm"

    def __init__(self, cfg: CsmTTSConfig):
        self.cfg = cfg
        self._model = None
        # Cached reference Segment per voice (built once on the executor thread).
        self._ref_cache: dict = {}
        # Cached TOKENIZED reference per voice, for the batched path. csm-mlx's
        # generate() re-runs tokenize_segment (a Mimi encode of the ~12 s clip,
        # ~0.03 s) on every call; the batch path owns the tokenization, so it
        # pays that once per voice instead of once per chunk.
        self._ref_token_cache: dict = {}
        self._sampler_cache: dict = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="csm-tts",
        )

    def _run(self, fn: Callable[..., _T], *args) -> _T:
        return self._executor.submit(fn, *args).result()

    # ---- public surface (called from any thread) ----

    @property
    def sample_rate(self) -> int:
        return _SAMPLE_RATE

    @property
    def current_voice(self) -> str:
        return self.cfg.speaker

    def load(self):
        self._run(self._load_impl)

    def swap_voice(self, voice: str) -> str:
        """Switch the active voice. Instant — one loaded model; speaker id + the
        reference clip are per-call args (no reload). Custom voices build their
        reference Segment lazily on first use (cached thereafter)."""
        valid = {v for v, _ in voices_for(self.cfg)}
        if voice not in valid:
            raise ValueError(
                f"Unsupported voice {voice!r}; pick from {sorted(valid)}"
            )
        self.cfg.speaker = voice
        return voice

    def set_temperature(self, temp: float) -> None:
        """Set the sampling temperature for subsequent synth calls. `_make_sampler`
        reads `self.cfg.temperature` fresh per call, so this takes effect on the
        next `synthesize` with no reload."""
        self.cfg.temperature = float(temp)

    def synthesize(self, text: str) -> np.ndarray:
        text = text.strip()
        if not text:
            return np.zeros(0, dtype=np.float32)
        return self._run(self._synthesize_impl, text)

    def synthesize_batch(self, items: list[tuple[str, float]]) -> list[np.ndarray]:
        """Synthesize several chunks in ONE frame loop. Returns audio in input order.

        ⚠ This is the main throughput lever. CSM emits one frame per 80 ms of
        audio, and each frame is 1 backbone step + 31 sequential decoder steps on
        a 1B model — ~400 tiny sequential matmuls per second of audio, which
        leaves the GPU mostly idle waiting on launch latency. Measured on M5 Pro
        (steady-state decode, ms per frame → audio produced per wall-second):

            batch 1 — 51.6 ms →  1.55 s     batch 4 — 82.1 ms →  3.90 s
            batch 2 — 80.5 ms →  1.99 s     batch 8 — 84.8 ms →  7.55 s

        i.e. 8x the work for 1.64x the time. `items` is [(text, temperature)] —
        each row keeps its OWN sampling temperature (the reading tone's
        `_expressive_temperature` for that chunk), so batching does not flatten
        delivery. Rows generate until their own EOS; the loop runs until every
        row is done, so batch rows of SIMILAR LENGTH (the caller buckets) or
        short rows idle while a long one finishes.
        """
        items = [(t.strip(), temp) for t, temp in items]
        if not items:
            return []
        return self._run(self._synthesize_batch_impl, items)

    # ---- impls (run ON the MLX executor thread; never re-submit) ----

    def _config_voice(self, voice: str):
        """The CsmVoicePrompt for `voice`, or None if it's a built-in reading voice."""
        for v in self.cfg.voices:
            if v.name == voice:
                return v
        return None

    def _speaker_id(self) -> int:
        cv = self._config_voice(self.cfg.speaker)
        if cv is not None:
            return cv.speaker
        return _VOICE_SPEAKER.get(self.cfg.speaker, 0)

    def _make_sampler(self):
        key = (self.cfg.temperature, self.cfg.top_k)
        cached = self._sampler_cache.get(key)
        if cached is not None:
            return cached
        from mlx_lm.sample_utils import make_sampler

        sampler = make_sampler(temp=self.cfg.temperature, top_k=self.cfg.top_k)
        self._sampler_cache[key] = sampler
        return sampler

    def _make_batch_sampler(self, temps):
        """Sampler with a PER-ROW temperature (shape (B, 1)).

        `_make_sampler` closes over one scalar temp, which would flatten every
        chunk in a batch to the same delivery. This mirrors mlx_lm's sampler
        chain exactly — `apply_top_k` then `categorical_sampling(logits, temp)`
        (= `mx.random.categorical(logits * (1 / temp))`) — both of which act on
        the last axis, so a (B, 1) temperature broadcasts across the batch.
        """
        import mlx.core as mx
        from mlx_lm.sample_utils import apply_top_k

        top_k = self.cfg.top_k

        def sampler(logprobs):
            if top_k and 0 < top_k < logprobs.shape[-1]:
                logprobs = apply_top_k(logprobs, top_k)
            return mx.random.categorical(logprobs * (1.0 / temps))

        return sampler

    def _ref_tokens_for(self, voice: str):
        """Tokenized reference prompt for `voice` — (tokens, mask) or (None, None).

        Cached per voice: the batch path builds prompts itself, so the Mimi
        encode of the reference clip happens once instead of once per chunk.
        """
        if voice in self._ref_token_cache:
            return self._ref_token_cache[voice]
        from csm_mlx.tokenizers import tokenize_segment

        ref = self._ref_for(voice)
        if not ref:
            self._ref_token_cache[voice] = (None, None)
            return None, None
        tok, mask = tokenize_segment(
            ref[0], n_audio_codebooks=self._model.n_audio_codebooks,
        )
        self._ref_token_cache[voice] = (tok, mask)
        return tok, mask

    def _ref_for(self, voice: str) -> list:
        """Cached reference-prompt context for `voice` (built once on the executor
        thread). Returns [Segment] to pass to generate(), or [] if no prompt is
        configured. `cfg.ref_max_sec` (None/0 = full) trims the clip AND its
        transcript together — a mismatched (text, audio) pair garbles the voice."""
        cached = self._ref_cache.get(voice)
        if cached is not None:
            return cached
        # Fine-tuned (LoRA) model: the voice is baked into the adapter, so we
        # follow the FINETUNING preset and generate with EMPTY context — a
        # read-speech reference prompt would fight the trained voice.
        if self.cfg.lora_path is not None:
            self._ref_cache[voice] = []
            return []
        import mlx.core as mx
        from csm_mlx import Segment
        from csm_mlx.utils import read_audio

        # Custom clone-condition voice (local clip) vs built-in reading prompt (HF).
        cv = self._config_voice(voice)
        if cv is not None:
            wav = str(cv.wav)
            text = cv.ref_text
            speaker = cv.speaker
        else:
            prompt = _PROMPTS.get(voice)
            if prompt is None:
                self._ref_cache[voice] = []
                return []
            from huggingface_hub import hf_hub_download

            filename, text = prompt
            speaker = _VOICE_SPEAKER.get(voice, 0)
            wav = hf_hub_download(repo_id=_HF_PROMPT_REPO, filename=filename)
        audio = read_audio(wav, _SAMPLE_RATE)            # (samples,) mx.array @ 24k
        ref_sec = self.cfg.ref_max_sec or 0.0
        if ref_sec:
            cap = int(ref_sec * _SAMPLE_RATE)
            full_sec = audio.shape[0] / _SAMPLE_RATE
            if full_sec > ref_sec:
                audio = audio[:cap]
                words = text.split()
                keep = max(4, int(len(words) * ref_sec / max(1.0, full_sec)))
                text = " ".join(words[:keep])
        mx.eval(audio)
        seg = [Segment(speaker=speaker, text=text, audio=audio)]
        self._ref_cache[voice] = seg
        return seg

    def _load_impl(self):
        if self._model is not None:
            return
        from csm_mlx import CSM, csm_1b
        from huggingface_hub import hf_hub_download

        self._model = CSM(csm_1b())
        self._model.load_weights(hf_hub_download(repo_id=_HF_REPO, filename=_HF_FILE))
        # Precision: bf16 by default — ~halves F32 compute, native on Apple Silicon
        # (no per-op dequant), and keeps the voice clean. "fp32" stays full
        # precision (slow); "fp16" a touch faster, narrower range.
        dtype_name = _PRECISION_DTYPES.get((self.cfg.precision or "bf16").lower())
        if dtype_name is not None:
            try:
                import mlx.core as mx

                self._model.set_dtype(getattr(mx, dtype_name))
                mx.eval(self._model.parameters())
            except Exception:
                pass   # fall back to loaded precision rather than failing load
        # Optional LoRA adapter from a csm-mlx finetune run (FINETUNING preset).
        # Loaded over the base weights; generation then uses empty context.
        if self.cfg.lora_path is not None:
            from csm_mlx import load_adapters

            load_adapters(self._model, str(self.cfg.lora_path))
        # Warm the graph (one throwaway synth) AND build the reference cache so
        # the first real sentence is fast and on-voice.
        try:
            import mlx.core as mx
            from csm_mlx import generate

            mx.eval(generate(
                self._model, text="Hello.", speaker=self._speaker_id(),
                context=self._ref_for(self.cfg.speaker), max_audio_length_ms=2000,
                sampler=self._make_sampler(),
            ))
        except Exception:
            pass

    def _synthesize_impl(self, text: str) -> np.ndarray:
        import mlx.core as mx
        from csm_mlx import generate

        if self._model is None:
            self._load_impl()
        audio = generate(
            self._model,
            text=text,
            speaker=self._speaker_id(),
            context=self._ref_for(self.cfg.speaker),
            max_audio_length_ms=_max_ms_for(text, self.cfg.max_audio_length_ms),
            sampler=self._make_sampler(),
        )
        mx.eval(audio)
        return _to_numpy(audio)

    def _frame_impl(self, model, tokens, token_mask, sampler, cache, mask, stream):
        """Masked twin of `csm_mlx.generation.generate_frame`.

        Identical maths, with ONE addition: the backbone is driven layer by layer
        so we can hand it an attention `mask` that excludes the batch's left-pad
        frames (see `_pad_key_mask`). `LlamaModel.__call__` builds its own causal
        mask and takes no mask argument, which is why the loop is inlined here.
        The decoder needs no mask — its per-frame inputs are 1-2 positions long
        and never padded.
        """
        import mlx.core as mx
        from mlx_lm.models.cache import make_prompt_cache

        embeds = model.embed_tokens(tokens) * mx.expand_dims(token_mask, axis=-1)
        with mx.stream(stream):
            h = embeds.sum(-2)
            for layer, layer_cache in zip(model.backbone.layers, cache):
                h = layer(h, mask, cache=layer_cache)
            last = model.backbone.norm(h)[:, -1, :]

            c0_logits = model.codebook0_head(last)
            c0_logprobs = c0_logits - mx.logsumexp(c0_logits, axis=-1, keepdims=True)
            c0_sample = mx.expand_dims(sampler(c0_logprobs), axis=-1)

            decoder_inputs = mx.concat(
                [mx.expand_dims(last, axis=1), model.embed_audio(0, c0_sample)], axis=1,
            )
            out = mx.zeros((tokens.shape[0], model.n_audio_codebooks), dtype=tokens.dtype)
            out[:, :1] = c0_sample

            decoder_cache = make_prompt_cache(model.decoder)
            for index in range(1, model.n_audio_codebooks):
                hidden = model.decoder(model.projection(decoder_inputs), cache=decoder_cache)
                ci_logits = mx.matmul(hidden[:, -1, :], model.audio_head[index - 1])
                ci_logprobs = ci_logits - mx.logsumexp(ci_logits, axis=-1, keepdims=True)
                ci_sample = mx.expand_dims(sampler(ci_logprobs), axis=-1)
                decoder_inputs = model.embed_audio(index, ci_sample)
                out[:, index:index + 1] = ci_sample
        return out

    def _synthesize_batch_impl(self, items: list[tuple[str, float]]) -> list[np.ndarray]:
        """Batched twin of csm-mlx's `generate`, run on the executor thread.

        ⚠ Mirrors `csm_mlx.generation.generate` (frame loop → `decode_audio`) but
        over a batch dimension, with a padding-aware attention mask (see
        `_pad_key_mask` — without it the pads flatten the output distribution and
        the voice comes out muffled). It therefore depends on csm-mlx internals
        (`generate_frame`'s maths, `tokenize_*`, `decode_audio`) and on mlx-lm's
        Llama layer signature; the caller falls back to the sequential path if
        this raises, so an upstream change degrades to slow rather than broken.
        """
        import mlx.core as mx
        from csm_mlx.generation import default_stream
        from csm_mlx.tokenizers import decode_audio, tokenize_text_segment
        from mlx_lm.models.cache import make_prompt_cache

        if self._model is None:
            self._load_impl()
        model = self._model
        speaker = self._speaker_id()
        ref_tok, ref_mask = self._ref_tokens_for(self.cfg.speaker)

        # Build one prompt per row: [reference] ++ [text].
        prompts, masks = [], []
        for text, _ in items:
            tok, msk = tokenize_text_segment(text, speaker)
            if ref_tok is not None:
                tok = mx.concat([ref_tok, tok], axis=0)
                msk = mx.concat([ref_mask, msk], axis=0)
            prompts.append(tok.astype(mx.int32))
            masks.append(msk.astype(mx.bool_))

        # LEFT-pad to the batch's longest prompt so every row's NEXT position is
        # the same, which is what lets one frame loop serve the whole batch. The
        # pads are then masked OUT of attention (`_pad_key_mask`); the caller
        # still buckets by length, which now only saves work, not quality.
        width = prompts[0].shape[1]            # codebooks + the text column
        L = max(p.shape[0] for p in prompts)
        pads = [L - p.shape[0] for p in prompts]
        padded, padded_masks = [], []
        for tok, msk in zip(prompts, masks):
            pad = L - tok.shape[0]
            if pad:
                tok = mx.concat([mx.zeros((pad, width), dtype=mx.int32), tok], axis=0)
                msk = mx.concat([mx.zeros((pad, width), dtype=mx.bool_), msk], axis=0)
            padded.append(tok)
            padded_masks.append(msk)
        inp = mx.stack(padded, axis=0)
        inp_mask = mx.stack(padded_masks, axis=0)

        B = len(items)
        temps = mx.array([[max(1e-4, float(t))] for _, t in items])
        sampler = self._make_batch_sampler(temps)
        # ⚠ PER-ROW generation bound. `_max_ms_for` scales the runaway-generation
        # cap with the chunk's own length, and that bound must stay per row: with
        # a single batch-wide max, a SHORT row that fails to emit EOS keeps
        # generating on the LONGEST row's budget and tails off into babble —
        # heard as "the ending is broken", and visible as a batch rendering 13 s
        # longer than the same text synthesized sequentially.
        row_max = frame_bounds(items, self.cfg.max_audio_length_ms)
        max_frames = max(row_max)

        # One key-validity mask covering prompt + every frame we could generate;
        # each step slices the prefix it needs (cheap, lazy). Skipped entirely
        # when nothing is padded, so a same-length batch runs the original path.
        key_ok = _pad_key_mask(pads, L + max_frames) if any(pads) else None
        mask = _prefill_mask(key_ok, L) if key_ok is not None else "causal"

        model.eval()                            # csm-mlx's generate() does this
        cache = make_prompt_cache(model.backbone)
        frames: list[list] = [[] for _ in range(B)]
        done = [False] * B
        for step in range(max_frames):
            sample = self._frame_impl(
                model, inp, inp_mask, sampler, cache, mask, default_stream,
            )
            mx.eval(sample)
            zeros = np.asarray(mx.sum(mx.abs(sample), axis=1)) == 0   # per-row EOS
            for b in range(B):
                if done[b]:
                    continue
                if zeros[b] or len(frames[b]) >= row_max[b]:
                    done[b] = True          # own EOS, or own length bound
                else:
                    frames[b].append(sample[b:b + 1])
            if all(done):
                break
            inp = mx.expand_dims(
                mx.concat([sample, mx.zeros((B, 1))], axis=1), 1,
            ).astype(mx.int32)
            inp_mask = mx.expand_dims(
                mx.concat([mx.ones_like(sample), mx.zeros((B, 1))], axis=1), 1,
            ).astype(mx.bool_)
            # Single-token step: the query is the newest position, so causality is
            # implicit and only the pad columns need masking.
            if key_ok is not None:
                mask = key_ok[..., :L + step + 1]

        model.train()
        out: list[np.ndarray] = []
        for b in range(B):
            if not frames[b]:
                out.append(np.zeros(0, dtype=np.float32))
                continue
            audio = decode_audio(
                mx.stack(frames[b]).transpose(1, 2, 0),
                n_audio_codebooks=model.n_audio_codebooks,
            ).squeeze(0).squeeze(0)
            mx.eval(audio)
            out.append(_to_numpy(audio))
        return out
