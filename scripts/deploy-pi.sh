#!/bin/bash
# ===========================================
# readback — Pi deployment script
# ===========================================
# Builds the dashboard locally, rsyncs source + dist to Pi,
# installs Pi-compatible deps, and starts/restarts via PM2.
#
# Usage: bash scripts/deploy-pi.sh
#
# Prerequisites:
#   - .env filled in (cp .env.example .env)
#   - SSH key auth configured (ssh PI_USER@PI_HOST works without a password)
#   - PM2 installed on Pi: npm install -g pm2
# ===========================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/.env" ]; then
    export $(grep -v '^#' "$PROJECT_ROOT/.env" | xargs)
fi

# ── Validate required vars ────────────────────────────────────────
for var in PI_USER PI_HOST PI_PATH; do
    if [ -z "${!var}" ]; then
        echo "Error: $var is not set."
        echo "  cp .env.example .env  and fill it in."
        exit 1
    fi
done

PI_AUDIO_DIR="${PI_AUDIO_DIR:-/home/${PI_USER}/readback-audio-db/audio}"
PI_DB_PATH="${PI_DB_PATH:-/home/${PI_USER}/readback-audio-db/library.db}"
PI_PORT="${PI_PORT:-8080}"

# ── Banner ────────────────────────────────────────────────────────
echo ""
echo "readback — Pi deployment"
echo "Target : ${PI_USER}@${PI_HOST}:${PI_PATH}"
echo "Port   : ${PI_PORT}"
echo "Audio  : ${PI_AUDIO_DIR}"
echo ""

# ── SSH check ────────────────────────────────────────────────────
echo "Testing connection..."
if ! ssh -q -o ConnectTimeout=5 "${PI_USER}@${PI_HOST}" exit; then
    echo "Cannot connect to ${PI_HOST}. Check PI_HOST/PI_USER and SSH key auth."
    exit 1
fi
echo "✓ Connected"
echo ""

# ── Build dashboard ──────────────────────────────────────────────
echo "Building dashboard..."
cd "$PROJECT_ROOT/src/dashboard"
bun run build
echo "✓ Dashboard built"
echo ""
cd "$PROJECT_ROOT"

# ── Rsync source ─────────────────────────────────────────────────
echo "Syncing source to Pi..."
ssh "${PI_USER}@${PI_HOST}" "mkdir -p ${PI_PATH}"
rsync -az --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.egg-info' \
    --exclude='.env' \
    --exclude='config.yaml' \
    --exclude='node_modules' \
    --exclude='src/cli' \
    --exclude='src/finetune' \
    --exclude='src/voice' \
    --exclude='src/landing-page' \
    --exclude='src/dashboard/node_modules' \
    --exclude='src/dashboard/dist' \
    "$PROJECT_ROOT/" "${PI_USER}@${PI_HOST}:${PI_PATH}/"

# Dashboard dist is gitignored on Mac — rsync it separately after build.
rsync -az --delete \
    "$PROJECT_ROOT/src/dashboard/dist/" \
    "${PI_USER}@${PI_HOST}:${PI_PATH}/src/dashboard/dist/"

echo "✓ Files synced"
echo ""

# ── Pi setup ─────────────────────────────────────────────────────
echo "Setting up Pi..."

# Venv + pip run as plain SSH commands (heredoc non-interactive shells have
# intermittent DNS issues with systemd-resolved's stub at 127.0.0.53).
ssh "${PI_USER}@${PI_HOST}" "[ -d ${PI_PATH}/venv ] || python3 -m venv ${PI_PATH}/venv"
echo "✓ Venv ready"

echo "Installing dependencies..."
ssh "${PI_USER}@${PI_HOST}" "${PI_PATH}/venv/bin/pip install -q -r ${PI_PATH}/requirements-pi.txt"
echo "✓ Dependencies installed"

# First-run config + dirs (no pip here — safe to use heredoc).
ssh "${PI_USER}@${PI_HOST}" bash << ENDSSH
set -e
cd "${PI_PATH}"

if [ ! -f config.yaml ]; then
    cp config.pi.example.yaml config.yaml
    echo "✓ config.yaml created from template"
fi

mkdir -p "${PI_AUDIO_DIR}"
mkdir -p "$(dirname "${PI_DB_PATH}")"

# PM2
export PATH="\$PATH:\$(npm prefix -g)/bin"
export PYTHONPATH="${PI_PATH}/src"

if pm2 describe readback > /dev/null 2>&1; then
    pm2 restart readback --update-env
    echo "✓ PM2 restarted readback"
else
    pm2 start ${PI_PATH}/venv/bin/python \
        --name readback \
        --interpreter none \
        --cwd "${PI_PATH}" \
        -- -m readback --host 0.0.0.0 --port ${PI_PORT} --config config.yaml
    echo "✓ PM2 started readback"
fi
pm2 save

echo ""
pm2 list
ENDSSH

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Deployment complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Dashboard: http://${PI_HOST}:${PI_PORT}"
echo ""
echo "  Push data:  bash scripts/sync-pi.sh"
echo "  Restart:    ssh ${PI_USER}@${PI_HOST} 'pm2 restart readback'"
echo ""
