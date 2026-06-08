"""ToolRegistry — owns the set of available tools, filters them by config
allowlist, and dispatches `run(name, args)` calls.

The registry is held by `LLMClient` so that streaming tool_calls can be
intercepted and resolved in the same call site that builds the chat request.
"""
from __future__ import annotations

import logging
from typing import Any

from readback.config import ToolsConfig
from readback.tools.base import Tool

log = logging.getLogger("readback.tools.registry")


class ToolRegistry:
    def __init__(self, cfg: ToolsConfig):
        self.cfg = cfg
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.enabled)

    def schemas_for_active(self) -> list[dict[str, Any]]:
        """JSON schemas for tools that are both registered AND in the allowlist.
        Returns [] when `cfg.enabled` is False so the chat call sees no tools."""
        if not self.cfg.enabled:
            return []
        out: list[dict[str, Any]] = []
        for name, tool in self._tools.items():
            if name in self.cfg.allowed:
                out.append(tool.schema)
        return out

    def run(self, name: str, args: dict[str, Any]) -> str:
        """Dispatch and surface errors as text so the LLM can recover gracefully.
        Never raises — a tool failure becomes a string the model can read."""
        tool = self._tools.get(name)
        if tool is None:
            return f"[tool error] unknown tool {name!r}"
        if name not in self.cfg.allowed:
            return f"[tool error] tool {name!r} is disabled in config"
        try:
            return tool.run(args or {})
        except Exception as e:
            log.exception("tool %s raised", name)
            return f"[tool error] {name}: {e}"
