import { ApiError, recognize } from "./api";
import { emitBurst, live } from "./live";
import { MicError, MicRecorder } from "./recorder";
import { sfx } from "./sound";
import { useBlazam, type ErrorKind } from "./store";

/** Record length. 7-10 s clips work best with the backend; values outside are clamped. */
export const RECORD_MS = clamp(Number(process.env.NEXT_PUBLIC_RECORD_MS ?? 8000), 7000, 10_000);
/** An early stop before this much audio would give the engine too little to match. */
const MIN_RECORD_MS = 2500;
/** Keep the "Identifying" deceleration on screen long enough to read, even at 165 ms latencies. */
const MIN_PROCESSING_MS = 1300;

function clamp(v: number, lo: number, hi: number) {
  return Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : 8000;
}

let recorder: MicRecorder | null = null;
let stopTimer: ReturnType<typeof setTimeout> | undefined;
let progressRaf = 0;
let session = 0;

const store = () => useBlazam.getState();

function fail(kind: ErrorKind) {
  sfx.stopSpin();
  sfx.error();
  emitBurst(0.6, "smoke");
  store().go("error", { error: kind });
}

/** Click / Space / Enter on the coin or the dock's Listen button. */
export function toggleListen() {
  const { phase } = store();
  if (phase === "listening") return void stopListening();
  if (phase === "processing") return;
  void startListening();
}

/** Close the result / error and return to idle. */
export function dismiss() {
  if (["reveal", "no_match", "error"].includes(store().phase)) store().go("idle");
}

async function startListening() {
  if (!store().go("listening")) return;
  const my = ++session;
  sfx.unlock();
  sfx.ignite();
  sfx.startSpin();
  live.impulse++;
  emitBurst(1.4, "fire");
  live.recordProgress = 0;

  recorder = new MicRecorder();
  try {
    await recorder.start();
  } catch (e) {
    recorder = null;
    if (my === session) fail(e instanceof MicError ? e.kind : "mic_unavailable");
    return;
  }
  if (my !== session || store().phase !== "listening") {
    recorder.dispose();
    return;
  }
  const tick = () => {
    live.recordProgress = recorder ? Math.min(1, recorder.elapsedMs / RECORD_MS) : live.recordProgress;
    progressRaf = requestAnimationFrame(tick);
  };
  tick();
  stopTimer = setTimeout(() => void stopListening(), RECORD_MS);
}

async function stopListening() {
  const rec = recorder;
  if (!rec || store().phase !== "listening") return;
  const elapsed = rec.elapsedMs;
  if (elapsed < MIN_RECORD_MS) {
    // too early: finish at the minimum instead of sending a useless clip
    clearTimeout(stopTimer);
    stopTimer = setTimeout(() => void stopListening(), MIN_RECORD_MS - elapsed);
    return;
  }
  clearTimeout(stopTimer);
  cancelAnimationFrame(progressRaf);
  recorder = null;
  const my = session;
  let clip;
  try {
    clip = await rec.stop();
  } catch (e) {
    if (my === session) fail(e instanceof MicError ? e.kind : "mic_unavailable");
    return;
  }
  if (!store().go("processing")) return;
  live.recordProgress = 1;

  const started = performance.now();
  try {
    const res = await recognize(clip.blob, clip.filename);
    const wait = MIN_PROCESSING_MS - (performance.now() - started);
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    if (my !== session) return;
    sfx.stopSpin();
    if (res.status === "match" && res.song) {
      store().go("reveal", { result: res });
      sfx.reveal();
      emitBurst(1.6, "fire");
      if (res.learned) store().showToast("Added to library", "lime");
    } else {
      store().go("no_match", { result: res });
      sfx.sputter();
      emitBurst(1, "smoke");
    }
  } catch (e) {
    if (my !== session) return;
    if (e instanceof ApiError) {
      const map: Record<ApiError["kind"], ErrorKind> = {
        offline: "offline",
        timeout: "timeout",
        bad_audio: "bad_audio",
        too_large: "bad_audio",
        not_found: "server",
        server: "server",
        invalid: "server",
      };
      if (e.kind === "offline") store().set({ backend: "down" });
      fail(map[e.kind]);
    } else {
      fail("server");
    }
  }
}
