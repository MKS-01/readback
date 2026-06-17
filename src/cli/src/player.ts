// afplay wrapper — module singleton outside React. Pause/resume via
// SIGSTOP/SIGCONT (afplay has no transport control); elapsed time is
// wall-clock tracked here because afplay reports nothing.
//
// Seeking: afplay can't start at an offset, so seek() slices the PCM data of
// the local WAV at the target byte offset into a temp file and relaunches
// afplay on that. Rapid seeks are debounced; the UI clock jumps immediately.

import { openSync, readSync, closeSync, createReadStream, createWriteStream } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export type PlayerState = "playing" | "paused" | "stopped" | "finished";

export interface PlayerSnapshot {
  state: PlayerState;
  elapsed: number; // seconds
}

type Listener = (snap: PlayerSnapshot) => void;

const SEEK_FILE = join(tmpdir(), `readback-seek-${process.pid}.wav`);
const SEEK_DEBOUNCE_MS = 180;

let proc: ReturnType<typeof Bun.spawn> | null = null;
let state: PlayerState = "stopped";
let elapsed = 0;
let timer: ReturnType<typeof setInterval> | null = null;
let listener: Listener | null = null;
let generation = 0; // invalidates exit handlers from superseded plays

let currentWav = "";
let currentDur = 0;
let seeking = false; // freezes the clock while a seek restart is in flight
let seekTimer: ReturnType<typeof setTimeout> | null = null;

function emit(): void {
  listener?.({ state, elapsed });
}

function clearTimer(): void {
  if (timer) clearInterval(timer);
  timer = null;
}

function startTimer(): void {
  clearTimer();
  timer = setInterval(() => {
    if (state === "playing" && !seeking) {
      elapsed = Math.min(elapsed + 0.25, currentDur);
      emit();
    }
  }, 250);
}

function killProc(): void {
  if (proc && proc.exitCode === null) {
    proc.kill("SIGKILL");
  }
  proc = null;
}

function spawnAfplay(path: string, gen: number): void {
  proc = Bun.spawn(["afplay", path], { stdout: "ignore", stderr: "ignore" });
  proc.exited.then(() => {
    if (gen !== generation) return; // superseded by a newer play()/seek()/stop()
    clearTimer();
    proc = null;
    if (state === "playing" || state === "paused") {
      state = "finished";
      elapsed = currentDur;
      emit();
    }
  });
}

export function onPlayerChange(fn: Listener | null): void {
  listener = fn;
}

export function play(wavPath: string, durationSec: number): void {
  stop();
  currentWav = wavPath;
  currentDur = durationSec;
  const gen = ++generation;
  state = "playing";
  elapsed = 0;
  spawnAfplay(wavPath, gen);
  startTimer();
  emit();
}

export function togglePause(): void {
  if (state === "playing") {
    if (seekTimer) clearTimeout(seekTimer);
    seekTimer = null;
    seeking = false;
    generation++;
    killProc();
    clearTimer();
    state = "paused";
    emit();
  } else if (state === "paused") {
    state = "playing";
    seeking = true;
    emit();
    void restartAt(elapsed);
  }
}

/** Jump deltaSec forward/back. Restarts afplay on a sliced WAV (debounced). */
export function seek(deltaSec: number): void {
  if (!currentWav || state === "stopped") return;
  elapsed = Math.min(Math.max(elapsed + deltaSec, 0), Math.max(currentDur - 0.25, 0));
  seeking = true;
  state = "playing"; // seeking out of paused/finished resumes playback
  emit();
  if (seekTimer) clearTimeout(seekTimer);
  seekTimer = setTimeout(() => {
    seekTimer = null;
    void restartAt(elapsed);
  }, SEEK_DEBOUNCE_MS);
}

