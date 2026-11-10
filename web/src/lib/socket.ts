import { wsUrl } from "./api";

type Listener = (msg: any) => void;
export type LinkState = "connecting" | "open" | "closed" | "unauthorized";

/** Authenticated WebSocket to /ws/client with heartbeat and jittered reconnect. */
export class ClientSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private stateListeners = new Set<(s: LinkState) => void>();
  private retry = 0;
  private timer: number | null = null;
  private ping: number | null = null;
  private stopped = false;
  state: LinkState = "connecting";

  constructor(private token: string) {}

  start() {
    this.stopped = false;
    this.connect();
    document.addEventListener("visibilitychange", this.onVisible);
    window.addEventListener("online", this.onVisible);
  }

  stop() {
    this.stopped = true;
    document.removeEventListener("visibilitychange", this.onVisible);
    window.removeEventListener("online", this.onVisible);
    if (this.timer) clearTimeout(this.timer);
    if (this.ping) clearInterval(this.ping);
    this.ws?.close();
  }

  on(fn: Listener) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  onState(fn: (s: LinkState) => void) { this.stateListeners.add(fn); return () => this.stateListeners.delete(fn); }

  send(obj: unknown): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  private setState(s: LinkState) {
    this.state = s;
    this.stateListeners.forEach((f) => f(s));
  }

  private onVisible = () => {
    // Phones suspend background tabs; reconnect immediately when the user comes back.
    if (document.visibilityState === "visible" && this.ws?.readyState !== WebSocket.OPEN && !this.stopped) {
      if (this.timer) clearTimeout(this.timer);
      this.retry = 0;
      this.connect();
    }
  };

  private connect() {
    if (this.stopped) return;
    this.ws?.close();
    this.setState("connecting");
    const ws = new WebSocket(wsUrl("/ws/client"));
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token: this.token }));
    };
    ws.onmessage = (ev) => {
      let msg: any;
      try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === "unauthorized") { this.setState("unauthorized"); this.stopped = true; return; }
      if (msg.type === "ready") {
        this.retry = 0;
        this.setState("open");
        if (this.ping) clearInterval(this.ping);
        this.ping = window.setInterval(() => this.send({ type: "ping" }), 20000);
      }
      this.listeners.forEach((f) => f(msg));
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      if (this.ping) clearInterval(this.ping);
      if (ev.code === 4401) { this.setState("unauthorized"); return; }
      if (this.stopped) return;
      this.setState("closed");
      const delay = Math.min(15000, 600 * 2 ** this.retry) * (0.7 + Math.random() * 0.6);
      this.retry++;
      this.timer = window.setTimeout(() => this.connect(), delay);
    };
  }
}
