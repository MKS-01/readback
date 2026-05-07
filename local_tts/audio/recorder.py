import queue
import threading
from typing import Optional

import numpy as np
import sounddevice as sd
import webrtcvad

from local_tts.config import AudioConfig, InputConfig, VADConfig
from local_tts.state import AppState, Phase

FRAME_DURATION_MS = 30
MIN_SPEECH_FRAMES_TO_START = 10        # ~300ms of speech to begin utterance


class Recorder:
    def __init__(
        self,
        audio_cfg: AudioConfig,
        vad_cfg: VADConfig,
        input_cfg: InputConfig,
        state: AppState,
        transcription_queue: queue.Queue,
    ):
        self.cfg = audio_cfg
        self.vad_cfg = vad_cfg
        self.input_cfg = input_cfg
        self.state = state
        self.out_queue = transcription_queue

        self.sample_rate = audio_cfg.sample_rate
        self.frame_samples = int(self.sample_rate * FRAME_DURATION_MS / 1000)  # 480 @ 16kHz
        self.silence_frames_threshold = int(vad_cfg.silence_threshold_ms / FRAME_DURATION_MS)
        self.interrupt_frames_threshold = int(vad_cfg.interrupt_speech_ms / FRAME_DURATION_MS)
        self.min_recording_frames = max(1, int(input_cfg.min_recording_ms / FRAME_DURATION_MS))

        self.vad = webrtcvad.Vad(vad_cfg.aggressiveness)
        self._raw_queue: queue.Queue = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._thread: Optional[threading.Thread] = None
        self._paused = threading.Event()
        self._ptt_active = threading.Event()

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass  # ignore overflow warnings
        mono = indata[:, 0]
        rms = float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0
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

    # PTT control surface — wired up by the keyboard listener in app.py.

    def ptt_press(self):
        self._ptt_active.set()
        # If AI is speaking, the user pressing PTT means "stop and listen to me".
        if self.state.get_phase() == Phase.SPEAKING:
            self.state.request_interrupt()

    def ptt_release(self):
        self._ptt_active.clear()

    def _vad_loop(self):
        if self.input_cfg.mode == "ptt":
            self._ptt_loop()
        else:
            self._vad_continuous_loop()

    # ---- Push-to-talk loop -------------------------------------------------

    def _ptt_loop(self):
        speech_frames: list[bytes] = []
        recording = False

        while self.state.is_running():
            try:
                frame, _rms = self._raw_queue.get(timeout=0.1)
            except queue.Empty:
                # No audio frame; still want to react to PTT release promptly
                if recording and not self._ptt_active.is_set():
                    self._finalize_ptt(speech_frames)
                    speech_frames = []
                    recording = False
                continue

            if self._paused.is_set():
                speech_frames.clear()
                recording = False
                continue

            ptt_on = self._ptt_active.is_set()

            if ptt_on and not recording:
                # Started holding PTT
                recording = True
                speech_frames = [frame]
                self.state.set_phase(Phase.LISTENING)
            elif ptt_on and recording:
                speech_frames.append(frame)
            elif (not ptt_on) and recording:
                # Released PTT — finalize
                self._finalize_ptt(speech_frames)
                speech_frames = []
                recording = False

    def _finalize_ptt(self, frames: list[bytes]):
        if len(frames) >= self.min_recording_frames:
            audio = self._frames_to_array(frames)
            self.out_queue.put(audio)
        if self.state.get_phase() == Phase.LISTENING:
            self.state.set_phase(Phase.IDLE)

    # ---- Continuous VAD loop (legacy mode) ---------------------------------

    def _vad_continuous_loop(self):
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
            if phase == Phase.SPEAKING:
                if self.vad_cfg.allow_interrupt and is_speech and rms >= self.vad_cfg.interrupt_rms_threshold:
                    interrupt_speech_count += 1
                    if interrupt_speech_count >= self.interrupt_frames_threshold:
                        self.state.request_interrupt()
                        interrupt_speech_count = 0
                else:
                    interrupt_speech_count = 0
                continue
            else:
                interrupt_speech_count = 0

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
