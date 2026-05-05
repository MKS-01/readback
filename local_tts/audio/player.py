import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from local_tts.config import AudioConfig
from local_tts.state import AppState

CHUNK_FRAMES = 2048  # ~85ms @ 24kHz — small enough for snappy interrupt response


class Player:
    """Plays numpy audio arrays from a queue. Checks interrupt_event between chunks."""

    def __init__(
        self,
        audio_cfg: AudioConfig,
        state: AppState,
        playback_queue: queue.Queue,
    ):
        self.cfg = audio_cfg
        self.state = state
        self.in_queue = playback_queue
        self.sample_rate = audio_cfg.output_sample_rate
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="player")
        self._thread.start()

    def _run(self):
        while self.state.is_running():
            try:
                audio = self.in_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if audio is None:
                continue
            self._play(audio)

    def _play(self, audio: np.ndarray):
        if audio.ndim > 1:
            audio = audio.squeeze()
        audio = audio.astype(np.float32)
        # Normalize if values exceed [-1, 1]
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak > 1.0:
            audio = audio / peak

        try:
            with sd.OutputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                device=self.cfg.output_device,
            ) as stream:
                idx = 0
                while idx < len(audio):
                    if self.state.is_interrupted() or not self.state.is_running():
                        break
                    end = min(idx + CHUNK_FRAMES, len(audio))
                    stream.write(audio[idx:end])
                    idx = end
        except Exception:
            pass

    def drain(self):
        """Empty the playback queue (used after interrupt)."""
        try:
            while True:
                self.in_queue.get_nowait()
        except queue.Empty:
            pass
