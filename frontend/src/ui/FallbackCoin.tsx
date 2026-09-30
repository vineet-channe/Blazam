"use client";

import { useEffect, useRef } from "react";
import { toggleListen } from "@/lib/controller";
import { live } from "@/lib/live";
import { useBlazam } from "@/lib/store";

/**
 * No-WebGL fallback: a CSS coin in a misty gradient that runs the exact same state machine.
 * Spin, progress ring and level ring are driven by the same `live` values as the 3D scene.
 */
export function FallbackCoin() {
  const phase = useBlazam((s) => s.phase);
  const ring = useRef<SVGCircleElement>(null);
  const level = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      if (ring.current) ring.current.style.strokeDashoffset = String(100 - live.recordProgress * 100);
      if (level.current) level.current.style.transform = `scale(${1 + live.micLevel * 0.12})`;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="fallback-scene">
      <div className="fallback-mist" />
      <button
        type="button"
        tabIndex={-1}
        aria-hidden
        onClick={toggleListen}
        onPointerEnter={() => useBlazam.getState().set({ coinHover: true })}
        onPointerLeave={() => useBlazam.getState().set({ coinHover: false })}
        className={`fallback-coin fallback-coin--${phase}`}
      >
        <span className="fallback-coin__face">B</span>
      </button>
      <div ref={level} className={`fallback-level ${phase === "listening" ? "is-on" : ""}`} />
      <svg className={`fallback-ring ${phase === "listening" || phase === "processing" ? "is-on" : ""}`} viewBox="0 0 100 100" aria-hidden>
        <circle cx="50" cy="50" r="48" pathLength={100} className="fallback-ring__track" />
        <circle ref={ring} cx="50" cy="50" r="48" pathLength={100} className="fallback-ring__arc" />
      </svg>
      <div className="fallback-pool" />
    </div>
  );
}
