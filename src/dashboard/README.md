# readback dashboard

A small **Vue 3 + Vite + TypeScript** web library for readback. Lists every
synthesized read (recorded in the SQLite library at `cfg.reader.library_db`),
with search, newest/oldest sort, inline replay, "read original", and delete.

It's a pure REST + static client — no WebSocket, no Python changes. Same design
system as the CLI and landing page (Ghost palette + IBM Plex Mono / Martian
Mono).

Playing a read expands its card into a full player — seekable bar (click to
seek), `elapsed / total`, ±5 s skips, pause/resume/replay, and **space / ←→**
keyboard shortcuts (mirroring the CLI). A playing **Summary** read shows its
summary as a **synced karaoke transcript** (words highlight in accent blue in
time with the audio), using the same char-count-proportional timing as the CLI
player.

## Develop

```bash
bun install
bun run dev        # Vite on http://localhost:5173, proxies /api + /audio → :8000
```

You need the `readback` server running on `:8000` for data (`readback` from the
repo root). Generate a read with the CLI and it appears here.

## Build

```bash
bun run build      # type-check + emit ./dist
```

When `src/dashboard/dist` exists, the `readback` server mounts it at `/`, so the
dashboard is served by the same process that makes the audio:

```bash
readback           # then open http://127.0.0.1:8000/
```

## How it talks to the server

| Route | Purpose |
|---|---|
| `GET /api/library?q=&sort=newest\|oldest` | list cards (search + sort) |
| `GET /api/library/{id}` | full record |
| `DELETE /api/library/{id}` | remove the row + its WAV |
| `GET /audio/{filename}` | the WAV (HTML5 `<audio>` playback) |

## Deploy (later)

The Pi (`github.com/MKS-01/pizow`) can serve `dist/` via nginx and proxy `/api`
+ `/audio` to the Mac, which stays the LLM + TTS + audio host. Out of scope for
now — the local setup serves everything from the one FastAPI process.
