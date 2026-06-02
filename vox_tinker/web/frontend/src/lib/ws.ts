// Single WebSocket client. Dispatches text frames (control messages) and
// binary frames (TTS audio) to caller-provided handlers. Living outside React
// means a re-render never tears down the socket.

export type WSMessage = { type: string; [key: string]: any };

export interface WSClientHandlers {
  onControl: (msg: WSMessage) => void;
  onAudio: (data: ArrayBuffer) => void;
  onOpen: () => void;
  onClose: () => void;
  onError: () => void;
}

function wsUrl(): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

export class WSClient {
  private ws: WebSocket | null = null;
  private handlers: WSClientHandlers;

  constructor(handlers: WSClientHandlers) {
    this.handlers = handlers;
  }

  connect(): void {
    const ws = new WebSocket(wsUrl());
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    ws.onopen = () => this.handlers.onOpen();
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          this.handlers.onControl(JSON.parse(ev.data));
        } catch (e) {
          console.warn("[ws] bad control payload", e);
        }
      } else {
        this.handlers.onAudio(ev.data as ArrayBuffer);
      }
    };
    ws.onclose = () => this.handlers.onClose();
    ws.onerror = () => this.handlers.onError();
  }

  send(obj: WSMessage): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(obj));
    }
  }

  sendBinary(buf: ArrayBuffer | ArrayBufferView): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(buf as any);
    }
  }

  close(): void {
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* */
      }
      this.ws = null;
    }
  }

  get isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
