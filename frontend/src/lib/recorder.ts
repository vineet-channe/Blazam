import { live } from "./live";
import type { ErrorKind } from "./store";

export class MicError extends Error {
  constructor(public readonly kind: ErrorKind) {
    super(kind);
    this.name = "MicError";
  }
}

/** Preferred containers, in order. The backend decodes all of them via ffmpeg. */
const MIME_CANDIDATES: readonly [mime: string, ext: string][] = [
  ["audio/webm;codecs=opus", "webm"],
  ["audio/webm", "webm"],
  ["audio/ogg;codecs=opus", "ogg"],
  ["audio/mp4;codecs=mp4a.40.2", "m4a"],
  ["audio/mp4", "m4a"],
];

function pickMime(): { mime: string | undefined; ext: string } {
  if (typeof MediaRecorder === "undefined") return { mime: undefined, ext: "webm" };
  for (const [mime, ext] of MIME_CANDIDATES) if (MediaRecorder.isTypeSupported(mime)) return { mime, ext };
  // Safari without isTypeSupported hits: let the browser choose, it will be mp4
  return { mime: undefined, ext: "m4a" };
}

export type Recording = { blob: Blob; filename: string; durationMs: number };

/**
 * Records the microphone with MediaRecorder while an AnalyserNode feeds `live.micLevel`.
 * Browser voice processing is disabled: echo cancellation and noise suppression smear the
 * spectral peaks the fingerprinting engine depends on.
 */
export class MicRecorder {
  private stream?: MediaStream;
  private ctx?: AudioContext;
  private recorder?: MediaRecorder;
  private chunks: Blob[] = [];
  private raf = 0;
  private startedAt = 0;
  private ext = "webm";

  async start(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      throw new MicError("mic_unsupported");
    }
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (e) {
      const name = e instanceof DOMException ? e.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") throw new MicError("mic_denied");
      throw new MicError("mic_unavailable");
    }

    const { mime, ext } = pickMime();
    this.ext = ext;
    this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime, audioBitsPerSecond: 128_000 } : undefined);
    this.chunks = [];
    this.recorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.recorder.start(250);
    this.startedAt = performance.now();
    this.meter(this.stream);
  }

  get elapsedMs() {
    return this.startedAt ? performance.now() - this.startedAt : 0;
  }

  private meter(stream: MediaStream) {
    try {
      this.ctx = new AudioContext();
      const src = this.ctx.createMediaStreamSource(stream);
      const analyser = this.ctx.createAnalyser();
      analyser.fftSize = 1024;
      src.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const tick = () => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);
        // perceptual-ish curve: -50 dBFS -> 0, -6 dBFS -> 1
        const db = 20 * Math.log10(rms + 1e-8);
        const level = Math.min(1, Math.max(0, (db + 50) / 44));
        live.micLevel += (level - live.micLevel) * (level > live.micLevel ? 0.5 : 0.12);
        this.raf = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      live.micLevel = 0.3; // metering is cosmetic; recording still works
    }
  }

  stop(): Promise<Recording> {
    const rec = this.recorder;
    const durationMs = this.elapsedMs;
    return new Promise((resolve, reject) => {
      if (!rec || rec.state === "inactive") {
        this.dispose();
        reject(new MicError("mic_unavailable"));
        return;
      }
      rec.onstop = () => {
        const type = rec.mimeType || this.chunks[0]?.type || "audio/webm";
        const blob = new Blob(this.chunks, { type });
        this.dispose();
        resolve({ blob, filename: `clip.${this.ext}`, durationMs });
      };
      rec.stop();
    });
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close().catch(() => undefined);
    this.stream = undefined;
    this.ctx = undefined;
    this.recorder = undefined;
    this.startedAt = 0;
    live.micLevel = 0;
  }
}
