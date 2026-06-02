// Audio engine: mic capture (AudioWorklet, 16k Int16 → WS) + playback queue
// (Float32 @ 24k → gapless scheduled buffers). Singleton inside the React app;
// hooks call .start()/.stop() but never own the underlying nodes.

const WORKLET_URL = "/static/dist/recorder.worklet.js";

export interface AudioEngineCallbacks {
  onMicFrame: (buf: ArrayBuffer) => void;
}

export class AudioEngine {
  // Capture-side state
  private micCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private muted = false;

  // Playback-side state
  private outCtx: AudioContext | null = null;
  private outNode: AudioNode | null = null;
  private outAudioEl: HTMLAudioElement | null = null;
  private playbackTime = 0;
  private scheduledNodes: AudioBufferSourceNode[] = [];
  private analyser: AnalyserNode | null = null;
  private outSampleRate = 24000;
  // Jitter buffer. TTS is synthesized one sentence at a time and the next
  // sentence often isn't ready the instant the current finishes (slow engines
  // like the cloned Base model, or LLM stalls between sentences). Starting
  // playback from a drained queue at `currentTime` leaves zero cushion, so any
  // stall underruns into an audible gap. When (re)filling a drained queue we
  // schedule the first buffer this far in the future to absorb that jitter —
  // small enough to stay snappy, large enough to smooth typical boundaries.
  private readonly LEAD_SEC = 0.28;
  // Fired when the last queued TTS buffer finishes playing (queue drains
  // naturally, not via stopAllPlayback). The server keeps the mic closed until
  // this round-trips so the speaker tail can't bleed back in as a new utterance.
  private onDrained: (() => void) | null = null;

  private cbs: AudioEngineCallbacks;

  constructor(cbs: AudioEngineCallbacks) {
    this.cbs = cbs;
  }

  // ---- mic capture ----

  async startMic(deviceId: string | null): Promise<void> {
    const audioConstraints: MediaTrackConstraints = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      channelCount: 1,
    };
    if (deviceId) audioConstraints.deviceId = { exact: deviceId };

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: audioConstraints,
      video: false,
    });
    this.micStream = stream;

    const micCtx = new (window.AudioContext ||
      (window as any).webkitAudioContext)();
    this.micCtx = micCtx;

    await micCtx.audioWorklet.addModule(WORKLET_URL);

    const source = micCtx.createMediaStreamSource(stream);
    this.micSource = source;

    const node = new AudioWorkletNode(micCtx, "recorder-processor", {
      processorOptions: { targetRate: 16000 },
    });
    node.port.onmessage = (ev) => {
      if (this.muted) return;
      this.cbs.onMicFrame(ev.data as ArrayBuffer);
    };
    source.connect(node);
    // Intentionally not connected to ctx.destination — no audible monitoring.
    this.workletNode = node;
  }

  stopMic(): void {
    try {
      this.workletNode?.disconnect();
    } catch {
      /* */
    }
    try {
      this.micSource?.disconnect();
    } catch {
      /* */
    }
    this.micStream?.getTracks().forEach((t) => t.stop());
    try {
      this.micCtx?.close();
    } catch {
      /* */
    }
    this.workletNode = null;
    this.micSource = null;
    this.micStream = null;
    this.micCtx = null;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  get currentMicId(): string {
    const track = this.micStream?.getAudioTracks()[0];
    return track?.getSettings?.().deviceId || "";
  }

  // ---- playback ----

  setOutSampleRate(rate: number): void {
    this.outSampleRate = rate;
  }

  ensureOutCtx(): AudioContext {
    if (this.outCtx) return this.outCtx;
    const ctx = new (window.AudioContext ||
      (window as any).webkitAudioContext)({
      sampleRate: this.outSampleRate,
    });
    this.outCtx = ctx;
    this.playbackTime = ctx.currentTime;

    // Android workaround: getUserMedia switches the route to the earpiece
    // ("communication mode"); piping through a MediaStream → <audio> element
    // forces loudspeaker. Falls back to ctx.destination on browsers without
    // createMediaStreamDestination.
    try {
      const dest = ctx.createMediaStreamDestination();
      const el = document.createElement("audio");
      el.srcObject = dest.stream;
      el.play().catch(() => {});
      this.outNode = dest;
      this.outAudioEl = el;
    } catch {
      this.outNode = ctx.destination;
    }
    return ctx;
  }

  async unlockOutCtx(): Promise<void> {
    const ctx = this.ensureOutCtx();
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        /* */
      }
    }
  }

  async enqueueAudio(arrayBuf: ArrayBuffer): Promise<void> {
    const ctx = this.ensureOutCtx();
    if (ctx.state === "suspended") {
      try {
        await ctx.resume();
      } catch {
        /* */
      }
    }
    const float32 = new Float32Array(arrayBuf);
    const buf = ctx.createBuffer(1, float32.length, this.outSampleRate);
    buf.copyToChannel(float32, 0);

    const src = ctx.createBufferSource();
    src.buffer = buf;

    if (!this.analyser) {
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.connect(this.outNode || ctx.destination);
    }
    src.connect(this.analyser);

    const now = ctx.currentTime;
    // If the queue has drained (or never started), rebuild a small lead before
    // the first buffer so a stalled next sentence doesn't underrun into a gap.
    // Otherwise chain seamlessly onto the already-scheduled tail.
    if (this.playbackTime <= now) {
      this.playbackTime = now + this.LEAD_SEC;
    }
    const startAt = this.playbackTime;
    src.start(startAt);
    this.playbackTime = startAt + buf.duration;
    this.scheduledNodes.push(src);
    src.onended = () => {
      this.scheduledNodes = this.scheduledNodes.filter((n) => n !== src);
      // Queue drained naturally → tell the server playback is done so it can
      // reopen the mic (after its cooldown). stopAllPlayback() clears the list
      // first, so an interrupt won't spuriously fire this.
      if (this.scheduledNodes.length === 0) this.onDrained?.();
    };
  }

  setOnDrained(cb: (() => void) | null): void {
    this.onDrained = cb;
  }

  getAnalyser(): AnalyserNode | null {
    return this.analyser;
  }

  stopAllPlayback(): void {
    for (const n of this.scheduledNodes) {
      try {
        n.stop();
      } catch {
        /* */
      }
    }
    this.scheduledNodes = [];
    if (this.outCtx) this.playbackTime = this.outCtx.currentTime;
  }
}
