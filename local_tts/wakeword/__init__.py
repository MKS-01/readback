"""openWakeWord integration. Always-on listening mode for the web UI."""

from local_tts.wakeword.detector import WakeWordDetector, WakeWordUnavailable

__all__ = ["WakeWordDetector", "WakeWordUnavailable"]