async function restartAt(targetSec: number): Promise<void> {
  const gen = ++generation;
  killProc();
  try {
    let path = currentWav;
    if (targetSec > 0.05) {
      await writeSlice(currentWav, targetSec, SEEK_FILE);
      path = SEEK_FILE;
    }
    if (gen !== generation) return; // a newer seek/play/stop superseded us
    spawnAfplay(path, gen);
    startTimer();
  } catch {
    // slice failed (unreadable wav?) — fall back to a fresh full play
    if (gen !== generation) return;
    elapsed = 0;
    spawnAfplay(currentWav, gen);
    startTimer();
  } finally {
    if (gen === generation) {
      seeking = false;
      emit();
    }
  }
}

export function stop(): void {
  generation++;
  if (seekTimer) clearTimeout(seekTimer);
  seekTimer = null;
  seeking = false;
  clearTimer();
  killProc();
  state = "stopped";
  elapsed = 0;
}

// --- WAV slicing -----------------------------------------------------------

interface WavInfo {
  channels: number;
  sampleRate: number;
  byteRate: number;
  blockAlign: number;
  bits: number;
  dataStart: number;
  dataSize: number;
}

function parseWav(path: string): WavInfo {
  const fd = openSync(path, "r");
  try {
    const head = Buffer.alloc(12);
    readSync(fd, head, 0, 12, 0);
    if (head.toString("ascii", 0, 4) !== "RIFF" || head.toString("ascii", 8, 12) !== "WAVE")
      throw new Error("not a RIFF/WAVE file");
    let off = 12;
    let fmt: Omit<WavInfo, "dataStart" | "dataSize"> | null = null;
    let data: { start: number; size: number } | null = null;
    const chunk = Buffer.alloc(8);
    while (!(fmt && data)) {
      if (readSync(fd, chunk, 0, 8, off) < 8) break;
      const id = chunk.toString("ascii", 0, 4);
      const size = chunk.readUInt32LE(4);
      if (id === "fmt ") {
        const b = Buffer.alloc(16);
        readSync(fd, b, 0, 16, off + 8);
        fmt = {
          channels: b.readUInt16LE(2),
          sampleRate: b.readUInt32LE(4),
          byteRate: b.readUInt32LE(8),
          blockAlign: b.readUInt16LE(12),
          bits: b.readUInt16LE(14),
        };
      } else if (id === "data") {
        data = { start: off + 8, size };
      }
      off += 8 + size + (size % 2); // chunks are word-aligned
    }
    if (!fmt || !data) throw new Error("missing fmt/data chunk");
    return { ...fmt, dataStart: data.start, dataSize: data.size };
  } finally {
    closeSync(fd);
  }
}

function wavHeader(info: WavInfo, dataSize: number): Buffer {
  const h = Buffer.alloc(44);
  h.write("RIFF", 0, "ascii");
  h.writeUInt32LE(36 + dataSize, 4);
  h.write("WAVE", 8, "ascii");
  h.write("fmt ", 12, "ascii");
  h.writeUInt32LE(16, 16);
  h.writeUInt16LE(1, 20); // PCM
  h.writeUInt16LE(info.channels, 22);
  h.writeUInt32LE(info.sampleRate, 24);
  h.writeUInt32LE(info.byteRate, 28);
  h.writeUInt16LE(info.blockAlign, 32);
  h.writeUInt16LE(info.bits, 34);
  h.write("data", 36, "ascii");
  h.writeUInt32LE(dataSize, 40);
  return h;
}

function writeSlice(src: string, fromSec: number, dest: string): Promise<void> {
  const info = parseWav(src);
  const offset = Math.min(
    Math.floor((fromSec * info.byteRate) / info.blockAlign) * info.blockAlign,
    info.dataSize,
  );
  const remaining = info.dataSize - offset;
  return new Promise((resolve, reject) => {
    const ws = createWriteStream(dest);
    ws.write(wavHeader(info, remaining));
    const rs = createReadStream(src, {
      start: info.dataStart + offset,
      end: info.dataStart + info.dataSize - 1,
    });
    rs.on("error", reject);
    ws.on("error", reject);
    ws.on("finish", resolve);
    rs.pipe(ws);
  });
}
