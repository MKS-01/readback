#!/bin/bash
# ===========================================
# readback — Mac → Pi data sync
# ===========================================
# Rsyncs generated WAVs + the SQLite library DB from this Mac
# to the Pi. Run after generating new reads on Mac.
#
# Only syncs WAVs created/modified since the last successful sync
# (tracked via a .last-sync marker). Pass --full to force a full sync.
# The DB is always synced (small, and rows may be deleted).
#
# Usage: bash scripts/sync-pi.sh [--full]
# ===========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Mac-side audio + DB live in the sibling readback-audio-db/ dir by default.
MAC_AUDIO_DIR="${PROJECT_ROOT}/../readback-audio-db/audio"
MAC_DB_PATH="${PROJECT_ROOT}/../readback-audio-db/library.db"
LAST_SYNC_MARKER="${PROJECT_ROOT}/../readback-audio-db/.last-sync"

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

# ── Determine sync mode ─────────────────────────────────────────
FULL_SYNC=false
if [[ "$1" == "--full" ]]; then
    FULL_SYNC=true
fi

# Find new/modified WAVs since last sync
NEW_FILES=()
if [ "$FULL_SYNC" = true ] || [ ! -f "$LAST_SYNC_MARKER" ]; then
    while IFS= read -r -d '' f; do NEW_FILES+=("$f"); done \
        < <(find "$MAC_AUDIO_DIR" -maxdepth 1 -name '*.wav' -type f -print0)
    SYNC_LABEL="full"
else
    while IFS= read -r -d '' f; do NEW_FILES+=("$f"); done \
        < <(find "$MAC_AUDIO_DIR" -maxdepth 1 -name '*.wav' -type f -newer "$LAST_SYNC_MARKER" -print0)
    SYNC_LABEL="incremental (since $(date -r "$LAST_SYNC_MARKER" '+%Y-%m-%d %H:%M'))"
fi

echo ""
echo "readback — sync Mac → Pi ($SYNC_LABEL)"
echo "Audio : $MAC_AUDIO_DIR → ${PI_USER}@${PI_HOST}:${PI_AUDIO_DIR}"
echo "DB    : $MAC_DB_PATH   → ${PI_USER}@${PI_HOST}:${PI_DB_PATH}"
echo "WAVs  : ${#NEW_FILES[@]} to sync"
echo ""

if [ ${#NEW_FILES[@]} -eq 0 ] && [ "$FULL_SYNC" = false ]; then
    echo "No new audio files since last sync."
    echo "Syncing DB only (handles deletes)..."
    echo ""
fi

# ── Stop Pi server (avoid SQLite lock during DB copy) ─────────────
echo "Pausing Pi server..."
ssh "${PI_USER}@${PI_HOST}" \
    "export PATH=\"\$PATH:\$(npm prefix -g)/bin\" && pm2 stop readback" \
    2>/dev/null || true

SSH_OPTS="-o ServerAliveInterval=15 -o ServerAliveCountMax=8"

# ── Sync audio ────────────────────────────────────────────────────
if [ ${#NEW_FILES[@]} -gt 0 ]; then
    echo "Syncing ${#NEW_FILES[@]} WAV(s)..."
    ssh $SSH_OPTS "${PI_USER}@${PI_HOST}" "mkdir -p ${PI_AUDIO_DIR}"

    # Build a file list for rsync --files-from (basenames only)
    FILE_LIST=$(mktemp)
    for f in "${NEW_FILES[@]}"; do
        basename "$f" >> "$FILE_LIST"
    done

    if [ "$FULL_SYNC" = true ]; then
        # Full sync with --delete to clean up orphaned WAVs on Pi
        rsync -az --delete --timeout=300 -e "ssh $SSH_OPTS" \
            --include='*.wav' \
            --exclude='*' \
            "$MAC_AUDIO_DIR/" "${PI_USER}@${PI_HOST}:${PI_AUDIO_DIR}/"
    else
        rsync -az --timeout=300 -e "ssh $SSH_OPTS" \
            --files-from="$FILE_LIST" \
            "$MAC_AUDIO_DIR/" "${PI_USER}@${PI_HOST}:${PI_AUDIO_DIR}/"
    fi
    rm -f "$FILE_LIST"
    echo "✓ Audio synced (${#NEW_FILES[@]} file(s))"
else
    echo "✓ Audio up to date"
fi

# ── Sync DB ──────────────────────────────────────────────────────
echo "Syncing library DB..."
rsync -az --timeout=60 -e "ssh $SSH_OPTS" \
    "$MAC_DB_PATH" "${PI_USER}@${PI_HOST}:${PI_DB_PATH}"
echo "✓ DB synced"

# ── Update sync marker ──────────────────────────────────────────
touch "$LAST_SYNC_MARKER"

# ── Restart Pi server ────────────────────────────────────────────
echo "Restarting Pi server..."
ssh $SSH_OPTS "${PI_USER}@${PI_HOST}" \
    "export PATH=\"\$PATH:\$(npm prefix -g)/bin\" && pm2 restart readback" \
    2>/dev/null || true
echo "✓ Server resumed"

echo ""
echo "Sync complete. Refresh the dashboard on Pi to see new reads."
echo ""
