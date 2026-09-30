"use client";

import { useEffect } from "react";
import { live } from "@/lib/live";

/** Feeds pointer position and device tilt into `live` for parallax. */
export function usePointerTracking() {
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      live.pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
      live.pointer.y = -((e.clientY / window.innerHeight) * 2 - 1);
    };
    const onTilt = (e: DeviceOrientationEvent) => {
      if (e.gamma == null || e.beta == null) return;
      live.tilt.x = Math.max(-1, Math.min(1, e.gamma / 35));
      live.tilt.y = Math.max(-1, Math.min(1, (e.beta - 45) / 35));
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("deviceorientation", onTilt, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("deviceorientation", onTilt);
    };
  }, []);
}
