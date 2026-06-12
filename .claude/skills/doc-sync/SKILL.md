---
name: doc-sync
description: Sync the project docs after a change lands. Use at the end of any feature, fix, or refactor — when the user says "update the docs", "doc update", or when code changes are finished and the docs haven't been touched. Maps the diff to the right doc surfaces (CLAUDE.md, README.md, ARCHITECTURE.md, cli/README.md, plan.md, version anchors, WS protocol docstring) and updates only what the change actually touched.
---

# Doc sync — keep readback's docs honest after a change

Run this at the **end** of a change, when the code is done and verified. The
job is to map what changed to the doc surfaces that describe it, and update
only those. Don't rewrite docs the diff doesn't touch.

## 1. Establish the change

```bash
git diff main... --stat        # or @{u}.. / HEAD for uncommitted work
```

The diff is ground truth. Read it (or recall what you just implemented) before
opening any doc.

## 2. Map changed areas → doc surfaces

| If the diff touches… | update |
|---|---|
| anything user-visible (commands, UI, flags, config keys) | `README.md` (user-facing tone, terminal-first) |
| `cli/` | `cli/README.md` + the CLI section of `CLAUDE.md` |
| `readback/web/server.py` WS messages or endpoints | the **WS protocol docstring** at the top of `server.py` + `ARCHITECTURE.md` if the pipeline/extension points moved |
| `readback/` internals (engine, reader, llm, config) | the matching **Critical Implementation Notes** section of `CLAUDE.md` — implementation notes, gotchas, exact knobs |
| pipeline shape, concurrency model, new client/extension point | `ARCHITECTURE.md` |
| `config.yaml` schema (`config.py`) | `CLAUDE.md` Config section + `README.md` if users set it |
| `finetune/` or voice workflow | `finetune/README.md` / `.claude/skills/csm-voice` |
| Project structure (new modules/dirs) | the **tree in CLAUDE.md** Project Structure |

Always check, regardless of area:

- **`plan.md`** — flip the matching entry's status (`proposed` → `in progress`
  → `done`), with a one-paragraph "what actually shipped + how verified" note.
  Newest entry on top; never delete history.
- **README.md → Roadmap** — the **only** open-items tracker (TODO.md was
  merged into it and deleted; never recreate a second tracker). Check off
  items the change shipped; add follow-ups there.
- **Stale claims** — grep the docs for the thing you changed (a command name, a
  message type, a default) and fix every mention, not just the section you
  remember.

## 3. Version (only when releasing)

A release bumps **all four anchors together**:
`pyproject.toml`, `readback/__init__.py`, `readback/web/frontend/package.json`,
`cli/package.json` — then update the **Version section at the bottom of
CLAUDE.md** (one line for the new version, condense the older notes). The CLI
banner reads its version from `cli/package.json`; remind the user that the
standalone binary needs `cli/install.sh` re-run to pick it up.

Don't bump unless the user asked for a release.

## 4. House style

- **CLAUDE.md** is for the next agent: terse, gotcha-dense, exact file paths
  and knob names, ⚠ for traps. No marketing.
- **README.md** is for users: what it does and how to run it; keep the
  terminal-first voice of the existing text.
- **ARCHITECTURE.md** is the system view: pipeline, concurrency, extension
  points — no implementation minutiae (those live in CLAUDE.md).
- Keep removed-feature hygiene: if something was deleted, delete its doc
  mentions too (this repo has a history of stale voice-assistant references —
  don't add to it).

## 5. Done check

One pass at the end: `grep -rn "<old name/command/default>" *.md cli/*.md`
returns nothing stale, and `plan.md`'s top entry status matches reality.
