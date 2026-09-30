"use client";

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useBackendHealth } from "@/hooks/useBackendHealth";
import { useMediaQuery, useReducedMotion } from "@/hooks/useMediaQuery";
import { usePointerTracking } from "@/hooks/usePointerTracking";
import { useBlazam } from "@/lib/store";
import { FallbackCoin } from "./FallbackCoin";

const SceneCanvas = dynamic(() => import("@/scene/SceneCanvas"), { ssr: false });

function detectWebGL(): boolean {
  if (new URLSearchParams(window.location.search).get("webgl") === "0") return false;
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * Persistent background: the WebGL scene (or the CSS fallback coin) lives in the root layout,
 * so route changes never remount it. Off the home page it dims and blurs behind the panels.
 */
export function SceneHost() {
  const webgl = useBlazam((s) => s.webgl);
  const coinHover = useBlazam((s) => s.coinHover);
  const pathname = usePathname();
  const reducedMotion = useReducedMotion();
  const mobile = useMediaQuery("(max-width: 768px), (pointer: coarse)");
  const home = pathname === "/";
  usePointerTracking();
  useBackendHealth();

  useEffect(() => {
    useBlazam.getState().set({ webgl: detectWebGL() ? "ok" : "none" });
    try {
      if (localStorage.getItem("blazam:muted") === "1") useBlazam.getState().set({ muted: true });
    } catch {
      /* storage unavailable */
    }
  }, []);

  useEffect(() => {
    document.body.style.cursor = coinHover && home ? "none" : "";
  }, [coinHover, home]);

  return (
    <div
      aria-hidden
      data-testid="scene"
      className={`scene-host fixed inset-0 z-0 ${home ? "" : "scene-host--dim"}`}
      style={{ pointerEvents: home ? "auto" : "none" }}
    >
      {webgl === "ok" && <SceneCanvas reducedMotion={reducedMotion} mobile={mobile} />}
      {webgl === "none" && <FallbackCoin />}
    </div>
  );
}
