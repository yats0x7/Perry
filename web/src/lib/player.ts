import { absoluteUrl } from "./api";

// One shared <audio> element. iOS Safari only allows programmatic playback on an element
// that has played once inside a user gesture, so we "unlock" it on the first tap
// (mic or send) and reuse it for every Timbre reply.
function silentWav(): string {
  // 50 ms of 8 kHz mono 16-bit silence, built at runtime (always a valid file).
  const n = 400, buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const w = (o: number, t: string) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); w(8, "WAVE"); w(12, "fmt "); v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 16000, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, n * 2, true);
  let bin = "";
  new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b)));
  return "data:audio/wav;base64," + btoa(bin);
}

class Player {
  el = new Audio();
  unlocked = false;
  currentUrl: string | null = null;
  private listeners = new Set<() => void>();

  constructor() {
    this.el.preload = "auto";
    (this.el as any).playsInline = true;
    for (const ev of ["play", "pause", "ended", "error", "playing", "waiting"]) {
      this.el.addEventListener(ev, () => this.listeners.forEach((f) => f()));
    }
  }

  unlock() {
    if (this.unlocked) return;
    this.unlocked = true;
    this.el.src = silentWav();
    this.el.play().catch(() => { this.unlocked = false; });
  }

  async play(url: string): Promise<void> {
    const full = absoluteUrl(url);
    this.currentUrl = url;
    this.el.src = full;
    await this.el.play();
  }

  stop() {
    // Only interrupt a real reply; pausing the silent unlock clip would undo the unlock.
    if (this.currentUrl !== null) this.el.pause();
    this.currentUrl = null;
    this.listeners.forEach((f) => f());
  }

  get playing(): boolean {
    return !this.el.paused && !this.el.ended && this.currentUrl !== null;
  }

  subscribe(fn: () => void) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
}

export const player = new Player();
