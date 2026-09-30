import { create } from "zustand";
import type { RecognizeResponse } from "./schemas";

export type Phase = "idle" | "listening" | "processing" | "reveal" | "no_match" | "error";

export type ErrorKind = "mic_denied" | "mic_unavailable" | "mic_unsupported" | "offline" | "timeout" | "bad_audio" | "server";

/** idle -> listening -> processing -> reveal | no_match | error -> idle (or straight back to listening). */
const TRANSITIONS: Record<Phase, readonly Phase[]> = {
  idle: ["listening"],
  listening: ["processing", "error", "idle"],
  processing: ["reveal", "no_match", "error"],
  reveal: ["idle", "listening"],
  no_match: ["idle", "listening"],
  error: ["idle", "listening"],
};

export type Toast = { id: number; text: string; tone: "lime" | "glow" };

type BlazamState = {
  phase: Phase;
  result: RecognizeResponse | null;
  error: ErrorKind | null;
  toast: Toast | null;
  muted: boolean;
  /** loader finished and the intro camera push has started */
  introStarted: boolean;
  sceneReady: boolean;
  webgl: "unknown" | "ok" | "none";
  backend: "unknown" | "up" | "down";
  /** bumped when a Listen request arrives from off the home page */
  listenRequest: number;
  lyricsOpen: boolean;
  /** cursor is over the coin (drives the "Listen" cursor label) */
  coinHover: boolean;
  /** adaptive render quality, lowered by the PerformanceMonitor */
  quality: "high" | "medium" | "low";

  go: (to: Phase, patch?: Partial<Pick<BlazamState, "result" | "error">>) => boolean;
  showToast: (text: string, tone?: Toast["tone"]) => void;
  setMuted: (muted: boolean) => void;
  set: (patch: Partial<Omit<BlazamState, "go" | "showToast" | "setMuted" | "set">>) => void;
};

let toastId = 0;

export const useBlazam = create<BlazamState>((set, get) => ({
  phase: "idle",
  result: null,
  error: null,
  toast: null,
  muted: false,
  introStarted: false,
  sceneReady: false,
  webgl: "unknown",
  backend: "unknown",
  listenRequest: 0,
  lyricsOpen: false,
  coinHover: false,
  quality: "high",

  go: (to, patch) => {
    const from = get().phase;
    if (!TRANSITIONS[from].includes(to)) return false;
    set({
      phase: to,
      result: to === "reveal" || to === "no_match" ? (patch?.result ?? null) : null,
      error: to === "error" ? (patch?.error ?? "server") : null,
      lyricsOpen: false,
    });
    return true;
  },
  showToast: (text, tone = "lime") => set({ toast: { id: ++toastId, text, tone } }),
  setMuted: (muted) => {
    try {
      localStorage.setItem("blazam:muted", muted ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
    set({ muted });
  },
  set: (patch) => set(patch),
}));
