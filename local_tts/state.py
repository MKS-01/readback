import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Phase(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    THINKING = "thinking"
    SPEAKING = "speaking"


class InputMode(Enum):
    VOICE = "voice"
    TEXT = "text"


@dataclass
class AppState:
    mode: InputMode = InputMode.VOICE
    phase: Phase = Phase.IDLE
    interrupt_event: threading.Event = field(default_factory=threading.Event)
    stop_event: threading.Event = field(default_factory=threading.Event)
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set_phase(self, phase: Phase) -> None:
        with self._lock:
            self.phase = phase

    def get_phase(self) -> Phase:
        with self._lock:
            return self.phase

    def set_mode(self, mode: InputMode) -> None:
        with self._lock:
            self.mode = mode

    def get_mode(self) -> InputMode:
        with self._lock:
            return self.mode

    def add_turn(self, role: str, content: str, max_turns: int = 10) -> None:
        with self._lock:
            self.conversation_history.append({"role": role, "content": content})
            # Keep last N turns (each turn is one message; pairs = 2 messages)
            if len(self.conversation_history) > max_turns * 2:
                self.conversation_history = self.conversation_history[-max_turns * 2:]

    def get_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.conversation_history)

    def request_interrupt(self) -> None:
        self.interrupt_event.set()

    def clear_interrupt(self) -> None:
        self.interrupt_event.clear()

    def is_interrupted(self) -> bool:
        return self.interrupt_event.is_set()

    def shutdown(self) -> None:
        self.stop_event.set()

    def is_running(self) -> bool:
        return not self.stop_event.is_set()
