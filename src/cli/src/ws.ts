// WS client for the readback /ws protocol — module singleton outside React,
// mirroring the web frontend's lib/ws.ts pattern.

export interface DoneMsg {
  type: "done";
  title: string;
  audio_url: string;
  duration_sec: number;
  word_count: number;
  mode: string;
  text: string | null;
}

export type ServerMsg =
  | {
      type: "config";
      voices_available: { id: string; label: string }[];
      voice: string;
      model: string;
      vision_model: string;
      default_mode: "full" | "summary";
      audio_dir?: string;   // where the server writes WAVs (same-machine shortcut)
    }
  | { type: "phase"; value: string }
  | { type: "progress"; done: number; total: number }
  | DoneMsg
  | { type: "error"; message: string };

type Handler = (msg: ServerMsg) => void;

// The live socket, tracked module-side so the process-exit path (index.tsx
// shutdown / signal handlers) can close it BEFORE killing the spawned server —
// uvicorn's graceful shutdown hangs on an open websocket, so closing it first
// lets the server exit in milliseconds instead of waiting out the SIGKILL timer.
let active: ReadbackSocket | null = null;
export function closeActiveSocket(): void {
  active?.close();
}

export class ReadbackSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private handler: Handler;
  private onDrop: () => void;
  private closed = false;

  constructor(base: string, handler: Handler, onDrop: () => void) {
    this.url = base.replace(/^http/, "ws") + "/ws";
    this.handler = handler;
    this.onDrop = onDrop;
  }

  connect(): Promise<void> {
    return new Promise((resolvePromise, reject) => {
      const ws = new WebSocket(this.url);
      this.ws = ws;
      active = this;
      ws.onopen = () => resolvePromise();
      ws.onerror = () => reject(new Error("websocket connection failed"));
      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        try {
          this.handler(JSON.parse(ev.data) as ServerMsg);
        } catch {
          // ignore malformed frames
        }
      };
      ws.onclose = () => {
        if (!this.closed) this.onDrop();
      };
    });
  }

  send(obj: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  read(
    url: string,
    mode: "full" | "summary",
    voice: string | null,
    model: string | null,
    visionModel: string | null,
  ): void {
    this.send({
      type: "read",
      url,
      mode,
      ...(voice ? { voice } : {}),
      ...(model ? { model } : {}),
      ...(visionModel ? { vision_model: visionModel } : {}),
    });
  }

  cancel(): void {
    this.send({ type: "cancel" });
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
    if (active === this) active = null;
  }
}
