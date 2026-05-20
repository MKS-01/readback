"""Function-calling tools the assistant can invoke during a turn.

Off by default — must be enabled via `tools.enabled: true` in config.yaml
or via the settings panel toggle (Phase 4 WS message).
"""

from local_tts.tools.base import Tool
from local_tts.tools.clock import ClockTool
from local_tts.tools.registry import ToolRegistry
from local_tts.tools.web_search import WebSearchTool

__all__ = ["Tool", "ToolRegistry", "ClockTool", "WebSearchTool"]
