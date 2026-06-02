"""SessionWriter — captures every turn in a call and writes a topic-organized
markdown file to the user's Obsidian vault at session end.

In-memory buffer is mirrored to `<memory.session_dir>/<sid>.jsonl` so a crash
mid-session leaves the transcript recoverable. The JSONL is deleted after the
markdown is committed.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from vox_tinker.config import MemoryConfig, ObsidianConfig
from vox_tinker.memory.topic_classifier import UNSORTED, propose_topic

if TYPE_CHECKING:
    from vox_tinker.llm.client import LLMClient

log = logging.getLogger("vox_tinker.memory.writer")


def _iso_local(ts: float) -> str:
    """RFC3339-ish local-time string for frontmatter."""
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


class SessionWriter:
    """One instance per WebSocket session. Cheap to construct; does no IO
    until start() is called. When `obsidian.enabled` is False, all methods
    are no-ops so feature can be toggled at runtime without touching wiring.
    """

    def __init__(
        self,
        session_id: str,
        obsidian: ObsidianConfig,
        memory: MemoryConfig,
    ):
        self.session_id = session_id
        self.obsidian = obsidian
        self.memory = memory

        self.turns: list[dict] = []
        self._started_at: Optional[float] = None
        self._model: Optional[str] = None
        self._voice: Optional[str] = None
        self._persona: Optional[str] = None
        self._jsonl_path: Optional[Path] = None
        self._jsonl_fh = None
        self._finalized = False

    # ---- public API ----

    def start(self, model: str, voice: str, persona: Optional[str] = None) -> None:
        if not self.obsidian.enabled or self._started_at is not None:
            return
        self._started_at = time.time()
        self._model = model
        self._voice = voice
        self._persona = persona
        try:
            session_dir = self.memory.session_dir.expanduser()
            session_dir.mkdir(parents=True, exist_ok=True)
            self._jsonl_path = session_dir / f"{self.session_id}.jsonl"
            self._jsonl_fh = open(self._jsonl_path, "a", encoding="utf-8")
            self._jsonl_fh.write(
                json.dumps({
                    "event": "start",
                    "session_id": self.session_id,
                    "ts": self._started_at,
                    "model": model,
                    "voice": voice,
                    "persona": persona,
                }) + "\n"
            )
            self._jsonl_fh.flush()
        except Exception:
            log.exception("session writer start failed; persistence disabled for this call")
            self._jsonl_fh = None

    def append_turn(self, role: str, text: str, ts: Optional[float] = None) -> None:
        if not self.obsidian.enabled or self._started_at is None:
            return
        if not text:
            return
        record = {
            "role": role,
            "text": text,
            "ts": ts if ts is not None else time.time(),
        }
        self.turns.append(record)
        if self._jsonl_fh is not None:
            try:
                self._jsonl_fh.write(json.dumps({"event": "turn", **record}) + "\n")
                self._jsonl_fh.flush()
            except Exception:
                log.exception("jsonl mirror write failed")

    def finalize(self, llm: "LLMClient") -> Optional[Path]:
        """Write the markdown file and clean up the JSONL. Safe to call once.

        Runs from a background thread so it can use blocking Ollama calls and
        sync file IO without holding the asyncio loop.
        """
        if self._finalized:
            return None
        self._finalized = True
        if not self.obsidian.enabled or self._started_at is None:
            return None

        # Close the JSONL handle before anything else so the file is flushed.
        if self._jsonl_fh is not None:
            try:
                self._jsonl_fh.close()
            except Exception:
                pass
            self._jsonl_fh = None

        if not self.turns:
            # Nothing to write; drop the empty JSONL.
            self._cleanup_jsonl()
            return None

        # Topic classification — fire only on sessions with real content.
        summary = self._summary_for_topic()
        topic = (
            propose_topic(llm, summary, model_override=self.obsidian.topic_model)
            if len(self.turns) >= 2
            else UNSORTED
        )

        # Write the markdown.
        ended_at = time.time()
        path = self._compose_path(topic)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._render_markdown(topic, ended_at), encoding="utf-8")
        except Exception:
            log.exception("failed to write obsidian markdown to %s", path)
            return None

        self._cleanup_jsonl()
        return path

    # ---- internals ----

    def _summary_for_topic(self) -> str:
        """Compress the transcript into a few hundred tokens for the topic
        classifier. Just keeps the first 30 turns and trims long ones — the
        classifier only needs the gist."""
        lines = []
        for t in self.turns[:30]:
            text = t["text"]
            if len(text) > 500:
                text = text[:500] + "…"
            lines.append(f"{t['role'].upper()}: {text}")
        return "\n".join(lines)

    def _compose_path(self, topic: str) -> Path:
        vault_root = self.obsidian.vault_root.expanduser()
        topic_dir = vault_root / topic
        date_str = datetime.fromtimestamp(self._started_at or time.time()).strftime("%Y-%m-%d")
        fname = f"{date_str}--{self.session_id[:6]}.md"
        return topic_dir / fname

    def _render_markdown(self, topic: str, ended_at: float) -> str:
        started = self._started_at or ended_at
        duration = int(ended_at - started)
        # Header date matches frontmatter `started` for cross-reference.
        date_human = datetime.fromtimestamp(started).strftime("%Y-%m-%d %H:%M")
        frontmatter = (
            "---\n"
            f"session_id: {self.session_id}\n"
            f"started: {_iso_local(started)}\n"
            f"ended: {_iso_local(ended_at)}\n"
            f"duration_sec: {duration}\n"
            f"model: {self._model or ''}\n"
            f"voice: {self._voice or ''}\n"
            f"persona: {self._persona or ''}\n"
            f"topic: {topic}\n"
            f"turn_count: {len(self.turns)}\n"
            "---\n\n"
        )
        body_lines = [f"# Conversation — {date_human}", ""]
        for t in self.turns:
            label = "User" if t["role"] == "user" else "Assistant"
            body_lines.append(f"**{label}:** {t['text']}")
            body_lines.append("")
        return frontmatter + "\n".join(body_lines)

    def _cleanup_jsonl(self) -> None:
        if self._jsonl_path is not None and self._jsonl_path.exists():
            try:
                self._jsonl_path.unlink()
            except Exception:
                log.exception("could not delete crash-recovery jsonl %s", self._jsonl_path)
