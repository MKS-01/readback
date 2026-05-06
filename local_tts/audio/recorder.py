import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
import webrtcvad

from local_tts.config import AudioConfig, VADConfig
from local_tts.state import AppState, Phase

FRAME_DURATION_MS = 30
MIN_SPEECH_FRAMES_TO_START = 10        # ~300ms of speech to begin utterance


class Recorder:
    def __init__(
        self,
        audio_cfg: AudioConfig,
        vad_cfg: VADConfig,
        state: AppState,
        transcription_queue: queue.Queue,
    ):
        self.cfg = audio_cfg
        self.vad_cfg = vad_cfg
        self.state = state
        self.out_queue = transcription_queue

        self.sample_rate = audio_cfg.sample_rate
        self.frame_samples = int(self.sample_rate * FRAME_DURATION_MS / 1000)  # 480 @ 16kHz
        self.silence_frames_threshold = int(vad_cfg.silence_threshold_ms / FRAME_DURATION_MS)
        self.interrupt_frames_threshold = int(vad_cfg.interrupt_speech_ms / FRAME_DURATION_MS)

        self.vad = webrtcvad.Vad(vad_cfg.aggressiveness)
        self._raw_queue: queue.Queue[bytes] = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._paused = threading.Event()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass  # ignore overflow warnings
        mono = indata[:, 0]
        # Compute RMS (loudness) for interrupt gating against speaker bleed
        rms = float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0
        # Convert float32 [-1, 1] to int16 PCM bytes for webrtcvad
        pcm = (mono * 32767).astype(np.int16).tobytes()
        self._raw_queue.put((pcm, rms))

    def start(self):
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            blocksize=self.frame_samples,
            device=self.cfg.input_device,
            callback=self._audio_callback,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._vad_loop, daemon=True, name="recorder")
        self._thread.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    def _vad_loop(self):
        speech_frames: list[bytes] = []
        in_speech = False
        speech_count = 0
        silence_count = 0
        interrupt_speech_count = 0

        while self.state.is_running():
            try:
                frame, rms = self._raw_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._paused.is_set():
                speech_frames.clear()
                in_speech = False
                speech_count = 0
                silence_count = 0
                interrupt_speech_count = 0
                continue

            is_speech = self.vad.is_speech(frame, self.sample_rate)
            phase = self.state.get_phase()

            # Interrupt detection: sustained AND loud speech while AI is SPEAKING.
            # Loudness gate filters out the AI's own voice bleeding from speaker into mic.
            if phase == Phase.SPEAKING:
                if self.vad_cfg.allow_interrupt and is_speech and rms >= self.vad_cfg.interrupt_rms_threshold:
                    interrupt_speech_count += 1
                    if interrupt_speech_count >= self.interrupt_frames_threshold:
                        self.state.request_interrupt()
                        interrupt_speech_count = 0
                else:
                    interrupt_speech_count = 0
                # Don't accumulate utterance audio while AI is speaking
                continue
            else:
                interrupt_speech_count = 0

            # Standard utterance detection (only when not in SPEAKING phase)
            if is_speech:
                speech_count += 1
                silence_count = 0
                if not in_speech and speech_count >= MIN_SPEECH_FRAMES_TO_START:
                    in_speech = True
                    self.state.set_phase(Phase.LISTENING)
                if in_speech:
                    speech_frames.append(frame)
            else:
                speech_count = 0
                if in_speech:
                    silence_count += 1
                    speech_frames.append(frame)
                    if silence_count >= self.silence_frames_threshold:
                        # Finalize utterance
                        audio = self._frames_to_array(speech_frames)
                        speech_frames.clear()
                        in_speech = False
                        silence_count = 0
                        self.out_queue.put(audio)

    @staticmethod
    def _frames_to_array(frames: list[bytes]) -> np.ndarray:
        pcm = b"".join(frames)
        arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32767.0
        return arr
