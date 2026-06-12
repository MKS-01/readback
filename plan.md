# Plans

Planning history for readback — newest entry on top, older entries kept below for
tracking. Each entry carries a date and a status (`proposed` / `in progress` /
`done` / `superseded`).

---

## 2026-06-12 — CLI model switch (`/model`) — list local Ollama models + RAM-fit suggestion

**Status: done** — shipped on branch `feat/model-switch` (2026-06-12), version
bumped to **v1.1.0**: `readback/llm/models.py`, `/api/models`, per-read
`model` swap, CLI `/model` command + prefs. Post-review additions: colored fit
verdicts (`ModelList.tsx`; green fits / yellow tight / red too-big, new
GREEN/YELLOW theme colors) and `/model` added to the home-screen hint line.
Verified end-to-end by driving the TUI through a pty (expect): list +
recommendation, switch + StatusLine + prefs persistence across restart,
unknown-name error, per-read swap confirmed server-side (`/api/config` flipped
mid-session). CLI scope only; web UI gets its own plan later.

### Context

Summary mode uses one Ollama model, fixed in `config.yaml` (`gemma4:26b`) at
server boot. Goal: switch the summary LLM from the terminal CLI without a
restart — a `/model` command that **lists all locally downloaded Ollama
models**, **flags which fit this Mac's RAM** (avoid swap/thrash later), and
**suggests the ideal one for summarization**, then switches to it. Mirrors the
existing `/voice` flow end-to-end.

A small server change is unavoidable (the LLM lives in the Python server), but
it's tiny: `LLMClient.oneshot()` reads `self.cfg.model` fresh on every call
(`llm/client.py`), so swapping = mutating `cfg.ollama.model` — no reload. The
bundled `ollama` lib already has `Client.list()` (`/api/tags`) for discovery.

### Design

1. **`GET /api/models`** (new, `web/server.py`, next to `/api/config`) — logic
   in a new **`readback/llm/models.py`** (reusable by the web client later):
   - `ollama.Client(host).list()` → per model: name, `size` bytes,
     `details.parameter_size`, `details.quantization_level`.
   - Total RAM via `sysctl -n hw.memsize` (fallback `os.sysconf`).
   - **Fit heuristic**: need ≈ `size × 1.2 + 1 GiB` (weights + KV/overhead);
     `good` if ≤ 50 % of total RAM, `tight` if ≤ 75 %, else `no` (reserve
     headroom for CSM + system).
   - **Recommendation**: largest `good` non-embedding model (skip names with
     `embed`/`bge`/`minilm`). Ollama down → `{"error": …, "models": []}`.
   - Shape: `{models: [{name, size_gb, params, quant, fit}], recommended,
     current, total_ram_gb}`.
2. **Per-read `model` field** on the `read` WS message — same semantics as
   `voice` (`_run_read_job`, applied *before* the summarize step): if set and
   different, validate against the installed list, then
   `cfg.ollama.model = model`; unknown name → `log.warning`, keep current.
   Global mutation like `swap_voice`; **no `config.yaml` write-back** (restart
   returns to the yaml default). Update the WS protocol docstring.
3. **CLI `/model`** (same UX as `/voice`):
   - `/model` → fetch `/api/models`, render in the notice pane: ★ current,
     → recommended, per row `size GB · params · fit` text; hint
     `/model <name> to switch · used by Summary mode only`. Cache the list in
     a ref for arg validation.
   - `/model <name>` → validate against the list, `setModel`, persist, notice.

### Files

- `readback/llm/models.py` (new): `list_models`, `installed_model_names`.
- `readback/web/server.py`: `/api/models` route; model swap in `_run_read_job`;
  protocol docstring.
- `cli/src/ws.ts`: `read(url, mode, voice, model)`.
- `cli/src/prefs.ts`: `model: string | null`.
- `cli/src/app.tsx`: `model` state (init `prefs.model ?? cfg.model`) +
  `setModel` action; `/model` command; pass `state.model` to `StatusLine` and
  `read()`; persist; HELP text.
- `cli/src/components/StatusLine.tsx`: no change (prop already exists).

### Out of scope

Web frontend UI; `config.yaml` write-back; `ollama pull` (installed-only).

### Verification

1. `cd cli && bun run start` → `/model` lists installed models with sizes, fit
   tags, ★ on `gemma4:26b`, → on the recommendation.
2. `/model <other-model>` → notice + StatusLine update; persisted in
   `~/.readback/cli.json`; survives a CLI restart.
