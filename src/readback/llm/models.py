"""Local Ollama model discovery for the summary LLM.

Lists the models installed in Ollama (`/api/tags` via `Client.list()`) and
attaches a RAM-fit verdict per model so a client can warn before switching to
something that would swap/thrash, plus a recommendation for summarization.

Fit heuristic (deliberately simple): a model needs roughly its on-disk size in
unified memory for weights, plus KV cache and runtime overhead — estimated as
`size * 1.2 + 1 GiB`. CSM-1B, the OS and apps also live in the same unified
memory, so a model is only a comfortable fit well below total RAM:

    good   need <= 50% of total RAM
    tight  need <= 75% of total RAM
    no     anything above
"""
from __future__ import annotations

import logging
import os
import subprocess

import ollama

from readback.config import OllamaConfig

log = logging.getLogger("readback.llm")

_GIB = 1024 ** 3

# Models that can't summarize at all (embedding / reranker families).
_NON_CHAT_MARKERS = ("embed", "bge", "minilm", "rerank")


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


# Preferred OCR models in priority order — smallest/fastest first, Qwen excels at text extraction.
_VISION_PREF = ["qwen3.5:4b", "gemma4:12b", "gemma4:e4b", "gemma4:26b"]


def pick_vision_model(cfg: OllamaConfig) -> str | None:
    """Return the name of the best available vision-capable Ollama model, or None.

    Queries each installed model's capabilities via the Ollama API. Preference
    order: qwen3.5:4b → gemma4:12b → gemma4:e4b → gemma4:26b → first vision
    model found by size (smallest first).
    """
    try:
        client = ollama.Client(host=cfg.host)
        resp = client.list()
        installed = {m.model: m for m in resp.models if m.model}
    except Exception:
        log.warning("could not list Ollama models for vision selection", exc_info=True)
        return None

    # Check preferred models first
    for name in _VISION_PREF:
        if name not in installed:
            continue
        try:
            info = client.show(name)
            if "vision" in (getattr(info, "capabilities", None) or []):
                return name
        except Exception:
            pass

    # Fall back: any vision-capable model, smallest first
    candidates: list[tuple[int, str]] = []
    for name, m in installed.items():
        if name in _VISION_PREF:
            continue  # already checked
        try:
            info = client.show(name)
            if "vision" in (getattr(info, "capabilities", None) or []):
                candidates.append((int(m.size or 0), name))
        except Exception:
            pass
    if candidates:
        return min(candidates)[1]
    return None


def installed_model_names(cfg: OllamaConfig) -> list[str]:
    """Names of the models installed in Ollama (empty list if unreachable)."""
    try:
        resp = ollama.Client(host=cfg.host).list()
        return [m.model for m in resp.models if m.model]
    except Exception:
        log.warning("could not list Ollama models", exc_info=True)
        return []


def list_models(cfg: OllamaConfig) -> dict:
    """Installed models + fit verdicts + a summarization recommendation.

    Returns `{"models": [...], "recommended": str|None, "current": str,
    "total_ram_gb": int}`; on an unreachable Ollama, `models` is empty and an
    `error` message is added instead.
    """
    total_ram = _total_ram_bytes()
    out: dict = {
        "models": [],
        "recommended": None,
        "current": cfg.model,
        "total_ram_gb": round(total_ram / _GIB),
    }
    try:
        resp = ollama.Client(host=cfg.host).list()
    except Exception as e:
        log.warning("could not list Ollama models: %s", e)
        out["error"] = f"Couldn't reach Ollama at {cfg.host}: {e}"
        return out

    # Fetch capabilities for all models in one pass (one show() call per model).
    capabilities: dict[str, list[str]] = {}
    for m in resp.models:
        if not m.model:
            continue
        try:
            info = ollama.Client(host=cfg.host).show(m.model)
            capabilities[m.model] = list(getattr(info, "capabilities", None) or [])
        except Exception:
            capabilities[m.model] = []

    # Extract the default model's family prefix (e.g. "qwen3.5" from "qwen3.5:9b")
    default_family = cfg.model.split(":")[0] if ":" in cfg.model else ""

    best_family: tuple[int, str] | None = None  # largest good-fit in the default's family
    best_any: tuple[int, str] | None = None      # largest good-fit overall (fallback)
    for m in resp.models:
        name = m.model or ""
        if not name:
            continue
        size = int(m.size or 0)
        details = m.details
        fit = _fit(size, total_ram)
        caps = capabilities.get(name, [])
        out["models"].append({
            "name": name,
            "size_gb": round(size / _GIB, 1),
            "params": (details.parameter_size if details else None) or None,
            "quant": (details.quantization_level if details else None) or None,
            "fit": fit,
            "chat": _is_chat_model(name),
            "vision": "vision" in caps,
        })
        if fit == "good" and _is_chat_model(name):
            if best_any is None or size > best_any[0]:
                best_any = (size, name)
            if default_family and name.startswith(default_family + ":"):
                if best_family is None or size > best_family[0]:
                    best_family = (size, name)

    out["models"].sort(key=lambda m: m["size_gb"], reverse=True)
    pick = best_family or best_any
    out["recommended"] = pick[1] if pick else None
    return out
