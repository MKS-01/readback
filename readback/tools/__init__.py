"""Function-calling tools the assistant can invoke during a turn.

Off by default — must be enabled via `tools.enabled: true` in config.yaml
or via the settings panel toggle (Phase 4 WS message).
"""

from readback.tools.base import Tool
from readback.tools.clock import ClockTool
from readback.tools.registry import ToolRegistry
from readback.tools.web_search import WebSearchTool

__all__ = ["Tool", "ToolRegistry", "ClockTool", "WebSearchTool"]