3. Summary-mode read → server log `summary model → …`; `ollama ps` shows the
   chosen model during the summarizing phase.
4. `/model not-a-model` → error banner; current model unchanged.
5. Ollama stopped → `/model` shows a clean error banner, no crash.
6. `curl http://127.0.0.1:8000/api/models | jq` matches the documented shape.

---

## 2026-06-11 — CLI mode — Bun + Ink terminal client

**Status: in progress** — implemented on branch `cli-mode`; docs + version bump
(0.9.0) landed; manual verification underway.

**2026-06-12 additions** (same branch, post-review with user): half-block
wordmark banner (`Header.tsx`, READ white / BACK Xcode-blue `#4da3ff`, chosen
over icon-art variants); blue accents (caret, version, progress fills,
slash-command hints); **seek ←/→ ±5 s** via WAV PCM slicing to a temp file
(afplay can't seek); **word-synced transcript highlight** (char-proportional
timing estimate; self-wrapped lines because ink `wrap="wrap"` breaks colored
spans); resize repaint via `prependListener` clear (alt-screen tried, glitchy
in Warp, reverted); `install.sh` one-command standalone binary →
`~/.local/bin/readback-cli` (repo root baked via `--define`). Docs updated
(cli/README, root README CLI section, CLAUDE.md) with screenshot placeholders
at `media/cli-{home,busy,player}.png` — paths pending from user.

### Context

A terminal client for readers who live in the shell — a **second client of the
existing FastAPI `/ws` protocol, zero Python changes**. Ink UI (React for
CLIs), themed to the web app's Ghost palette (#f0f0f0 primary, #808080 dim,
#ff5d5d errors/cancel only). Runtime: **Bun + TypeScript**.

### Decisions

- **Auto-spawn the server.** On start, health-check `GET /api/config`; if down,
  spawn `readback` (prefers `.venv/bin/readback`, cwd = repo root so
  `config.yaml` resolves), wait ≤60 s; on exit kill it only if we spawned it —
  SIGTERM then SIGKILL after 1.5 s (uvicorn's graceful shutdown can hang on the
  open websocket). `--no-spawn` opts out; `--host`/`--port` target a remote.
- **`afplay` player** (macOS-only): SIGSTOP/SIGCONT pause/resume (always
  SIGCONT before SIGTERM), no seeking, wall-clock elapsed; keys: space, t
  (transcript, Summary mode), q/esc. Local WAV from `~/.readback/reader/` when
  present, else download from `/audio`.
- **Interactive-only session**: bordered URL input + slash commands (`/voice`,
  `/mode`, `/help`, `/quit`); prefs persist to `~/.readback/cli.json`; esc
  cancels a running read. No one-shot/batch flags.
- **Ink screen model**: `useReducer` switches one mounted screen
  (input | busy | player) so keys only land on the active screen; `ws.ts` /
  `player.ts` are module singletons outside the React tree (web frontend
  pattern).

### Files

`cli/`: `package.json` (readback-cli 0.9.0), `tsconfig.json`, `README.md`,
`src/{index.tsx, app.tsx, theme.ts, server.ts, ws.ts, player.ts, prefs.ts,
components/{UrlInput,StatusLine,BusyView,PlayerView}.tsx}`. Docs: README /
CLAUDE / ARCHITECTURE / cli/README; version → 0.9.0 in the three Python-side
anchors + cli/package.json.

### Verification

`bun run start` with no server → auto-spawn + read + afplay playback; q exits
and the spawned server dies. With a server already running → connects, doesn't
kill it on exit. Cancel mid-synthesis (esc), Summary transcript toggle, prefs
survive a restart, `--no-spawn` fails fast when no server. Known caveats:
CLI SIGKILL orphans a spawned server; pause flushes ~0.5 s of buffer.

---

## 2026-06-10 — Tune CSM-1B by config (simple path; no model swap)

**Status: done (Step 1; Steps 2–3 deferred)** — applied 2026-06-10:
`precision: fp32`; kay ref upgraded to an 11 s CSM-bootstrapped clip
(`voice/voice_kay_long.wav`, transcript whisper-verified); summary LLM switched
to `gemma4:26b` (cleaner, structured spoken summaries; nemotron-3-nano was the
fallback). End-to-end sample verified: steady pacing, no instability; only
residual nit is occasional proper-noun articulation ("Fable" ≈ "Table"), which
is LoRA territory. **Step 2 (LoRA) deferred** — revisit only if articulation
bothers in real use; anything more now is overengineering.

