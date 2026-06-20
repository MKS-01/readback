"""Local MLX model discovery for the summary LLM.

Lists MLX models downloaded to the HuggingFace cache and attaches a RAM-fit
verdict per model so a client can warn before switching to something that would
swap/thrash, plus a recommendation for summarization.

Fit heuristic (deliberately simple): a model needs roughly its on-disk size in
unified memory for weights, plus KV cache and runtime overhead — estimated as
`size * 1.2 + 1 GiB`. CSM-1B, the OS and apps also live in the same unified
memory, so a model is only a comfortable fit well below total RAM:

    good   need <= 50% of total RAM
    tight  need <= 75% of total RAM
    no     anything above
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from readback.config import LLMConfig

log = logging.getLogger("readback.llm")

_GIB = 1024 ** 3

_NON_CHAT_MARKERS = ("embed", "bge", "minilm", "rerank")
_VISION_MARKERS = ("VL", "vision", "vlm")


def _total_ram_bytes() -> int:
    try:
        return int(subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
            check=True,
        ).stdout.strip())
    except Exception:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")


def _fit(size_bytes: int, total_ram: int) -> str:
    need = size_bytes * 1.2 + _GIB
    if need <= total_ram * 0.50:
        return "good"
    if need <= total_ram * 0.75:
        return "tight"
    return "no"


def _is_chat_model(name: str) -> bool:
    low = name.lower()
    return not any(m in low for m in _NON_CHAT_MARKERS)


def _is_vision_model(name: str) -> bool:
    return any(m in name for m in _VISION_MARKERS)


def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def _short_name(model_id: str) -> str:
    """Extract a display-friendly short name from a HF model ID.
    'mlx-community/Qwen3.5-9B-4bit' → 'Qwen3.5-9B-4bit'"""
    return model_id.rsplit("/", 1)[-1] if "/" in model_id else model_id


def _scan_downloaded_models() -> list[dict]:
    """Scan the HuggingFace cache for downloaded MLX models.

    Returns a list of dicts with model_id, size_bytes, and metadata from
    config.json when available.
    """
    cache_dir = _hf_cache_dir()
    if not cache_dir.exists():
        return []

    models = []
    for entry in cache_dir.iterdir():
        if not entry.name.startswith("models--"):
            continue
        model_id = entry.name.removeprefix("models--").replace("--", "/")

        snapshots_dir = entry / "snapshots"
        if not snapshots_dir.exists():
            continue
        snapshot_dirs = sorted(snapshots_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not snapshot_dirs:
            continue
        snapshot = snapshot_dirs[0]

        config_path = snapshot / "config.json"
        params = None
        if config_path.exists():
            try:
                with open(config_path) as f:
                    cfg = json.load(f)
                params = cfg.get("num_parameters") or cfg.get("num_params")
            except Exception:
                pass

        total_size = 0
        for f in snapshot.rglob("*"):
            if f.is_file() and f.suffix in (".safetensors", ".bin", ".npz"):
                total_size += f.stat().st_size

        if total_size == 0:
            continue

        models.append({
            "model_id": model_id,
            "size_bytes": total_size,
            "params": params,
        })

    return models


def installed_model_names(cfg: LLMConfig) -> list[str]:
    """Names (HF IDs) of downloaded MLX models (empty list if none found)."""
    try:
        return [m["model_id"] for m in _scan_downloaded_models()]
    except Exception:
        log.warning("could not scan downloaded models", exc_info=True)
        return []


def list_models(cfg: LLMConfig) -> dict:
    """Downloaded models + fit verdicts + a summarization recommendation.

    Returns `{"models": [...], "recommended": str|None, "current": str,
    "total_ram_gb": int}`; on error, `models` is empty and an `error` message
    is added instead.
    """
    total_ram = _total_ram_bytes()
    out: dict = {
        "models": [],
        "recommended": None,
        "current": cfg.model,
        "total_ram_gb": round(total_ram / _GIB),
    }
    try:
        raw = _scan_downloaded_models()
    except Exception as e:
        log.warning("could not scan models: %s", e)
        out["error"] = f"Couldn't scan HuggingFace cache: {e}"
        return out

    default_family = _short_name(cfg.model).split("-")[0].lower() if cfg.model else ""

    best_family: tuple[int, str] | None = None
    best_any: tuple[int, str] | None = None
    for m in raw:
        model_id = m["model_id"]
        size = m["size_bytes"]
        fit = _fit(size, total_ram)
        short = _short_name(model_id)
        is_vision = _is_vision_model(short)
        is_chat = _is_chat_model(short) and not is_vision

        params_str = None
        if m["params"]:
            p = m["params"]
            if p >= 1_000_000_000:
                params_str = f"{p / 1_000_000_000:.1f}B"
            elif p >= 1_000_000:
                params_str = f"{p / 1_000_000:.0f}M"

        out["models"].append({
            "name": model_id,
            "short_name": short,
            "size_gb": round(size / _GIB, 1),
            "params": params_str,
            "fit": fit,
            "chat": is_chat,
            "vision": is_vision,
        })
        if fit == "good" and is_chat:
            if best_any is None or size > best_any[0]:
                best_any = (size, model_id)
            family = short.split("-")[0].lower()
            if default_family and family == default_family:
                if best_family is None or size > best_family[0]:
                    best_family = (size, model_id)

    out["models"].sort(key=lambda m: m["size_gb"], reverse=True)
    pick = best_family or best_any
    out["recommended"] = pick[1] if pick else None
    return out
