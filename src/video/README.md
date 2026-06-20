# readback — explainer video (Remotion)

A short (15 s) programmatic explainer for the README: **how readback works** —
hero wordmark → animated pipeline → terminal mock → live waveform of the real
sample read → outro. Authored in React/[Remotion](https://www.remotion.dev/) so
it stays on-brand with the Ghost design tokens (`src/design-system/`) and is
editable in code, not a binary.

Not part of the shipped package — this is a build tool for `docs/media/`.

## Setup

```bash
cd src/video
bun install
cp ../../docs/media/sample-read.wav public/sample-read.wav   # waveform + audio source
```

## Preview (Remotion Studio)

```bash
bun run studio          # opens http://localhost:3000 — scrub, tweak, hot-reload
```

## Render

```bash
bun run render          # → docs/media/how-it-works.mp4 (H.264, with sound)
bun run gif             # → docs/media/how-it-works.gif (inline README preview, no sound)
```

First render downloads a headless Chrome shell (~150 MB, one-time).

## Structure

| File | What |
|---|---|
| `src/Root.tsx` | the `<Composition>` (1280×720, 30 fps, 450 frames) |
| `src/Explainer.tsx` | the timeline + all five scenes |
| `src/theme.ts` | Ghost palette + brand fonts (IBM Plex Mono / Martian Mono via `@remotion/google-fonts`) |

Edit scene timing in the `<Sequence>` list at the bottom of `Explainer.tsx`.

## README embedding

GitHub renders an inline autoplaying preview for a **GIF**; for an MP4 *player*
upload `how-it-works.mp4` via the GitHub web UI (drag into an issue/release) and
paste the resulting `user-attachments` URL. The repo references the GIF.
