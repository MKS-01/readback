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

    best: tuple[int, str] | None = None   # (size_bytes, name) of best good fit
    for m in resp.models:
        name = m.model or ""
        if not name:
            continue
        size = int(m.size or 0)
        details = m.details
        fit = _fit(size, total_ram)
        out["models"].append({
            "name": name,
            "size_gb": round(size / _GIB, 1),
            "params": (details.parameter_size if details else None) or None,
            "quant": (details.quantization_level if details else None) or None,
            "fit": fit,
            "chat": _is_chat_model(name),
        })
        # Recommend the largest comfortably-fitting chat model: best summary
        # quality without crowding CSM + the rest of the system.
        if fit == "good" and _is_chat_model(name):
            if best is None or size > best[0]:
                best = (size, name)

    out["models"].sort(key=lambda m: m["size_gb"], reverse=True)
    out["recommended"] = best[1] if best else None
    return out
