---
name: ghost-design-system
description: "readback's Ghost design system: color tokens, typography, layout, motion, and component patterns shared across all three surfaces (CLI, dashboard, landing page). Use when adding or modifying any visual element — ensures consistency across platforms."
---

# Ghost Design System

readback's visual identity across all three surfaces. The name comes from the
palette — near-white on near-black, with a single blue accent. Everything is
monospace. Everything is dark. The same tokens, the same feel.

**Use this skill** when adding or changing any visual element. It is the
single source of truth for what the correct color, font, spacing, or motion
value is. **Use `emil-design-eng`** for the _philosophy_ behind animation
and interaction decisions — this skill gives you the _concrete values_.

---

## Surfaces

| Surface | Stack | Source of truth |
|---|---|---|
| **CLI** | Bun + Ink (React for terminals) | `src/cli/src/theme.ts` |
| **Dashboard** | Vue 3 + Vite | `src/dashboard/src/styles.css` |
| **Landing page** | Vanilla HTML/CSS/JS | `src/landing-page/style.css` |

The CLI's `theme.ts` is the origin — the web surfaces mirror its hex values
into CSS custom properties. When a token changes, update all three.

---

## Color tokens

### Core palette

| Token | Hex | Usage |
|---|---|---|
| `--bg` | `#0a0a0a` | Page/terminal background |
| `--panel` | `#121212` | Elevated surfaces (cards, inputs, feature boxes) |
| `--line` | `#232323` | Borders, dividers, hairline rules, track rails |
| `--text` / `FG` | `#f0f0f0` | Primary text, wordmark "READ" |
| `--dim` / `DIM` | `#808080` | Secondary text, hints, metadata, timestamps |
| `--accent` / `BLUE` | `#4da3ff` | Wordmark "BACK", caret, progress fills, links, active states, transcript highlight |
| `--accent-hi` | `#6cb4ff` | Landing page only — brighter accent for hover/glow |
| `--green` / `GREEN` | `#5dd17a` | Success, checkmarks, model-fit "good" verdict |
| `--yellow` / `YELLOW` | `#e6c35a` | Warning, model-fit "tight" verdict (CLI only) |
| `--red` / `RED` | `#ff5d5d` | Errors, cancel, destructive actions, delete confirm |

### Accent usage rules

- **Accent blue is the only brand color.** It marks interactivity (links,
  buttons, active states) and identity (wordmark "BACK", version number).
- **Never use accent for body text.** It's a signal, not a reading color.
- **Active/selected states** use accent-on-bg: `rgba(77, 163, 255, 0.08)`
  background + accent text/border. The dashboard's `.sort button.on` and
  `.btn-accent` both follow this pattern.
- **Hover** on the landing page uses `--accent-hi` (`#6cb4ff`); the
  dashboard uses plain `--accent`. Don't introduce `accent-hi` to the
  dashboard — its surfaces are smaller and the extra brightness reads as
  noise.

### Semantic mapping

| Semantic | Token | Example |
|---|---|---|
| Primary text | `--text` | Article titles, player time, banner |
| Secondary/supporting | `--dim` | Metadata, mode labels, hints, key legends |
| Interactive/brand | `--accent` | Links, caret, fills, wordmark "BACK" |
| Positive | `--green` | "good fit" verdict, feature checkmarks |
| Negative/destructive | `--red` | Errors, delete, cancel |
| Surface elevation | `--bg` → `--panel` → `--line` | Background < card < border |

---

## Typography

### Font stack

| Role | Family | Weights | Where |
|---|---|---|---|
| **Body / code** | IBM Plex Mono | 400, 500, 600 (+ 400i) | All text — dashboard, landing page |
| **Display / wordmark** | Martian Mono | 500, 700 | Section headers, wordmark text, kickers, subtitle |
| **Terminal** | System mono (via Ink) | — | CLI inherits the terminal's font |

```
font-family: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, monospace;
```

Both web surfaces load identical Google Fonts imports:
```html
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&family=Martian+Mono:wght@500;700&display=swap" rel="stylesheet">
```

### Type scale

| Element | Size | Weight | Font |
|---|---|---|---|
| Body | 15px | 400 | IBM Plex Mono |
| Wordmark (web) | 26px | 700 | Martian Mono |
| Section headers (h2) | 19px | 700 | Martian Mono |
| Subtitle / kicker | 12–13px | 500 | Martian Mono |
| Card title | 15px | 600 | IBM Plex Mono |
| Metadata | 12–13px | 400 | IBM Plex Mono |
| Buttons / controls | 13–14px | 400 | IBM Plex Mono |
| Code inline | 12.5px | 400 | inherit (mono) |

### Line height

Body: `1.7` (generous for readability in mono). Transcript: `1.75`. Titles:
`1.3–1.4`. These are consistent across dashboard and landing page.

---

## Wordmark

The wordmark is "readback" split: **READ** in `--text` (white), **BACK** in
`--accent` (blue). This split is the logo.

| Surface | Implementation |
|---|---|
| CLI | Half-block Unicode art in `Header.tsx` — two rows of `█▀ ▄` glyphs |
| Dashboard | HTML text: `<span>READ</span><span class="accent">BACK</span>` in Martian Mono 700 |
| Landing page | PNG wordmark (`docs/media/wordmark.png`) generated by `make_wordmark.py` — keep in sync with CLI banner |

**Version** renders next to/below the wordmark in `--accent` blue: `v3.5.0`.

