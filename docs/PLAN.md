# Plans

Planning history for readback — newest entry on top, older entries kept below for
tracking. Each entry carries a date and a status (`proposed` / `in progress` /
`done` / `superseded`).

---

## 2026-06-13 — Landing page on GitHub Pages

**Status: done** — branch `landing-page`, PR #11 merged 2026-06-13. Static
one-page site + the repo's first GitHub Action; zero changes to `src/`.
Shipped: `site/index.html` + `style.css` (Ghost-palette terminal page with an
inline sample-read player), `.github/workflows/pages.yml` (copies media from
`docs/media/` into the artifact), Pages enabled with the Actions source.
Verified: workflow run green, `https://mks-01.github.io/readback/` live —
page + css + all media return 200, headless-Chrome render matches local, no
viewport overflow.
Follow-ups (same day): ASCII flow chart rebuilt as HTML/CSS boxes (box-drawing
glyphs aren't in the IBM Plex Mono webfont — fallback glyph widths shattered
it); footer "PRs welcome" line dropped; `site/blog/` added (3 high-level
notes: why / how-it-works / voices) with a Notes section on the landing page;
motion pass (scroll-reveal sections, animated flow connectors, breathing
feature markers, `prefers-reduced-motion` respected); workflow now copies all
of `site/` into the artifact.

### Context

readback is open source but has no web presence beyond the GitHub README. A
minimalist landing page gives the project a linkable home — and since the
product *makes audio*, the page can do what the README can't: play the sample
read inline. Constraint: the v2.0.0 pivot deliberately removed the web
frontend, so the site must live outside `src/` as pure static marketing, not a
client. Hosting: GitHub Pages (free), deployed by GitHub Actions per the
user's ask.

### Design

1. **`site/` at the repo root** — standalone static site: `index.html` +
   `style.css`, hand-written, no framework, no build step. Never imports or
   serves anything from `src/`.
2. **Look: the product's own aesthetic.** Dark terminal page using the CLI's
   Ghost palette — `#f0f0f0` primary / `#808080` dim / `#4da3ff` accent
   (`theme.ts` is the source of truth) — monospace type, the wordmark PNG as
   the hero. The page should read like the CLI screenshots beside it.
