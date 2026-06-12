# readback CLI

A terminal client for readback — Bun + TypeScript + [Ink](https://github.com/vadimdemedes/ink).
It is the sole client of the readback server's `/ws` protocol: paste a URL, watch the
phases, and the finished WAV plays right in your terminal via `afplay`.
macOS only. *Built with [Claude Code](https://claude.com/claude-code).*

<p align="center">
  <img src="../../docs/media/cli-home.png" alt="readback CLI — home screen" width="820">
</p>

The look: a two-tone block wordmark (`READ` white / `BACK` blue), a
dark Ghost palette plus an Xcode-blue accent, and three screens — URL input,
progress, player — switched in place.

## Prerequisites

- [Bun](https://bun.sh/) 1.x
- The readback Python package installed (see the [root README](../../README.md)) —
  the CLI talks to (or spawns) the `readback` server.

## Install (one command)

```bash
cd src/cli && ./install.sh     # or: bun run setup
```

Builds a standalone binary (Bun runtime included) and installs it to
`~/.local/bin/readback-cli` (override with `READBACK_BIN_DIR=...`). Then run
`readback-cli` from anywhere. The repo path is baked in at build time so the
binary can still auto-spawn the server with the right `config.yaml`.
**Re-run `./install.sh` after pulling new changes.**

> The binary is `readback-cli`; plain `readback` is the Python *server*
> entrypoint (inside the repo venv). Want it shorter? `alias rb="readback-cli"`.

## Run from source (dev)

```bash
cd src/cli
bun install
bun run start          # or: bun run src/index.tsx
```

On start it health-checks `GET /api/config`. If no server is running it
auto-spawns `readback` (prefers `.venv/bin/readback`, cwd = repo root so
`config.yaml` resolves), waits up to 60 s, and kills the server on exit —
but only if it spawned it.

### Flags

| Flag | Default | What |
|---|---|---|
| `--host` | `127.0.0.1` | Server host |
| `--port` | `8000` | Server port |
| `--no-spawn` | off | Never auto-spawn a server; fail if none is reachable |

## Usage

Paste an article URL and hit enter. The progress screen streams the server's
phases (fetching → summarizing → synthesizing) with a per-chunk progress bar;
esc cancels a running read.

### Slash commands

| Command | What |
|---|---|
| `/voice [id]` | Show / set the voice (persisted) |
| `/model [name]` | List local Ollama models / set the summary LLM (persisted) |
| `/mode [full\|summary]` | Show / set the read mode (persisted) |
| `/help` | List commands |
| `/quit` | Exit |

`/model` shows every model installed in Ollama with its size and a RAM-fit
verdict for this Mac (green fits · yellow tight · red too big), recommends the
best fit for summaries, and marks the active one with ★. The model is used by
Summary mode only and switches on the next read — no server restart.

<p align="center">
  <img src="../../docs/media/cli-model.png" alt="readback CLI — /model list with RAM-fit verdicts" width="820">
</p>

Prefs (voice/mode/model) persist to `~/.readback/cli.json`.

### Player

<p align="center">
  <img src="../../docs/media/cli-player.png" alt="readback CLI — player with live transcript" width="820">
</p>

| Key | What |
|---|---|
| `space` | Pause / resume (replays when finished) |
| `←` / `→` | Seek back / forward 5 s |
| `t` | Toggle transcript (Summary mode only) |
| `q` / `esc` | Back to the URL input |

- **Live transcript** (Summary mode): the spoken summary highlights in blue
  word by word as the voice reads it. Timing is estimated — the server returns
  no word timestamps, so each word gets a slice of the total duration
  proportional to its length — but it tracks the voice closely.
- **Seeking** works even though `afplay` has no transport control: the CLI
  slices the local WAV's PCM data at the target offset into a temp file and
  relaunches `afplay` there. Rapid presses are debounced into one jump.
- Pausing flushes ~0.5 s of buffered audio (`afplay` SIGSTOP quirk).

## Caveats

- **SIGKILL can orphan a spawned server.** Normal exits (q, ctrl-c) shut the
  spawned `readback` down (SIGTERM, then SIGKILL after 1.5 s), but if the CLI
  itself is SIGKILLed the server keeps running — kill it manually
  (`pkill -f readback`).
- Playback is `afplay`, so macOS only.
- Transcript word-sync is an estimate (see above), not timestamp-accurate.
