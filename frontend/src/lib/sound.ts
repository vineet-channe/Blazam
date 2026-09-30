import { live } from "./live";
import { useBlazam } from "./store";

/**
 * Every sound is synthesized with Web Audio: no audio assets to ship. The context is created
 * lazily on the first user gesture (autoplay policy) and respects the mute toggle.
 */
let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let noiseBuf: AudioBuffer | null = null;
let spin: { src: AudioBufferSourceNode; filter: BiquadFilterNode; gain: GainNode; timer: ReturnType<typeof setInterval> } | null = null;

function audio(): { ctx: AudioContext; out: GainNode; noise: AudioBuffer } | null {
  if (typeof window === "undefined") return null;
  if (!ctx) {
    try {
      ctx = new AudioContext();
      master = ctx.createGain();
      master.gain.value = 0.55;
      master.connect(ctx.destination);
      noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    } catch {
      return null;
    }
  }
  if (ctx.state === "suspended") void ctx.resume();
  return ctx && master && noiseBuf ? { ctx, out: master, noise: noiseBuf } : null;
}

const muted = () => useBlazam.getState().muted;

function env(g: GainNode, t: number, peak: number, attack: number, decay: number) {
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(peak, t + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
}

function noise(a: NonNullable<ReturnType<typeof audio>>, type: BiquadFilterType, f0: number, f1: number, dur: number, peak: number, at = 0) {
  const t = a.ctx.currentTime + at;
  const src = a.ctx.createBufferSource();
  src.buffer = a.noise;
  const filter = a.ctx.createBiquadFilter();
  filter.type = type;
  filter.Q.value = 1.2;
  filter.frequency.setValueAtTime(f0, t);
  filter.frequency.exponentialRampToValueAtTime(f1, t + dur);
  const g = a.ctx.createGain();
  env(g, t, peak, 0.02, dur);
  src.connect(filter).connect(g).connect(a.out);
  src.start(t, Math.random());
  src.stop(t + dur + 0.1);
}

function tone(a: NonNullable<ReturnType<typeof audio>>, type: OscillatorType, f0: number, f1: number, dur: number, peak: number, at = 0) {
  const t = a.ctx.currentTime + at;
  const osc = a.ctx.createOscillator();
  osc.type = type;
  osc.frequency.setValueAtTime(f0, t);
  osc.frequency.exponentialRampToValueAtTime(f1, t + dur);
  const g = a.ctx.createGain();
  env(g, t, peak, 0.01, dur);
  osc.connect(g).connect(a.out);
  osc.start(t);
  osc.stop(t + dur + 0.05);
}

export const sfx = {
  /** call inside a user gesture so later sounds are allowed to play */
  unlock() {
    audio();
  },
  ignite() {
    const a = audio();
    if (!a || muted()) return;
    tone(a, "sine", 110, 38, 0.6, 0.7);
    noise(a, "bandpass", 300, 4200, 0.55, 0.5);
    for (let i = 0; i < 9; i++) noise(a, "highpass", 3000 + Math.random() * 3000, 6000, 0.03, 0.15 + Math.random() * 0.2, 0.05 + Math.random() * 0.4);
  },
  /** continuous whoosh whose pitch and level follow the coin's spin */
  startSpin() {
    const a = audio();
    if (!a || spin) return;
    const src = a.ctx.createBufferSource();
    src.buffer = a.noise;
    src.loop = true;
    const filter = a.ctx.createBiquadFilter();
    filter.type = "bandpass";
    filter.Q.value = 2.5;
    const gain = a.ctx.createGain();
    gain.gain.value = 0;
    src.connect(filter).connect(gain).connect(a.out);
    src.start();
    const timer = setInterval(() => {
      const s = live.spin;
      const t = a.ctx.currentTime;
      // amplitude-modulate at the coin's rotation rate for the "wub" of a spinning disc
      const wob = 0.75 + 0.25 * Math.sin(t * 25 * s * 2);
      gain.gain.setTargetAtTime(muted() ? 0 : 0.22 * s * wob * (0.7 + live.micLevel * 0.6), t, 0.05);
      filter.frequency.setTargetAtTime(250 + 1900 * s, t, 0.08);
    }, 40);
    spin = { src, filter, gain, timer };
  },
  stopSpin() {
    if (!spin || !ctx) return;
    const s = spin;
    spin = null;
    clearInterval(s.timer);
    s.gain.gain.setTargetAtTime(0, ctx.currentTime, 0.35);
    s.src.stop(ctx.currentTime + 1.6);
  },
  reveal() {
    const a = audio();
    if (!a || muted()) return;
    noise(a, "bandpass", 5000, 800, 0.5, 0.25);
    [523.25, 783.99, 1046.5, 1567.98].forEach((f, i) => tone(a, "sine", f, f * 1.002, 2.2 - i * 0.3, 0.16 - i * 0.025, i * 0.06));
    tone(a, "triangle", 130.8, 130.8, 1.6, 0.12);
  },
  sputter() {
    const a = audio();
    if (!a || muted()) return;
    for (let i = 0; i < 5; i++) noise(a, "lowpass", 900 - i * 120, 120, 0.18, 0.35 - i * 0.05, i * 0.14 + Math.random() * 0.05);
    tone(a, "sine", 180, 60, 0.9, 0.18);
  },
  error() {
    const a = audio();
    if (!a || muted()) return;
    tone(a, "sine", 330, 320, 0.35, 0.12);
    tone(a, "sine", 247, 240, 0.5, 0.12, 0.18);
  },
};
