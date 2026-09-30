"use client";

import { useEffect } from "react";
import { getHealth } from "@/lib/api";
import { useBlazam } from "@/lib/store";

/** Polls /api/health so the UI can show a designed "server offline" state before anyone clicks. */
export function useBackendHealth(intervalMs = 15_000) {
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    let alive = true;
    let failures = 0;
    const check = async () => {
      try {
        await getHealth();
        failures = 0;
        if (alive) useBlazam.getState().set({ backend: "up" });
      } catch {
        // one miss can be a main thread busy compiling shaders; two in a row means offline
        failures++;
        if (alive && failures >= 2) useBlazam.getState().set({ backend: "down" });
      }
      if (alive) timer = setTimeout(check, failures > 0 ? 3000 : intervalMs);
    };
    void check();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [intervalMs]);
}
