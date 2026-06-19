# Design Revamp — consistency pass

A pass to make the readback design system **internally consistent**: every surface
should express the same role the same way, and every value shown in the
foundation cards should be the value the components actually use.

_Date: 20 Jun 2026 · scope: tokens + all 10 components + 3 UI kits._

---

## The problem

The token files defined a full type scale, semantic tints, and control sizing,
and the **specimen cards used them** — but the **components and UI kits hardcoded
raw numbers**. The system documented a language it didn't speak. Six concrete
inconsistencies:

| # | Inconsistency | Where | Severity |
|---|---|---|---|
| 1 | Type scale documented but unused — raw px (`13`, `13.5`, `14`, `12.5`…) instead of `--text-*`; some values (`13.5`, `12.5`) matched no token | every component + kit | **high** |
| 2 | Semantic tints half-tokenized — accent used `--accent-08`, but green/yellow/red used raw `rgba(…)` | `Badge.jsx` | medium |
| 3 | Play button size disagreed (`42px` vs `40px`) and ignored `--control-h` | `WaveformPlayer`, `ReadCard` | medium |
| 4 | Caret had two geometries (`9×3` block vs `8×15` box) | `Caret`/landing vs terminal input | low |
| 5 | Spacing / weight / leading tokens unused outside the cards | components | low |
| 6 | Terminal traffic-light hexes hardcoded | `Terminal.jsx` | not a bug |

---

## The fixes

### 1 · Type scale is now real
Every inline `fontSize` in the components and kits was replaced with a `var(--text-*)`
token. Off-scale values were snapped to the nearest documented rung (shifts ≤ 1px,
imperceptible). The canonical mapping:

| was | → token | value |
|-----|---------|-------|
| `11.5` | `--text-xs` | 11.5px |
| `12`, `12.5` | `--text-sm` | 12.5px |
| `13`, `13.5` | `--text-base` | 13.5px |
| `14`, `15` | `--text-body` | 15px |
| `19` | `--text-lg` | 19px |
| `23` | `--text-xl` | 23px |

The token values themselves were **not** changed, so every foundation card stays
accurate. The scale is now authoritative: change a rung in `typography.css` and it
propagates to every component and screen.

### 2 · Semantic tints tokenized
Added `--green-10`, `--yellow-10`, `--red-10` to `tokens/colors.css` (parallel to
`--accent-08`). `Badge.jsx` now references them instead of inline `rgba(…)`. All
five chip tints now come from one place.

### 3 · One control height
Both play buttons (`WaveformPlayer`, `ReadCard`) now use `var(--control-h)` (40px)
for width and height. `42px` is gone; the token is the single source.

### 4 · One caret
The terminal input caret was changed from an `8×15` box to the `9×3` block used by
the `Caret` component and the landing page. The blinking accent underline is now a
single, consistent brand element everywhere.

### 5 · Leading token where touched
`Badge` line-height moved to `--leading-normal`. The remaining spacing/weight
literals are on-scale and low-traffic; migrating them is a possible follow-up but
carries no consistency risk today.

### 6 · Traffic lights left literal (documented)
The macOS window dots (`#ff5f57` / `#febc2e` / `#28c840`) are genuine OS chrome,
not brand colors, so they stay hardcoded — now with a comment saying so, so nobody
"fixes" them into accent tokens later.

---

## Result

- No magic font sizes remain in components or kits — all type flows from the scale.
- All status fills, the accent fills, control height, and the caret each have **one**
  definition.
- Foundation cards and live components now agree by construction.

## Suggested follow-ups (not done)
- Migrate high-traffic `gap` / `padding` literals to `--space-*` for the same
  "one source" benefit on spacing.
- Optionally vendor the woff2 font binaries for true offline use (currently CDN).
- Convert the three UI kits into copy-ready **templates**.