### Context

Stay on CSM-1B (user decision — an engine swap was judged too expensive, and
earlier engine experiments had already been abandoned). csm-mlx runs the
**same weights** as the official release, and every lever that matters is
**already plumbed into `config.yaml`** — so the plan is staged: config-only
first, LoRA fine-tune only if that's not enough. **No app-code changes
anywhere.**

Why this works: the open 1B is a *base* model; the polished demo voices are
fine-tuned variants conditioned on good reference audio. Better reference +
right precision/temperature is the first half of that recipe; the LoRA is the
second.

### Step 1 — Config-only tuning (~1 hour, no code)

1. **Better reference clip — the biggest lever.** Current kay ref is one short
   ~4–5 s clip; a clean **8–10 s** clip conditions far more reliably (per
   `.claude/skills/csm-voice`). More kay-source audio if available, else any
   clean recording of a voice you like:
   `scripts/make_clone_voice.sh <in> voice/kay2.wav` → exact transcript via
   one-off mlx-whisper (install → transcribe → uninstall, the skill's pattern)
   → update `wav:` + `ref_text:` under `tts.csm.voices`.
2. **`precision: "fp32"`** — max quality; RTF ~1.4 is fine for an offline reader.
3. **Temperature**: render the same paragraph at 0.6 and 0.7, keep the one that
   sounds better (0.6 measured, 0.7 livelier). Two runs, not a grid.
4. Restart the server, read one real article end-to-end, judge by ear.

### Step 2 — LoRA fine-tune (only if Step 1 isn't enough; the real jump)

Follow `finetune/README.md` **verbatim** — commands already M5/48 GB-tuned:
1. Data: one **LibriVox narrator** (clean public-domain read-speech), 30–60 min
   of chapters → split to 5–15 s clips (ffmpeg) → `finetune/data/` layout.
2. `finetune/transcribe.py` (one-off mlx-whisper) → review transcripts.
3. `csm-mlx finetune convert finetune/data finetune/dataset.json`
4. `csm-mlx finetune lora sft --data-path finetune/dataset.json
   --output-dir finetune/runs/v1 --lora-rank 8 --lora-alpha 16 --epochs 10
   --batch-size 1 --gradient-accumulation-steps 8 --gradient-ckpt
   --learning-rate 5e-4`
5. Result is again just config: `lora_path: "finetune/runs/v1"` +
   `temperature: 0.8`. Quick-check synth (README one-liner), then the server.

### Step 3 — Optional, later (on request only)

YouTube voice extraction for a specific person's voice (yt-dlp + diarization +
review pass). Skipped for now — LibriVox covers the quality goal without the
extra deps and script.

### Deliberately cut for simplicity

Multi-clip conditioning (code change), WER bench script, chunk-size and sampler
experiments, mlx upgrade. Revisit only if Step 2 still disappoints.

### Files touched

- Step 1: `config.yaml`, `voice/*.wav` — nothing else.
- Step 2: `finetune/data/*` + `finetune/runs/v1` + two `config.yaml` lines.

### Verification

- Same test paragraph synthesized before/after each change; pick by ear.
  (Optional: one one-off mlx-whisper transcription to count word errors.)
- Server smoke after each config edit (restart required): paste an article URL
  → Full mode → play + download work; cancel still works (no code touched).

### Honest expectations

Step 1 tightens voice consistency and clarity; Step 2 (LoRA on fluent
narration) is what removes the conversational/halting character and gives the
composed "narrator" delivery — the same move Sesame made for its demo voices. A
tuned 1B won't fully equal their hosted demo (a larger fine-tuned variant), but
it's the best this hardware does without the 8B-class cost already ruled out.

---

## 2026-06-10 — TTS engine upgrade + accuracy bench (researched, dropped)

**Status: superseded (same day)** — explored swapping the TTS engine for a
larger model behind a new adapter, with a WER/RTF bench to pick the default.
Direction changed the same day to staying on CSM-1B and tuning it (see the
entry above): an engine swap was judged too expensive for the gain, and the
sample analysis showed the remaining gap was model-level naturalness — pacing
was already fixed by `_tidy_silence` (zero pauses ≥ 0.35 s in the outputs).
The detailed research notes (candidate models, bench harness design, adapter
sketch) were removed from this file once the decision landed.
