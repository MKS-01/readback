#!/usr/bin/env bash
# readback-cli — build a standalone binary and install it on PATH.
#
#   ./install.sh                 # → ~/.local/bin/readback-cli
#   READBACK_BIN_DIR=/usr/local/bin ./install.sh
#
# Re-run after pulling new changes; the binary is self-contained (Bun runtime
# included) but the repo path is baked in so it can auto-spawn the server.
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd ../.. && pwd)"
BIN_DIR="${READBACK_BIN_DIR:-$HOME/.local/bin}"
BIN_NAME="readback-cli"

command -v bun >/dev/null 2>&1 || {
  echo "error: bun is required — install it from https://bun.sh" >&2
  exit 1
}

echo "▸ compiling ${BIN_NAME}…"
bun build ./src/index.tsx --compile \
  --define "process.env.READBACK_ROOT=\"${REPO_ROOT}\"" \
  --outfile "dist/${BIN_NAME}"

mkdir -p "$BIN_DIR"
install -m 755 "dist/${BIN_NAME}" "${BIN_DIR}/${BIN_NAME}"
echo "✓ installed ${BIN_DIR}/${BIN_NAME}"

case ":$PATH:" in
  *":${BIN_DIR}:"*) echo "✓ ${BIN_DIR} is on your PATH — run: ${BIN_NAME}" ;;
  *)
    echo "⚠ ${BIN_DIR} is not on your PATH — add this to ~/.zshrc:"
    echo "    export PATH=\"${BIN_DIR}:\$PATH\""
    ;;
esac
