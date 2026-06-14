#!/bin/bash
# ===========================================
# readback — Mac → Pi data sync
# ===========================================
# Rsyncs generated WAVs + the SQLite library DB from this Mac
# to the Pi. Run after generating new reads on Mac.
#
# Usage: bash scripts/sync-pi.sh
# ===========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Mac-side audio + DB live in the sibling readback-audio-db/ dir by default.
MAC_AUDIO_DIR="${PROJECT_ROOT}/../readback-audio-db/audio"
MAC_DB_PATH="${PROJECT_ROOT}/../readback-audio-db/library.db"

if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

# ── Validate ──────────────────────────────────────────────────────
for var in PI_USER PI_HOST; do
    if [ -z "${!var}" ]; then
        echo "Error: $var is not set. cp .env.example .env and fill it in."
        exit 1
    fi
done

PI_AUDIO_DIR="${PI_AUDIO_DIR:-/home/${PI_USER}/readback-audio-db/audio}"
PI_DB_PATH="${PI_DB_PATH:-/home/${PI_USER}/readback-audio-db/library.db}"

if [ ! -d "$MAC_AUDIO_DIR" ]; then
    echo "Error: audio dir not found at $MAC_AUDIO_DIR"
    echo "Generate at least one read on Mac first."
    exit 1
fi

if [ ! -f "$MAC_DB_PATH" ]; then
    echo "Error: library DB not found at $MAC_DB_PATH"
    echo "Generate at least one read on Mac first."
    exit 1
fi

echo ""
echo "readback — sync Mac → Pi"
echo "Audio : $MAC_AUDIO_DIR → ${PI_USER}@${PI_HOST}:${PI_AUDIO_DIR}"
echo "DB    : $MAC_DB_PATH   → ${PI_USER}@${PI_HOST}:${PI_DB_PATH}"
echo ""

# ── Stop Pi server (avoid SQLite lock during DB copy) ─────────────
echo "Pausing Pi server..."
ssh "${PI_USER}@${PI_HOST}" \
    "export PATH=\"\$PATH:\$(npm prefix -g)/bin\" && pm2 stop readback" \
    2>/dev/null || true

SSH_OPTS="-o ServerAliveInterval=15 -o ServerAliveCountMax=8"

# ── Sync audio ────────────────────────────────────────────────────
echo "Syncing audio..."
ssh $SSH_OPTS "${PI_USER}@${PI_HOST}" "mkdir -p ${PI_AUDIO_DIR}"
rsync -az --timeout=120 -e "ssh $SSH_OPTS" \
    --include='*.wav' \
    --exclude='*' \
    "$MAC_AUDIO_DIR/" "${PI_USER}@${PI_HOST}:${PI_AUDIO_DIR}/"
echo "✓ Audio synced"

# ── Sync DB ──────────────────────────────────────────────────────
echo "Syncing library DB..."
rsync -az --timeout=60 -e "ssh $SSH_OPTS" \
    "$MAC_DB_PATH" "${PI_USER}@${PI_HOST}:${PI_DB_PATH}"
echo "✓ DB synced"

# ── Restart Pi server ────────────────────────────────────────────
echo "Restarting Pi server..."
ssh $SSH_OPTS "${PI_USER}@${PI_HOST}" \
    "export PATH=\"\$PATH:\$(npm prefix -g)/bin\" && pm2 restart readback" \
    2>/dev/null || true
echo "✓ Server resumed"

echo ""
echo "Sync complete. Refresh the dashboard on Pi to see new reads."
echo ""
