#!/usr/bin/env bash
#
# make_clone_voice.sh — prep reference clips for Qwen3-TTS voice cloning.
#
# Converts ANY audio/video file (m4a, mp3, mp4, a mislabeled .wav, etc.) into a
# clean PCM wav that mlx-audio's Base model can actually load — and optionally
# trims it to a single clean segment. Renaming an .m4a to .wav does NOT work;
# the bytes are still AAC and the cloning model can't decode them. This does a
# real re-encode to mono / 24 kHz / 16-bit PCM.
#
# Usage:
#   Single file:
#     scripts/make_clone_voice.sh <input-file> <clone-name> [options]
#   Whole folder (batch — converts every audio file inside):
#     scripts/make_clone_voice.sh --batch <input-dir> [options]
#
# Options:
#   -s, --start    <sec>  start offset to extract from   (single-file only)
#   -d, --duration <sec>  length to extract              (single-file only)
#   -o, --out-dir  <dir>  output folder (default: <project>/voice)
#   -r, --rate     <hz>   output sample rate (default 24000 — Qwen3-TTS native)
#   -l, --lang     <code> transcription language hint for the snippet (e.g. hi)
#   -b, --batch           treat the input as a directory of clips
#   -h, --help            show this help
#
# Output: <out-dir>/<name>.wav   (mono, <rate> Hz, 16-bit PCM)
#
# Examples:
#   # one clip, whole thing:
#   scripts/make_clone_voice.sh ~/Desktop/voice/e23.m4a e23 -l hi
#   # one clip, clean 10s window from 0:02:
#   scripts/make_clone_voice.sh ~/Desktop/voice/talk.mp4 myvoice -s 2 -d 10 -l hi
#   # convert a whole folder of samples into ~/Desktop/voice/new-sample/:
#   scripts/make_clone_voice.sh --batch ~/Desktop/voice -o ~/Desktop/voice/new-sample -l hi

set -euo pipefail

# Default output: the project's voice/ folder (resolved from this script's path).
OUT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/voice"
RATE=24000
START=""
DURATION=""
LANG_HINT=""
BATCH=0

err()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; }
info() { printf '\033[36m›\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m✓\033[0m %s\n' "$*"; }

usage() { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

# ---- parse args ----
POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s|--start)    START="$2"; shift 2 ;;
    -d|--duration) DURATION="$2"; shift 2 ;;
    -o|--out-dir)  OUT_DIR="$2"; shift 2 ;;
    -r|--rate)     RATE="$2"; shift 2 ;;
    -l|--lang)     LANG_HINT="$2"; shift 2 ;;
    -b|--batch)    BATCH=1; shift ;;
    -h|--help)     usage 0 ;;
    -*)            err "unknown option: $1"; usage 1 ;;
    *)             POSITIONAL+=("$1"); shift ;;
  esac
done

# ---- preflight ----
command -v ffmpeg  >/dev/null 2>&1 || { err "ffmpeg not found (brew install ffmpeg)"; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { err "ffprobe not found (brew install ffmpeg)"; exit 1; }
OUT_DIR="${OUT_DIR/#\~/$HOME}"   # expand a leading ~

# Convert one file → $OUT_DIR/$name.wav. Args: <input> <name> [trim-args...]
convert_one() {
  local input="$1" name="$2"; shift 2
  local dest="$OUT_DIR/$name.wav"

  local src
  src=$(ffprobe -v error -show_entries format=duration \
    -show_entries stream=codec_name,sample_rate,channels \
    -of default=noprint_wrappers=1 "$input" 2>/dev/null || true)
  info "source: $input"
  echo "$src" | sed 's/^/    /'

  info "writing $dest  (mono, ${RATE} Hz, pcm_s16le)"
  ffmpeg -y -loglevel error "$@" -i "$input" \
    -ar "$RATE" -ac 1 -c:a pcm_s16le "$dest"

  local dur
  dur=$(ffprobe -v error -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$dest" 2>/dev/null || echo "?")
  ok "done — ${dur}s clip at $dest"
  if [[ "$dur" != "?" ]]; then
    local di=${dur%.*}
    if   (( di < 4  )); then err "clip is short (<4s) — quality may suffer; aim for 8–12s"
    elif (( di > 20 )); then info "clip is long (>20s) — a clean 8–12s window often clones better (use -s/-d)"
    fi
  fi
  CLIP_PATHS+=("$name|$dest")   # collected for the config snippet
}

# Print a config.yaml snippet for every clip converted this run.
print_snippet() {
  local lang_line=""
  [[ -n "$LANG_HINT" ]] && lang_line=$'\n'"        ref_lang: $LANG_HINT"
  echo
  echo "Paste under  tts.qwen.clones  in config.yaml:"
  echo
  local entry name path
  for entry in "${CLIP_PATHS[@]}"; do
    name="${entry%%|*}"; path="${entry#*|}"
    printf '      - name: %s\n        label: "%s (cloned)"\n        wav: %s%s\n' \
      "$name" "$name" "$path" "$lang_line"
  done
  echo
  echo "Then: launch local-tts → Settings → voice picker → \"Cloned voices\"."
}

CLIP_PATHS=()
mkdir -p "$OUT_DIR"

if [[ $BATCH -eq 1 ]]; then
  # ---- batch: convert every audio file in the input directory ----
  [[ ${#POSITIONAL[@]} -ge 1 ]] || { err "--batch needs <input-dir>"; usage 1; }
  SRC_DIR="${POSITIONAL[0]/#\~/$HOME}"
  [[ -d "$SRC_DIR" ]] || { err "not a directory: $SRC_DIR"; exit 1; }
  shopt -s nullglob nocaseglob
  found=0
  for f in "$SRC_DIR"/*.{m4a,mp3,mp4,aac,wav,flac,ogg,opus,caf,aiff}; do
    [[ -f "$f" ]] || continue
    base="$(basename "$f")"; name="${base%.*}"
    # Skip outputs we'd be writing into the same dir to avoid self-reconvert.
    [[ "$f" == "$OUT_DIR/$name.wav" ]] && continue
    convert_one "$f" "$name"
    found=$((found+1))
    echo
  done
  shopt -u nullglob nocaseglob
  (( found > 0 )) || { err "no audio files found in $SRC_DIR"; exit 1; }
  print_snippet
else
  # ---- single file ----
  [[ ${#POSITIONAL[@]} -ge 2 ]] || { err "need <input-file> and <clone-name>"; usage 1; }
  INPUT="${POSITIONAL[0]/#\~/$HOME}"; NAME="${POSITIONAL[1]}"
  [[ -f "$INPUT" ]] || { err "input file not found: $INPUT"; exit 1; }
  [[ "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]] || { err "clone-name must be [a-zA-Z0-9_-]"; exit 1; }
  TRIM=()
  [[ -n "$START"    ]] && TRIM+=(-ss "$START")
  [[ -n "$DURATION" ]] && TRIM+=(-t "$DURATION")
  convert_one "$INPUT" "$NAME" ${TRIM[@]+"${TRIM[@]}"}
  print_snippet
fi
