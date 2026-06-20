---
name: upgrade-deps
description: Upgrade Python, JS, and system dependencies across the project. Use when the user says "upgrade deps", "update packages", "bump dependencies", or wants to move to a newer Python/Bun/package version. Covers pyproject.toml, requirements-pi.txt, CLI (Bun/Ink), dashboard (Vue/Vite), CI matrix, and setup.sh.
---

# Dependency upgrade — readback

Upgrade one or more dependency layers. Each layer is independent — upgrade what
the user asks for, skip what they don't mention. When they say "everything",
run all layers.

## 0. Before touching anything

```bash
source .venv/bin/activate
python --version                          # current Python
pip list --outdated                       # Python packages with available updates
cd src/cli && bun outdated; cd ../..      # CLI JS packages
cd src/dashboard && bun outdated; cd ../..# dashboard JS packages
```

Report what's outdated in a short table before making changes. **Get a go-ahead
before upgrading** — some packages have breaking changes worth flagging.

## Layer 1 — Python version

The ceiling is set by `csm-mlx` (the most constrained dep). Check:

```bash
pip show csm-mlx | grep -i 'requires-python\|Requires-Python'
# or: grep Requires-Python .venv/lib/python*/site-packages/csm_mlx*/METADATA
```

If a newer Python is supported:

1. `brew install python@X.YZ`
2. Recreate the venv: `rm -rf .venv && python3.XZ -m venv .venv`
3. `source .venv/bin/activate && pip install -e ".[test]"`
4. `python -m pytest` — all tests must pass
5. Update if needed:
   - `pyproject.toml` `requires-python` upper bound
   - `.github/workflows/ci.yml` matrix (add the new version)
   - `scripts/setup.sh` Python version search range + messages
   - `CLAUDE.md` install section if the example command mentions a version

**Do NOT remove older Python versions from the CI matrix** unless they're
genuinely broken — the Pi may still run an older version.

## Layer 2 — Python packages (pyproject.toml)

The project has two dep files:

| File | Where it runs | What it covers |
|---|---|---|
| `pyproject.toml` `[project.dependencies]` | Mac (Apple Silicon) | Full stack: csm-mlx, mlx-lm, mlx-vlm, trafilatura, fastapi, etc. |
| `requirements-pi.txt` | Raspberry Pi | Server-only subset: fastapi, uvicorn, pydantic, pyyaml, numpy. No MLX. |

### Upgrade steps

```bash
source .venv/bin/activate
pip list --outdated --format=columns
```

For each outdated package:

1. **Check the changelog** for breaking changes (especially: `mlx`, `csm-mlx`,
   `fastapi`, `pydantic`, `trafilatura`).
2. Bump the version pin in `pyproject.toml`.
3. If the package also appears in `requirements-pi.txt`, bump it there too.
4. `pip install -e ".[test]"` — verify it installs clean.
5. `python -m pytest` — all tests pass.
6. Smoke test: `readback` boots, paste a URL, summary mode works.

### Constraint rules

- `csm-mlx` is a **git dep** (`@ git+https://...`). To upgrade: `pip install
  --force-reinstall "csm-mlx @ git+https://github.com/senstella/csm-mlx"`, then
  re-check its `Requires-Python` (it may unlock a newer Python).
- `mlx` and `mlx-metal` are pulled transitively by `csm-mlx` and `mlx-lm` —
  don't pin them directly unless there's a floor version needed.
- `numpy` has an upper bound (`<3.0.0`) — only raise it if downstream deps
  (soundfile, mlx) support numpy 3.
- `ollama` — **being removed** (see llm-migration branch). Once that lands,
  delete it from both `pyproject.toml` and `requirements-pi.txt`.

### requirements-pi.txt sync

After upgrading `pyproject.toml`, verify `requirements-pi.txt` still matches.
The Pi file pins the **same lower bounds** as pyproject.toml for shared packages.
Packages that are Mac-only (csm-mlx, mlx-lm, mlx-vlm, trafilatura, soundfile,
huggingface-hub) are **excluded** from the Pi file — they're lazy imports.

## Layer 3 — CLI (Bun + Ink + React)

```bash
cd src/cli
bun outdated
```

Core packages and what to watch:

| Package | Notes |
|---|---|
| `ink` | Major bumps can change the component API. Check their changelog. |
| `ink-text-input` | Must match ink's major version. |
| `react` | ink 6 requires React 19. Don't downgrade. |
| `@types/bun` | Safe to bump freely. |
| `typescript` | Safe to bump; run `bun tsc --noEmit` after. |

### Upgrade steps

```bash
cd src/cli
bun update                                # bump within semver ranges
bun tsc --noEmit                          # type-check
bun run start                             # smoke test (or use drive-cli skill)
```

For major version bumps (e.g. ink 6 → 7): read the migration guide, make the
changes, then verify via `drive-cli` skill or manual testing.

After upgrading, rebuild the standalone binary:

```bash
./install.sh                              # recompiles ~/.local/bin/readback-cli
```

## Layer 4 — Dashboard (Vue + Vite)

```bash
cd src/dashboard
bun outdated
```

| Package | Notes |
|---|---|
| `vue` | Major bumps are rare. Check for API deprecations. |
| `vite` | Major bumps may need `vite.config.ts` changes. |
| `@vitejs/plugin-vue` | Must match Vite's major version. |
| `vue-tsc` | Type-checking; safe to bump. |
| `typescript` | Keep in sync with CLI's TS version (both should be ~5.x). |

### Upgrade steps

```bash
cd src/dashboard
bun update
bun run build                             # must produce dist/ cleanly
```

Open `http://localhost:8000` (with server running) and verify the dashboard
loads, search works, playback works.

## Layer 5 — Bun itself

```bash
bun --version
# Upgrade:
brew upgrade bun
# or:
curl -fsSL https://bun.sh/install | bash
```

After upgrading Bun, rebuild both JS projects:

```bash
cd src/cli && bun install && bun tsc --noEmit
cd src/dashboard && bun install && bun run build
```

## Layer 6 — CI workflow actions

Check `.github/workflows/ci.yml` and `pages.yml` for pinned action versions:

```bash
grep 'uses:' .github/workflows/*.yml
```

Bump `actions/checkout`, `actions/setup-python`, `actions/upload-pages-artifact`,
`actions/deploy-pages` to their latest `@v*` tags. These are safe to bump — they
follow semver.

## Post-upgrade checklist

After any layer:

- [ ] `python -m pytest` passes
- [ ] `readback` boots and serves `/api/config`
- [ ] CLI: `bun tsc --noEmit` clean in `src/cli/`
- [ ] Dashboard: `bun run build` clean in `src/dashboard/`
- [ ] No version pins conflict between `pyproject.toml` and `requirements-pi.txt`

If the upgrade touches the Python version or a core dep (mlx, csm-mlx, fastapi),
do a full smoke test: paste a URL → Summary mode → audio plays.
