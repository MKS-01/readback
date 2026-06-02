"""Tool protocol. Each tool is a small object with a name, an Ollama-style
JSON schema, and a `run(args)` method that returns a plain string the LLM
can fold into its response."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    name: str
    # JSON schema in the Ollama tools=[...] format. Top-level shape:
    #   {"type": "function", "function": {"name": ..., "description": ...,
    #    "parameters": {"type": "object", "properties": {...}, "required": [...]}}}
    schema: dict[str, Any]

    def run(self, args: dict[str, Any]) -> str: ...
