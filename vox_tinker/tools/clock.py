"""Trivial sample tool: returns the local time. Useful smoke test for the
tool-call streaming path before pulling in network-dependent tools."""
from __future__ import annotations

from datetime import datetime
from typing import Any


class ClockTool:
    name = "clock"
    schema = {
        "type": "function",
        "function": {
            "name": "clock",
            "description": (
                "Get the current local date and time. Use this when the user "
                "asks what time it is, what day it is, or anything similar."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }

    def run(self, args: dict[str, Any]) -> str:
        now = datetime.now().astimezone()
        return now.strftime("%A, %B %d, %Y at %I:%M %p %Z").strip()
