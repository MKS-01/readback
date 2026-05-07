import queue
import threading
import time
from typing import Optional

import numpy as np

from local_tts.audio.player import Player
from local_tts.audio.recorder import Recorder
from local_tts.config import Config
from local_tts.llm.client import LLMClient
from local_tts.state import AppState, InputMode, Phase
from local_tts.stt.transcriber import Transcriber
from local_tts.tts.synthesizer import Synthesizer
from local_tts.ui.display import Display


class ConversationApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.state = AppState()
        self.state.set_mode(
            InputMode.VOICE if cfg.ui.default_mode == "voice" else InputMode.TEXT
        )

        # Queues
        self.transcription_queue: queue.Queue = queue.Queue()
        self.text_input_queue: queue.Queue = queue.Queue()
        self.playback_queue: queue.Queue = queue.Queue()

        # Components
        self.display = Display(self.state, cfg.input)
        self.transcriber = Transcriber(cfg.whisper)
        self.llm = LLMClient(cfg.ollama)
        self.synthesizer = Synthesizer(cfg.kokoro)
        self.recorder = Recorder(
            cfg.audio, cfg.vad, cfg.input, self.state, self.transcription_queue
        )
        self.player = Player(cfg.audio, self.state, self.playback_queue)

        self._pipeline_thread: Optional[threading.Thread] = None
        self._text_thread: Optional[threading.Thread] = None
        self._key_listener = None

    # ---------- lifecycle ----------

    def start(self):
        self.display.start()
        try:
            self.display.notify("Loading models — this may take a moment on first run...")
            self.transcriber.load()
            self.synthesizer.load()
            self.player.sample_rate = self.synthesizer.sample_rate
            self.player.cfg.output_sample_rate = self.synthesizer.sample_rate
            self.display.notify(
                f"Ready. Device: {self.synthesizer.device}. Ollama model: {self.cfg.ollama.model}"
            )
            if self.cfg.input.mode == "ptt":
                self.display.notify(
                    f"PTT key: {self.cfg.input.ptt_key}. If it doesn't respond, grant "
                    "Accessibility permission to your terminal app in System Settings → "
                    "Privacy & Security → Accessibility."
                )

            self.player.start()
            self.recorder.start()
            self._apply_mode()

            self._pipeline_thread = threading.Thread(
                target=self._pipeline_loop, daemon=True, name="pipeline"
            )
            self._pipeline_thread.start()

            self._text_thread = threading.Thread(
                target=self._text_input_loop, daemon=True, name="text-input"
            )
            self._text_thread.start()

            self._start_key_listener()

            # Main thread: wait for shutdown
            while self.state.is_running():
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        self.state.shutdown()
        try:
            self.recorder.stop()
        except Exception:
            pass
        if self._key_listener is not None:
            try:
                self._key_listener.stop()
            except Exception:
                pass
        self.display.stop()

    # ---------- mode switching ----------

    def _apply_mode(self):
        if self.state.get_mode() == InputMode.VOICE:
            self.recorder.resume()
        else:
            self.recorder.pause()

    def toggle_mode(self):
        new_mode = (
            InputMode.TEXT
            if self.state.get_mode() == InputMode.VOICE
            else InputMode.VOICE
        )
        self.state.set_mode(new_mode)
        self._apply_mode()
        self.display.notify(f"Switched to {new_mode.value.upper()} mode")

    def _start_key_listener(self):
        try:
            from pynput import keyboard
        except Exception:
            return

        toggle_key = self.cfg.ui.toggle_key.lower()
        ptt_key = self.cfg.input.ptt_key.lower()
        ptt_enabled = self.cfg.input.mode == "ptt"

        def matches(key, name: str) -> bool:
            k = (getattr(key, "name", None) or getattr(key, "char", None) or "")
            return k.lower() == name.lower()

        def on_press(key):
            try:
                if matches(key, toggle_key):
                    self.toggle_mode()
                    return
                if (
                    ptt_enabled
                    and self.state.get_mode() == InputMode.VOICE
                    and matches(key, ptt_key)
                ):
                    self.recorder.ptt_press()
            except Exception:
                pass

        def on_release(key):
            try:
                if (
                    ptt_enabled
                    and self.state.get_mode() == InputMode.VOICE
                    and matches(key, ptt_key)
                ):
                    self.recorder.ptt_release()
            except Exception:
                pass

        self._key_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._key_listener.daemon = True
        self._key_listener.start()

    # ---------- text-input loop ----------

    def _text_input_loop(self):
        """Read terminal input when in TEXT mode and feed into the pipeline."""
        while self.state.is_running():
            if self.state.get_mode() != InputMode.TEXT:
                time.sleep(0.2)
                continue
            if self.state.get_phase() not in (Phase.IDLE, Phase.LISTENING):
                time.sleep(0.1)
                continue
            try:
                # Note: input() is blocking; that's fine — text mode is sequential
                user_text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.state.shutdown()
                return
            if not user_text:
                continue
            if user_text.lower() in ("/quit", "/exit"):
                self.state.shutdown()
                return
            if user_text.lower() == "/voice":
                self.toggle_mode()
                continue
            self.text_input_queue.put(user_text)

    # ---------- pipeline ----------

    def _get_next_input(self) -> Optional[tuple[str, np.ndarray | None]]:
        """Block until either a transcription audio buffer or a typed text arrives.
        Returns ("voice", audio_array) or ("text", None) with text passed via queue.
        """
        while self.state.is_running():
            try:
                audio = self.transcription_queue.get(timeout=0.1)
                return ("voice", audio)
            except queue.Empty:
                pass
            try:
                text = self.text_input_queue.get_nowait()
                return ("text", text)  # type: ignore
            except queue.Empty:
                pass
        return None

    def _pipeline_loop(self):
        while self.state.is_running():
            item = self._get_next_input()
            if item is None:
                return
            kind, payload = item

            if kind == "voice":
                self.state.set_phase(Phase.TRANSCRIBING)
                user_text = self.transcriber.transcribe(
                    payload, sample_rate=self.cfg.audio.sample_rate
                )
            else:
                user_text = payload

            user_text = (user_text or "").strip()
            if not user_text:
                self.state.set_phase(Phase.IDLE)
                continue

            self.display.add_user_message(user_text)
            self.state.add_turn("user", user_text, max_turns=self.cfg.ui.history_turns)

            self.state.clear_interrupt()
            self.state.set_phase(Phase.THINKING)
            self.display.start_ai_message()

            full_response = []
            first_sentence = True
            for sentence in self.llm.stream_response(self.state.get_history()):
                if self.state.is_interrupted():
                    break
                full_response.append(sentence)
                self.display.append_ai_chunk(sentence)

                # Synthesize and queue audio
                if first_sentence:
                    self.state.set_phase(Phase.SPEAKING)
                    first_sentence = False
                try:
                    audio = self.synthesizer.synthesize(sentence)
                    if audio.size > 0 and not self.state.is_interrupted():
                        self.playback_queue.put(audio)
                except Exception as e:
                    self.display.notify(f"TTS error: {e}")

            # Wait for playback to drain (or interrupt)
            self._wait_for_playback_done()

            if full_response:
                self.display.finalize_ai_message()
                self.state.add_turn(
                    "assistant",
                    " ".join(full_response),
                    max_turns=self.cfg.ui.history_turns,
                )

            if self.state.is_interrupted():
                self.player.drain()
                self.state.clear_interrupt()
                self.display.notify("Interrupted")

            self.state.set_phase(Phase.IDLE)

    def _wait_for_playback_done(self):
        """Block until playback queue is empty AND no chunk currently playing."""
        while self.state.is_running():
            if self.state.is_interrupted():
                return
            if self.playback_queue.empty():
                # Give a short grace period for the last chunk to finish playing
                time.sleep(0.2)
                if self.playback_queue.empty():
                    return
            time.sleep(0.1)