3. **Sections** (single scroll, in order): hero (wordmark, tagline "Make
   reading interesting again", one-line pitch, `git clone` CTA + GitHub
   button) → inline **audio player** with `sample-read.wav` → screenshot
   (`cli-player.png`) → features grid (100% offline / CSM-1B voice + cloning /
   Summary mode via local LLM / real terminal player with seek + synced
   transcript) → how-it-works pipeline (the README's ASCII diagram in a
   `<pre>`) → quick start (the README's 4-step code block) → open-source
   footer (MIT, GitHub, issues, "Built on Apple Silicon · MLX").
4. **Media is not duplicated in git.** `site/` holds only html/css; the deploy
   workflow copies `docs/media/{wordmark.png, cli-player.png, cli-home.png,
   sample-read.wav}` into the artifact's `media/` before upload. The page
   references `media/…` relatively.
5. **Workflow `.github/workflows/pages.yml`** — on push to `main` (paths:
   `site/**`, `docs/media/**`, the workflow itself) + `workflow_dispatch`:
   checkout → assemble `_site` (site/ + media copy) →
   `actions/upload-pages-artifact` → `actions/deploy-pages`. Standard
   `pages: write` / `id-token: write` permissions, `github-pages` environment.
6. **Pages source = GitHub Actions** — one-time repo setting via
   `gh api repos/MKS-01/readback/pages -X POST -f build_type=workflow`.
   Site URL: `https://mks-01.github.io/readback/`.

### Files

- `site/index.html` (new): the one-page site.
- `site/style.css` (new): Ghost-palette styling.
- `.github/workflows/pages.yml` (new): assemble + deploy to Pages.
- `docs/PLAN.md` (modified): this entry.
- `README.md` (modified): link the live site under the badge row.

### Out of scope

- No JS framework, no build tooling, no analytics, no custom domain.
- No docs site / multi-page — README and `docs/` stay the documentation home.
- No re-introduction of any web client; the page is static marketing only.
- No CI beyond the Pages deploy (tests/lint workflows are a separate decision).

### Verification

1. `open site/index.html` locally (with media copied in) — renders correctly,
   audio plays, links resolve.
2. Merge to `main` → the `pages.yml` run goes green end-to-end.
3. `https://mks-01.github.io/readback/` loads: wordmark crisp, sample WAV
   plays inline, screenshots load, GitHub links work.
4. Lighthouse-level sanity: page is responsive at phone width; no console
   errors; total weight dominated only by the media files.

## 2026-06-12 — Folder restructure: src/ layout + docs/

**Status: done** — branch `depreciate/web` (continues PR #10, same post-web
cleanup umbrella). Top-level reorganization only; zero code-logic changes.
Shipped: everything python-side under `src/` (`readback/`, `cli/`, `voice/`,
`finetune/`), all docs caps-named under `docs/` (`ARCHITECTURE.md`, `SETUP.md`,
`PLAN.md` + `media/`). Riding along: `docs/SETUP.md` and `docs/ARCHITECTURE.md`
rewritten for the CLI-only era (both still described the deleted web
frontend/TLS). Verified: editable install + imports, server 200/404, CLI
dev-mode auto-spawn from the new depth, `install.sh` binary bakes the correct
repo root, stale-path sweep clean.

### Context

After the web deletion and package rename, the repo root holds 7 markdown/config
files plus 6 directories — the Python package sits at top level next to the CLI,
and docs are scattered. Goal: a conventional layout where the Python backend
lives under `src/` (standard src-layout), the CLI stays a clear sibling at
`cli/`, and reference docs collect under `docs/` — leaving the root with just
the entry-point files (`README.md`, `CLAUDE.md`, `config.yaml`,
`pyproject.toml`, `plan.md`, `LICENSE`).

Research confirmed the moves are cheap: the package has no `__file__` path
tricks, `config.yaml` resolves from cwd (the CLI spawns the server with
cwd = repo root), and only two spots derive the repo root relative to `cli/`
(`install.sh`, `server.ts`) — each needs one extra `..` when `cli/` moves
under `src/`.

### Design

1. **`src/` layout — both clients**: `git mv readback/ src/readback/` and
   `git mv cli/ src/cli/`. Update `pyproject.toml`:
   `packages = ["src/readback"]`. No Python import changes — the package name
   is unchanged. Requires one `pip install -e .` re-run.
2. **Root-derivation fixes** (the only code-path edits):
   - `src/cli/install.sh`: `REPO_ROOT="$(cd .. && pwd)"` → `cd ../..`.
   - `src/cli/src/server.ts`: dev fallback `resolve(import.meta.dir, "..", "..")`
     → `"..", "..", ".."`.
3. **`docs/`** — all caps-named: `docs/ARCHITECTURE.md`, `docs/SETUP.md`,
   `docs/PLAN.md` (renamed from `plan.md`), `docs/media/`. Fix links in
   `README.md` (SETUP, ARCHITECTURE, 4 media images + sample WAV),
   `src/cli/README.md` (media images, `../media/` → `../../docs/media/`), and
   `CLAUDE.md` (ARCHITECTURE link + project-structure map).
4. **`voice/` → `src/voice/`, `finetune/` → `src/finetune/`** — python-side
   assets grouped under `src/` (as siblings of the package, NOT inside
   `src/readback/`, so they don't ship in the wheel). Path updates:
   `config.yaml` (`wav:` + `lora_path` comment), `.gitignore` (wav exceptions +
   finetune ignores), `src/finetune/README.md` self-referencing commands,
   `csm-voice` skill paths.
5. **Stays at root**: `README.md` (GitHub landing + pyproject `readme`),
   `CLAUDE.md` (user request), `config.yaml` (cwd-resolved at runtime),
   `LICENSE`.
5. **Stale-doc fixes riding along**: `SETUP.md` drops the Node.js/React
   frontend prerequisite + build step (web is gone); the `doc-sync` skill's
   `readback/web/server.py` reference becomes `src/readback/server/server.py`;
   `cd cli` install instructions become `cd src/cli` everywhere.
6. **CLAUDE.md project-structure block** rewritten to the new tree.

### Files

- `readback/` → `src/readback/` (git mv, no content changes).
- `cli/` → `src/cli/` (git mv).
- `src/cli/install.sh` (modified): repo-root derivation one level deeper.
- `src/cli/src/server.ts` (modified): dev repo-root fallback one level deeper.
- `ARCHITECTURE.md` → `docs/ARCHITECTURE.md`; `SETUP.md` → `docs/SETUP.md`
  (+ stale frontend refs removed); `plan.md` → `docs/PLAN.md`;
  `media/` → `docs/media/`.
- `voice/` → `src/voice/`; `finetune/` → `src/finetune/` (+ path updates in
  `config.yaml`, `.gitignore`, `src/finetune/README.md`, `csm-voice` skill).
- `pyproject.toml` (modified): wheel packages path.
- `README.md` (modified): doc + media links, `cd src/cli`.
- `src/cli/README.md` (modified): media links.
- `CLAUDE.md` (modified): structure map, ARCHITECTURE link, install notes.
- `.claude/skills/doc-sync/SKILL.md` (modified): doc paths.

### Out of scope

- Moving `config.yaml` (stays at root, cwd-resolved).
- Any logic changes — only the two root-derivation constants change in code.
- Rewriting SETUP.md beyond deleting the dead frontend steps.

### Verification

1. `pip install -e .` succeeds with the src layout; `readback` entry point works.
2. `python -c "from readback.server.server import create_app; print('ok')"`.
3. `readback` boots; `GET /api/config` → 200; `GET /` → 404.
4. `cd src/cli && bun run start` — auto-spawn + full read flow works
   (cwd-relative `config.yaml` still resolves from the derived repo root).
5. `cd src/cli && ./install.sh` — compiled binary bakes the right repo root,
   finds the venv server.
6. All README/cli README image + doc links resolve; no stale `cd cli` /
   `media/` / root `ARCHITECTURE.md` references remain.

---

## 2026-06-12 — Restructure Python package: pipeline/ + server/

**Status: done** — branch `depreciate/web` (runs after web deletion is done).
Rename `reader/` → `pipeline/` and `web/` → `server/` for accurate, durable naming.
Zero behavior change; import fixes only.

> **Why now:** With the browser UI gone, `web/` is a misnomer (it's a WS/REST server,
> not a web app) and `reader/` was always the old feature label, not a description
> of what the code does. Clean names before the project settles as CLI-only.

### Context

Two folder names became stale after the v0.8.0 pivot and the web deletion:
`reader/` was named after the "article reader" feature, not its role (processing
pipeline: extract → summarize → synthesize). `web/` implied a browser-facing layer
that no longer exists. Renaming both while the diff is small is lower risk than
accumulating a larger rename later. `llm/` and `tts/` are already well-named.

### Design

1. Rename `readback/reader/` → `readback/pipeline/`. Update the `__init__.py`
   self-references and `summarize.py`'s import of `extract`.
2. Rename `readback/web/` → `readback/server/`. `server.py` moves with it;
   update its three `readback.reader.*` import lines to `readback.pipeline.*`.
3. Update `__main__.py`: `readback.web.server` → `readback.server.server`.
4. Update `CLAUDE.md` module map and any `reader/` path references.

### Files

- `readback/reader/` → `readback/pipeline/` (renamed directory, 3 files + `__init__.py`).
- `readback/web/` → `readback/server/` (renamed directory, `server.py` + `__init__.py`).
- `readback/__main__.py` (modified): one import line.
- `readback/pipeline/__init__.py` (modified): self-import path.
- `readback/pipeline/summarize.py` (modified): one import line.
- `readback/server/server.py` (modified): three import lines (`readback.reader.*` → `readback.pipeline.*`).
- `CLAUDE.md` (modified): module map paths.

### Out of scope

- Any logic changes in any file.
- Renaming `llm/` or `tts/` — both names are accurate.
- CLI changes — the CLI has no Python imports.

### Verification

1. `python -c "from readback.pipeline import fetch_article; print('ok')"` — no ImportError.
2. `python -c "from readback.server.server import create_app; print('ok')"` — no ImportError.
3. `readback` starts cleanly; `GET /api/config` responds.
4. `bun run start` in `cli/` — full read flow works end-to-end.
5. No `readback.reader` or `readback.web` references remain (`grep -r "readback\.reader\|readback\.web" readback/`).

---

## 2026-06-12 — Delete web frontend; CLI-only project

**Status: done** — branch `depreciate/web`.
Remove the React/Vite browser UI and all its scaffolding; slim the server to a
pure CLI-backend (WS + `/audio` + `/api/*`). No protocol changes, no CLI changes.

> **Why we're discontinuing the web UI:** The browser client was the original
> interface, but the terminal CLI (v1.0.0) has fully replaced it as the daily
> driver. The React/Vite/three.js/zustand stack now only adds maintenance debt —
> a mandatory `npm run build` before every server start, TLS/cert machinery for
> LAN browser access, and a large `node_modules` tree to keep up to date. No new
> web features are planned and the CLI covers the full pipeline. Removing the
> frontend simplifies install to a single `pip install -e .` and eliminates the
> web maintenance surface entirely.

### Context

The browser UI (React 18 + Vite + three.js + zustand) was the original primary
client. The terminal CLI (v1.0.0) has since become the sole focus. The frontend
brings: npm/node_modules maintenance, a mandatory build step before server start,
TLS/cert machinery for LAN browser access, and the entire `web/frontend/` tree.
None of that serves the CLI. Deleting it simplifies install and removes the web
maintenance surface entirely.

The CLI still needs the Python server (FastAPI WS) — that is NOT removed.

### Design

1. Delete `readback/web/frontend/` and `readback/web/static/` entirely.
2. In `server.py`: remove `GET /` (index.html), `GET /cert.pem`, the
   `_no_cache_static` middleware, and the `StaticFiles` frontend mount.
   Keep `/ws`, `GET /api/config`, `GET /api/models`, and `/audio` (WAV serving).
3. In `__main__.py`: remove `--auto-cert`, `--cert`, `--key` flags and all TLS/cert
   generation logic (`_ensure_cert`, `_fingerprint`, cert banner output).
   Keep `--host`, `--port`, `--model`, `--config`.
4. In `pyproject.toml`: remove `cryptography` dep.
5. In README + CLAUDE.md: remove frontend build step from install instructions;
   update description to CLI-only.

### Files

- `readback/web/frontend/` (deleted): entire React/Vite app.
- `readback/web/static/` (deleted): Vite build output.
- `readback/web/server.py` (modified): remove HTML-serving routes + middleware.
- `readback/__main__.py` (modified): remove TLS/cert logic and flags.
- `pyproject.toml` (modified): remove `cryptography` dep.
- `README.md` (modified): remove `npm run build` step, update intro.
- `CLAUDE.md` (modified): remove frontend build from install section.

### Out of scope

- Any CLI changes (zero protocol impact).
- Removing `fastapi`, `uvicorn`, `python-multipart` — the WS server stays.
- Removing the `/audio` static mount — CLI player downloads WAVs from it.
- Any new CLI features.

### Verification

1. `pip install -e .` succeeds (no `cryptography` dep error).
2. `readback` starts without `--auto-cert` and prints local URL with no cert/fingerprint output.
3. `readback --auto-cert` prints an unknown-flag error (flag is gone).
4. `GET http://127.0.0.1:8000/` returns 404 (no index.html served).
5. `bun run start` in `cli/` — spawns server, paste a URL, audio plays. Full flow works.
6. `/model`, `/voice`, `/mode` all function normally in the CLI.

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
