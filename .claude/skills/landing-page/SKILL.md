---
name: landing-page
description: Refresh the readback landing page (src/landing-page) to reflect new features, screenshots, or a version bump. Use when a shipped change alters what the product does or how it looks — a new client/mode/feature, a new screenshot worth showing, or after a release — or when the user says "update the landing page", "refresh the site", or "sync the landing page". Collects what changed, maps it to the page's sections, pulls screenshots from docs/media, reviews locally, and lets the Pages workflow deploy.
---

# Landing-page sync — keep the marketing site current

This is **doc-sync for the marketing site**. Run it after a feature or release
lands and the landing page no longer tells the truth. The landing page is pure
static marketing (`src/landing-page/index.html` + `style.css`, vanilla inline JS,
**no build step**) — it is NOT a web client, never import from `src/`.

## 1. Establish what changed

```bash
git diff main... --stat                 # what shipped
grep '^version' pyproject.toml          # current version (the page shows it nowhere yet — see §2)
```

Read the diff (or recall the work). The page's job is to answer "what does this
do and why is it nice" — only update sections the change actually affects.

## 2. Map changes → page sections

⚠ **The page is hook-and-redirect** (trimmed 2026-06-14): hero · **Hear it** ·
**See it work** · **Features** · **Dive in** · footer. Deep detail — install
steps, the pipeline, the architecture, the build story — lives in the **repo**,
not on the page. Do **not** re-add the cut sections (How it works / Quick start /
Architecture / the story timeline); if such a thing changed, update the
README/`docs/` and let the **Dive in** band link to it.

`src/landing-page/index.html`, in order. Touch only what's relevant:

| Section | Update when… |
|---|---|
| `<head>` `og:` meta + `<title>`/description | the one-line pitch changed, or a better `og:image` exists (`media/<x>.png`) |
| **hero** (kicker, tagline, pitch, CTA) | the core value prop changed (copy is mined from `docs/JOURNEY.md` — see CLAUDE/memory, not generic) |
| **sample player** (`#player`) | the sample WAV changed (`media/sample-read.wav`) |
| **screenshot stepper** (`#shots`) | a new screenshot is worth showing — see §3 |
| **Features** (`.feat-term` — a `readback --features` terminal listing) | a headline capability was added/removed |
| **Dive in** (`.dive` — GitHub redirect links) | a deep-detail destination moved (README / `docs/ARCHITECTURE.md` anchors) |
| **footer** | links changed |

Keep the voice: terminal-first, Ghost palette, concise. Section headers are
**plain titles** (no `##` prefix — it read as broken markdown), separated by a
hairline rule under each `h2`. Corners are softened via `--radius` (8px). Match
the surrounding markup exactly — this page has no framework.

## 3. Screenshots — pull from `docs/media/`

`docs/media/` is the **canonical** image source (the README uses it too). The
page references images as `media/<file>` (served flat by the Pages workflow).

- Pick the most representative shots already in `docs/media/` (e.g.
  `dashboard.png`, `cli-player.png`, `cli-home.png`, `cli-model.png`). Don't
  invent files — if a shot doesn't exist, capture one into `docs/media/` first.
- The stepper (`#shots`) is **slide count–sensitive**: each `<img class="demo-slide">`
  needs a matching `.demo-step` tab (underline tabs) *and* a `data-cap` caption.
  Add/remove all three together or they desync (the JS maps `slides[i]` ↔
  `steps[i]` ↔ caption). The `#demo-progress` bar is rAF-driven over `STEP_MS`
  (auto-advance) — no per-slide config; it freezes on hover.
- ⚠ **Add every newly-referenced `media/<file>` to `.github/workflows/pages.yml`
  in TWO places**: (1) the `paths:` trigger (so a change to it actually fires a
  deploy) and (2) the `cp` copy list (so it lands in `_site/media/`). Miss the
  copy list → broken image; miss `paths` → the page won't redeploy when it changes.
- Update `og:image` if a better hero shot landed.

## 4. Keep the aesthetic + gotchas

- **Ghost palette** is the single source of truth in `src/landing-page/style.css`
  `:root` (mirrors the CLI `theme.ts`). Don't hardcode hexes inline. `--radius`
  (8px) softens corners; `--ease-out` / `--ease-drawer` are the motion curves
  (no spring/bounce in functional UI).
- **De-boxed by design** — structure with whitespace + a hairline rule under each
  header, not full borders. Only the screenshot frame (`.demo-frame`) and the
  features panel (`.feat-term`) stay framed. Don't reintroduce a box per section.
- **Features is a terminal listing** (`.feat-term` / `.feat-list`: ✓ + key +
  hang-indented detail), not a card grid — match that markup when editing it.
- **`prefers-reduced-motion`** is respected — *gentle, not zero*: keep opacity
  fades, drop movement (no slide/sway/drift). Any new animation must follow suit.
- Inline JS patterns already there: waveform player, screenshot **stepper** (rAF
  auto-advance + progress bar + caption fade), scroll reveal
  (`IntersectionObserver`). Reuse them; don't add libraries or a build.

## 5. Review locally (always, before pushing)

`media/` is gitignored, so ensure the referenced images exist locally first:

```bash
cp docs/media/*.png docs/media/*.wav src/landing-page/media/ 2>/dev/null
python3 -m http.server -d src/landing-page 8099 &      # serve it
```

Then eyeball it — open `http://localhost:8099/`, or headless-screenshot to
confirm render + no broken images + no viewport overflow:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --disable-gpu --window-size=900,3000 --screenshot=/tmp/landing.png \
  --virtual-time-budget=4000 http://localhost:8099/
```

View `/tmp/landing.png`. Kill the server when done. **Don't push an unreviewed
page** — it's the public front door.

## 6. Deploy (GitHub Pages)

Deployment is automatic but **gated by a rule** (`.github/workflows/pages.yml`):
it publishes `src/landing-page/` to `mks-01.github.io/readback` **only on push to
`main`** (i.e. after a PR merges — never from a feature branch) **and only when
the page itself or one of its exact media files changed** (the narrow `paths:`
list). Unrelated pushes — including `docs/media/` files the page doesn't ship —
don't redeploy. The deploy job is also `if: github.ref == 'refs/heads/main'`, so a
manual `workflow_dispatch` still only publishes from main.

So: **merge to main**, then watch the Action go green (`gh run watch`). Verify the
live URL returns 200 and the new images load. (On a feature branch / PR, nothing
deploys — that's intended.)

## 7. Done check

- Every `media/<file>` referenced in `index.html` is in the pages.yml copy list.
- Slides ↔ steps ↔ captions counts all match.
- No stale claims (old version, removed feature, dead screenshot) — grep the page
  for the thing you changed.
- Local screenshot looks right; then push to `main` and confirm the deploy.
