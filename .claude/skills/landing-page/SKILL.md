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

`src/landing-page/index.html`, in order. Touch only what's relevant:

| Section | Update when… |
|---|---|
| `<head>` `og:` meta + `<title>`/description | the one-line pitch changed, or a better `og:image` exists (`media/<x>.png`) |
| **hero** (tagline, pitch, CTA) | the core value prop changed |
| **sample player** (`#player`) | the sample WAV changed (`media/sample-read.wav`) |
| **screenshots** (`#shots` crossfade) | a new screenshot is worth showing — see §3 |
| **Features** grid (`.feat-grid`, 4 cells) | a headline capability was added/removed |
| **How it works** (`.flow`) | the pipeline or client set changed (e.g. a second client) |
| **Quick start** (`pre.code`) | install/run steps changed |
| **The story** / **Architecture** (`.stack-list`) | the narrative or a core design fact changed |
| **footer** | links changed |

Keep the voice: terminal-first, lowercase headings prefixed `##`, Ghost palette,
concise. Match the surrounding markup exactly — this page has no framework.

## 3. Screenshots — pull from `docs/media/`

`docs/media/` is the **canonical** image source (the README uses it too). The
page references images as `media/<file>` (served flat by the Pages workflow).

- Pick the most representative shots already in `docs/media/` (e.g.
  `dashboard.png`, `cli-player.png`, `cli-home.png`, `cli-model.png`). Don't
  invent files — if a shot doesn't exist, capture one into `docs/media/` first.
- The crossfade (`#shots`) is **slide count–sensitive**: each `<img class="slide">`
  needs a matching `.dot` button *and* a `data-caption`. Add/remove all three
  together or the dots desync (the JS maps `slides[i]` ↔ `dots[i]`).
- ⚠ **Add every newly-referenced `media/<file>` to the Pages workflow's copy
  list** in `.github/workflows/pages.yml` — the page only renders an image on the
  live site if the workflow copied it into `_site/media/`. Missing = broken image.
- Update `og:image` if a better hero shot landed.

## 4. Keep the aesthetic + gotchas

- **Ghost palette** is the single source of truth in `src/landing-page/style.css`
  `:root` (mirrors the CLI `theme.ts`). Don't hardcode hexes inline.
- **Flow chart is HTML/CSS boxes, not ASCII** — box-drawing glyphs shatter in the
  IBM Plex Mono webfont (fallback widths differ). Build flow nodes as `.node`
  divs (see the existing `.flow`).
- **`prefers-reduced-motion`** is respected — any new animation must no-op under it.
- Inline JS patterns already there: waveform player, screenshot crossfade, scroll
  reveal (`IntersectionObserver`). Reuse them; don't add libraries or a build.

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

Deployment is automatic: `.github/workflows/pages.yml` publishes
`src/landing-page/` to `mks-01.github.io/readback` on **push to `main`** when the
push touches `src/landing-page/**`, `docs/media/**`, or the workflow itself.
Nothing to run by hand — just merge to main and watch the Action go green
(`gh run watch`). Verify the live URL returns 200 and the new images load.

## 7. Done check

- Every `media/<file>` referenced in `index.html` is in the pages.yml copy list.
- Slides ↔ dots ↔ captions counts all match.
- No stale claims (old version, removed feature, dead screenshot) — grep the page
  for the thing you changed.
- Local screenshot looks right; then push to `main` and confirm the deploy.