---

## Layout

### Content width

| Surface | Max width | Padding |
|---|---|---|
| Dashboard | `820px` | `56px 24px 72px` (mobile: `40px 16px 56px`) |
| Landing page | `760px` | `64px 24px 48px` (mobile: `44px 24px`) |
| CLI | Terminal width (typically 80–120 cols) | `paddingX={1} paddingY={1}` (Ink) |

### Spacing rhythm

Use multiples of **4px** for spacing. Common values: 6, 8, 12, 14, 16, 20,
22, 24, 32, 48. Section gaps on the landing page are `104px` (desktop) /
`64px` (mobile).

### Border radius

`--radius: 8px` — used on cards, inputs, buttons, feature boxes, image
frames, play buttons. Consistent across dashboard and landing page. Don't use
sharp corners (0) or pill shapes (999px) except for the seek knob (50% =
circle).

### Elevation model

No shadows. Depth is communicated through background tiers:
`--bg` (deepest) → `--panel` (elevated) → `--line` (border/separator).
The active card in the dashboard adds `box-shadow: inset 2px 0 0 var(--accent)`
as a left-edge accent stripe — the only shadow-like effect in the system.

---

## Motion

Concrete values live here; the _why_ is in `emil-design-eng`.

### Curves

```css
--ease-out:    cubic-bezier(0.23, 1, 0.32, 1);   /* entrances, press feedback */
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);   /* accordion, drawer slides */
```

These are the only two curves. Don't introduce `ease`, `ease-in`, or new
custom curves without good reason.

### Durations

| What | Duration | Curve |
|---|---|---|
| Button/press feedback | 120–160ms | `--ease-out` |
| Color/border transitions | 150ms | `--ease-out` |
| Card entrance (staggered) | 280ms + `--i * 40ms` | `--ease-out` |
| Accordion (player panel) | 280ms | `--ease-drawer` |
| Slide delete (card-leave) | 200ms | `--ease-out` |
| Scroll reveal (landing) | 600ms | `--ease-out` |
| Feature print-in (landing) | 400ms + `--i * 70ms` | `--ease-out` |

### Stagger cap

Dashboard card entrances cap at `--i: 8` so a 20-item page doesn't drag.
Landing feature rows use `--i: 0–5` (6 items).

### Press feedback

Every pressable element gets `:active { transform: scale(0.95–0.99) }`.
Play buttons: `scale(0.95)`. Regular buttons: `scale(0.97–0.99)`.

### Reduced motion

`prefers-reduced-motion` is **gentle, not zero**: keep opacity fades (card
entrance, loading pulse, caret blink, scroll reveal); drop movement (slide,
accordion height, press scale, sway). Both web surfaces implement this.

---

## Background texture

Both web surfaces share a faint scanline overlay:
```css
background-image: repeating-linear-gradient(
  0deg, transparent 0 2px, rgba(255, 255, 255, 0.012) 2px 4px);
```
Applied to `body`. The CLI gets its texture from the terminal emulator.

---

## Component patterns

### Cards (dashboard)

```
.cards  — flex column, gap 1px, --line background (gap = divider), --radius
.card   — --bg background, 20px 22px padding
.active — --panel background + inset accent stripe
```

### Buttons

| Variant | Border | Text | Background | Where |
|---|---|---|---|---|
| Ghost (default) | `--line` | `--text` | none | Load more, sort, nav |
| Accent | `--accent` | `--accent` | `rgba(77,163,255,0.07)` | Primary CTA, active play |
| Destructive | none | `--dim` → `--red` on hover/confirm | none | Delete |

### Play button

40–42px square, `--radius`, `--accent` border + text. On active/playing:
filled accent background with `--bg` text. All three surfaces use this
pattern.

### Input / search

`--panel` background, `--line` border, `--radius`. Focus: `border-color:
--accent`. Placeholder: `--dim`.

### Progress / seek bar

Rail: `--line` (3px height). Fill: `--accent`. Knob (dashboard): 8px circle,
`--accent`, `border-radius: 50%`. CLI: `━` (filled, accent) + `─` (unfilled,
dim).

### Transcript (karaoke)

Spoken words: `--accent`. Unspoken: `--dim`. Both CLI and dashboard use
char-count-proportional timing. The CLI wraps manually (ink ANSI bug); the
dashboard uses CSS wrapping.

---

## Cross-surface checklist

When changing any visual element, verify consistency:

- [ ] **Color** — hex matches across `theme.ts`, `styles.css`, `style.css`
- [ ] **Font** — same Google Fonts import in both `index.html` files
- [ ] **Wordmark** — "READ" white + "BACK" blue, version in accent
- [ ] **Radius** — 8px everywhere (no sharp cards, no pills)
- [ ] **Curves** — only `--ease-out` and `--ease-drawer`
- [ ] **Reduced motion** — gentle (opacity yes, movement no)
- [ ] **Press states** — every button has `:active { scale }`

When adding a **new token** (color, curve, size):
1. Add to `theme.ts` (CLI source of truth)
2. Add to `styles.css` (dashboard `:root`)
3. Add to `style.css` (landing page `:root`)
4. Document in this skill

---

## Files to update when tokens change

```
src/cli/src/theme.ts          ← origin
src/dashboard/src/styles.css  ← CSS custom properties
src/landing-page/style.css    ← CSS custom properties
CLAUDE.md                     ← CLI section (Ghost palette description)
```
