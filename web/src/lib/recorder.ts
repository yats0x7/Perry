// Push-to-talk recorder that produces 16 kHz mono 16-bit WAV in the browser.
// Gnani Prisma's REST API accepts wav/mp3/ogg/flac/aac/m4a but not WebM (Chrome's
// MediaRecorder default), so we capture raw PCM ourselves — identical on Android
// Chrome, iPhone Safari and desktop browsers.

const TARGET_RATE = 16000;
export const MAX_SECONDS = 28; // Prisma REST limit is 30 s per request

export class WavRecorder {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunks: Float32Array[] = [];
  private rate = 48000;
  private startedAt = 0;
  onLevel: (level: number) => void = () => {};
  onAutoStop: () => void = () => {};

  static supported(): boolean {
    return typeof navigator.mediaDevices?.getUserMedia === "function" && !!(window.AudioContext || (window as any).webkitAudioContext);
  }

  async start(): Promise<void> {
    this.chunks = [];
    // iOS Safari only lets an AudioContext start inside the user's tap, so create and
    // resume it synchronously *before* awaiting the microphone permission prompt.
    const Ctx = window.AudioContext || (window as any).webkitAudioContext;
    this.ctx = new Ctx();
    const resumed = this.ctx.resume();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      this.ctx.close().catch(() => {});
      throw e;
    }
    await resumed;
    if (this.ctx.state !== "running") await this.ctx.resume();
    this.rate = this.ctx.sampleRate;
    this.source = this.ctx.createMediaStreamSource(this.stream);
    // ScriptProcessor is deprecated but is the one capture path that works everywhere,
    // including older iOS Safari, without serving a separate worklet module.
    this.node = this.ctx.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (e) => {
      const data = e.inputBuffer.getChannelData(0);
      this.chunks.push(new Float32Array(data));
      let sum = 0;
      for (let i = 0; i < data.length; i += 4) sum += data[i] * data[i];
      this.onLevel(Math.min(1, Math.sqrt(sum / (data.length / 4)) * 4));
      if ((performance.now() - this.startedAt) / 1000 > MAX_SECONDS) this.onAutoStop();
    };
    this.source.connect(this.node);
    this.node.connect(this.ctx.destination);
    this.startedAt = performance.now();
  }

  get seconds(): number {
    return this.startedAt ? (performance.now() - this.startedAt) / 1000 : 0;
  }

  async stop(): Promise<Blob> {
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    await this.ctx?.close().catch(() => {});
    this.onLevel(0);
    const pcm = downsample(merge(this.chunks), this.rate, TARGET_RATE);
    this.chunks = [];
    this.startedAt = 0;
    return encodeWav(pcm, TARGET_RATE);
  }

  cancel() {
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.chunks = [];
    this.startedAt = 0;
    this.onLevel(0);
  }
}

function merge(chunks: Float32Array[]): Float32Array {
  const len = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Float32Array(len);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return out;
}

function downsample(buf: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return buf;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(buf.length / ratio));
  for (let i = 0; i < out.length; i++) {
    // average the source window (simple low-pass) to avoid aliasing
    const start = Math.floor(i * ratio), end = Math.min(buf.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += buf[j];
    out[i] = sum / Math.max(1, end - start);
  }
  return out;
}

function encodeWav(samples: Float32Array, rate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buffer);
  const w = (o: number, s: string) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); w(8, "WAVE");
  w(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  w(36, "data"); v.setUint32(40, samples.length * 2, true);
  let o = 44;
  for (let i = 0; i < samples.length; i++, o += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(o, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}
