import threading
from collections import deque
from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from local_tts.state import AppState, InputMode, Phase

PHASE_LABELS = {
    Phase.IDLE: ("dim", "Ready"),
    Phase.LISTENING: ("cyan", "Listening..."),
    Phase.TRANSCRIBING: ("yellow", "Transcribing..."),
    Phase.THINKING: ("magenta", "Thinking..."),
    Phase.SPEAKING: ("green", "Speaking..."),
}


class Display:
    """Rich live display: rolling conversation history + current phase indicator."""

    def __init__(self, state: AppState, max_messages: int = 20):
        self.state = state
        self.console = Console()
        self.messages: deque[tuple[str, str]] = deque(maxlen=max_messages)
        self._current_ai: str = ""
        self._lock = threading.Lock()
        self._live: Optional[Live] = None
        self._spinner = Spinner("dots", text="")

    def start(self):
        self._live = Live(
            self._render(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.start()

    def stop(self):
        if self._live is not None:
            self._live.stop()
            self._live = None

    def add_user_message(self, text: str):
        with self._lock:
            self.messages.append(("user", text))
            self._current_ai = ""
        self._refresh()

    def start_ai_message(self):
        with self._lock:
            self._current_ai = ""
        self._refresh()

    def append_ai_chunk(self, chunk: str):
        with self._lock:
            if self._current_ai:
                self._current_ai += " " + chunk
            else:
                self._current_ai = chunk
        self._refresh()

    def finalize_ai_message(self):
        with self._lock:
            if self._current_ai:
                self.messages.append(("ai", self._current_ai))
                self._current_ai = ""
        self._refresh()

    def notify(self, text: str):
        """Show a transient system note."""
        with self._lock:
            self.messages.append(("system", text))
        self._refresh()

    def _refresh(self):
        if self._live is not None:
            self._live.update(self._render())

    def _render(self) -> Group:
        items = []
        with self._lock:
            for role, text in self.messages:
                items.append(self._panel_for(role, text))
            if self._current_ai:
                items.append(self._panel_for("ai", self._current_ai, streaming=True))

        phase = self.state.get_phase()
        mode = self.state.get_mode()
        color, label = PHASE_LABELS[phase]

        mode_label = "VOICE" if mode == InputMode.VOICE else "TEXT"
        mode_color = "cyan" if mode == InputMode.VOICE else "yellow"
        status_text = Text()
        status_text.append("● ", style=color)
        status_text.append(label, style=f"bold {color}")
        status_text.append("   ")
        status_text.append(f"[{mode_label}]", style=f"bold {mode_color}")
        status_text.append("   F4: toggle mode  Ctrl+C: quit", style="dim")

        items.append(Panel(status_text, border_style=color, padding=(0, 1)))
        return Group(*items)

    @staticmethod
    def _panel_for(role: str, text: str, streaming: bool = False) -> Panel:
        if role == "user":
            return Panel(
                Text(text, style="white"),
                title="[bold cyan]you[/]",
                title_align="left",
                border_style="cyan",
                padding=(0, 1),
            )
        if role == "ai":
            suffix = " ▌" if streaming else ""
            return Panel(
                Text(text + suffix, style="white"),
                title="[bold green]assistant[/]",
                title_align="left",
                border_style="green",
                padding=(0, 1),
            )
        return Panel(
            Text(text, style="dim italic"),
            border_style="dim",
            padding=(0, 1),
        )
