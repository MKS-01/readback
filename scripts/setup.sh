#!/usr/bin/env bash
# readback — one-command setup for first-time users.
#
#   bash scripts/setup.sh
#
# readback is built for macOS on Apple Silicon. This script checks your
# prerequisites, creates the Python venv and installs readback, builds the
# terminal CLI + the web dashboard, and offers to pre-download the MLX summary
# model and CSM-1B voice weights so your first read is fast.
#
# Safe to re-run — every step skips work that's already done.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

# ── pretty output ───────────────────────────────────────────────
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  RED=$'\033[31m'; BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; BLUE=""; RESET=""
fi
step() { printf "\n%s▸ %s%s\n" "$BOLD" "$1" "$RESET"; }
ok()   { printf "%s✓%s %s\n" "$GREEN" "$RESET" "$1"; }
warn() { printf "%s⚠%s %s\n" "$YELLOW" "$RESET" "$1"; }
die()  { printf "%s✗ %s%s\n" "$RED" "$1" "$RESET" >&2; exit 1; }
ask()  { # ask "question" "Y" → returns 0 for yes; default in $2 (Y/N)
  local q="$1" def="${2:-Y}" ans
  if [ ! -t 0 ]; then [ "$def" = "Y" ]; return; fi   # non-interactive → use default
  local hint="[Y/n]"; [ "$def" = "N" ] && hint="[y/N]"
  read -r -p "$(printf "%s%s%s %s " "$BLUE" "$q" "$RESET" "$hint")" ans || true
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[Yy] ]]
}

printf "%s%sreadback setup%s\n" "$BOLD" "$BLUE" "$RESET"
printf "%sone-command install for macOS on Apple Silicon%s\n" "$DIM" "$RESET"

# ── 1. platform ─────────────────────────────────────────────────
step "Checking your platform"
[ "$(uname -s)" = "Darwin" ] || die "readback is built for macOS — this is $(uname -s). It won't run here."
if [ "$(uname -m)" = "arm64" ]; then
  ok "macOS on Apple Silicon ($(uname -m))"
else
  warn "Not Apple Silicon ($(uname -m)) — CSM-1B TTS needs MLX/Metal and will not run. Continuing anyway."
fi

# ── 2. Python 3.10–3.12 ─────────────────────────────────────────
step "Finding Python 3.10–3.12"
PY=""
for cand in python3.11 python3.12 python3.10 python3; do
  if command -v "$cand" >/dev/null 2>&1; then
    ver="$("$cand" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
    case "$ver" in
      3.10|3.11|3.12) PY="$cand"; break ;;
    esac
  fi
done
[ -n "$PY" ] || die "No Python 3.10–3.12 found. Install one (e.g. 'brew install python@3.11') and re-run."
ok "Using $PY ($("$PY" --version 2>&1 | awk '{print $2}'))"

# ── 3. venv + install readback ──────────────────────────────────
step "Setting up the Python environment"
if [ ! -d "$ROOT/.venv" ]; then
  "$PY" -m venv "$ROOT/.venv"
  ok "created .venv"
else
  ok ".venv already exists"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
python -m pip install -q --upgrade pip
echo "  installing readback (csm-mlx is a git dep — this can take a few minutes)…"
python -m pip install -q -e .
ok "readback installed into .venv"

# ── 3b. config.yaml (from the template) ─────────────────────────
step "Configuration"
if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
  ok "config.yaml created from config.example.yaml — edit it to add your feeds, voices, or paths"
else
  # Never overwrite: config.yaml is the user's own file (gitignored), and a
  # re-run of this script must not clobber their edits.
  ok "config.yaml already exists — left untouched"
fi

# ── 4. terminal CLI (Bun) ───────────────────────────────────────
step "Building the terminal CLI"
if command -v bun >/dev/null 2>&1; then
  ( cd src/cli && ./install.sh )
else
  warn "Bun not found — skipping the CLI + dashboard build. Install it from https://bun.sh and re-run, or run the server alone with 'readback'."
fi

# ── 5. web dashboard (Bun) ──────────────────────────────────────
if command -v bun >/dev/null 2>&1; then
  step "Building the web dashboard"
  ( cd src/dashboard && bun run build )
  ok "dashboard built → src/dashboard/dist (served at / by 'readback')"
fi

# ── 6. MLX summary model ───────────────────────────────────────
step "Summary-mode model (MLX-LM)"
MODEL="$(grep -A4 '^llm:' config.yaml | grep -m1 'model:' | sed -E 's/.*model:[[:space:]]*"?([^"#]+)"?.*/\1/' | xargs || true)"
MODEL="${MODEL:-mlx-community/Qwen3.5-9B-4bit}"
if ask "Pre-download the summary model '$MODEL' now? (~4.5 GB; needed only for Summary mode)" "N"; then
  echo "  downloading $MODEL…"
  python -c "from huggingface_hub import snapshot_download; snapshot_download('$MODEL')" \
    && ok "downloaded $MODEL"
else
  echo "  Skipped — it downloads automatically on your first Summary-mode read."
fi

# ── 7. CSM-1B voice weights (optional pre-warm) ─────────────────
step "Voice weights (CSM-1B, ~6 GB)"
if ask "Pre-download the CSM-1B weights now so your first read isn't slow?" "N"; then
  echo "  downloading + warming the MLX graph (one time)…"
  python -c "from readback.config import Config; from readback.tts.synthesizer import Synthesizer; Synthesizer(Config.load().tts).load(); print('  warm.')" \
    && ok "CSM-1B weights cached in ~/.cache/huggingface/hub/"
else
  echo "  Skipped — they download automatically on your first read."
fi

# ── done ────────────────────────────────────────────────────────
printf "\n%s%s✓ readback is ready.%s\n" "$BOLD" "$GREEN" "$RESET"
if command -v bun >/dev/null 2>&1; then
  printf "Start reading:  %sreadback-cli%s   (paste a URL — it auto-starts the server)\n" "$BOLD" "$RESET"
else
  printf "Start the server:  %sreadback%s   then open http://127.0.0.1:8000/\n" "$BOLD" "$RESET"
fi
printf "%sSetup guide + troubleshooting: docs/SETUP.md%s\n" "$DIM" "$RESET"
