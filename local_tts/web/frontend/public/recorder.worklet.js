// AudioWorkletProcessor that downsamples mono mic input to 16kHz Int16 PCM
// and posts chunks to the main thread.
class RecorderProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.targetRate = (options.processorOptions && options.processorOptions.targetRate) || 16000;
    // sampleRate is a global in AudioWorkletGlobalScope
    this.ratio = sampleRate / this.targetRate;
    this._frac = 0;
    this._chunk = [];
    this._chunkTarget = Math.round(this.targetRate * 0.06); // ~60ms (≈ 2 VAD frames)
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0];
    if (!ch || ch.length === 0) return true;

    // Linear-interp downsample at integer-or-fractional ratio.
    let i = this._frac;
    while (i < ch.length) {
      const idx = Math.floor(i);
      const next = Math.min(idx + 1, ch.length - 1);
      const t = i - idx;
      let s = ch[idx] * (1 - t) + ch[next] * t;
      if (s > 1) s = 1; else if (s < -1) s = -1;
      this._chunk.push(s);
      i += this.ratio;
    }
    this._frac = i - ch.length;

    while (this._chunk.length >= this._chunkTarget) {
      const slice = this._chunk.splice(0, this._chunkTarget);
      const i16 = new Int16Array(slice.length);
      for (let k = 0; k < slice.length; k++) {
        i16[k] = Math.max(-32768, Math.min(32767, Math.round(slice[k] * 32767)));
      }
      this.port.postMessage(i16.buffer, [i16.buffer]);
    }
    return true;
  }
}

registerProcessor("recorder-processor", RecorderProcessor);
