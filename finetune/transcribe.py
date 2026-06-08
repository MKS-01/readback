#!/usr/bin/env python3
"""Auto-transcribe training clips → write a matching .txt next to every audio
file under finetune/data/ (the layout `csm-mlx finetune convert` expects).

The reader app dropped all ASR (v0.8.0), so this is a standalone one-off helper:
it uses mlx-whisper, which is NOT a project dependency. Install on demand:

    .venv/bin/python -m pip install mlx-whisper

Then:

    .venv/bin/python finetune/transcribe.py            # whole finetune/data tree
    .venv/bin/python finetune/transcribe.py path/to/dir # a specific folder
    .venv/bin/python finetune/transcribe.py --force     # overwrite existing .txt

CSM conditions on the (audio, text) pair, so transcripts must be accurate —
ALWAYS eyeball the generated .txt files and fix any mistakes before training.
"""
from __future__ import annotations

import sys
from pathlib import Path

AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".m4a"}
HF_MODEL = "mlx-community/whisper-small-mlx"   # small = good accuracy, fast on M-series


def main(argv: list[str]) -> int:
    force = "--force" in argv
    args = [a for a in argv if not a.startswith("--")]
    root = Path(args[0]) if args else Path(__file__).parent / "data"
    if not root.exists():
        print(f"no such path: {root}")
        return 1

    try:
        import mlx_whisper
    except ImportError:
        print("mlx-whisper not installed. Run:\n"
              "  .venv/bin/python -m pip install mlx-whisper")
        return 1

    clips = sorted(p for p in root.rglob("*") if p.suffix.lower() in AUDIO_EXTS)
    if not clips:
        print(f"no audio files under {root}")
        return 1

    for wav in clips:
        txt = wav.with_suffix(".txt")
        if txt.exists() and not force:
            print(f"skip (exists): {txt.relative_to(root)}")
            continue
        text = mlx_whisper.transcribe(str(wav), path_or_hf_repo=HF_MODEL)["text"].strip()
        txt.write_text(text, encoding="utf-8")
        print(f"wrote {txt.relative_to(root)}: {text[:70]}{'…' if len(text) > 70 else ''}")

    print("\nDone. Review the .txt files for accuracy before training.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
