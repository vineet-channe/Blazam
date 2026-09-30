"use client";

import { Environment, Lightformer, PerformanceMonitor } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Suspense, useEffect, useState } from "react";
import { useBlazam } from "@/lib/store";
import { palette, sceneColors } from "@/lib/theme";
import { Atmosphere } from "./Atmosphere";
import { CameraRig } from "./CameraRig";
import { Coin } from "./Coin";
import { Effects } from "./Effects";
import { Landscape } from "./Landscape";
import { Rings } from "./Rings";
import { Sparks } from "./Sparks";

/** Mounted inside the Suspense boundary: runs once every suspended asset (the coin font) is in. */
function ReadySignal() {
  useEffect(() => {
    useBlazam.getState().set({ sceneReady: true });
  }, []);
  return null;
}

type Props = { reducedMotion: boolean; mobile: boolean };

export default function SceneCanvas({ reducedMotion, mobile }: Props) {
  const quality = useBlazam((s) => s.quality);
  const [dpr, setDpr] = useState(mobile ? 1.25 : 1.75);
  const sparkCount = reducedMotion ? 900 : mobile ? 1800 : 5000;

  return (
    <Canvas
      dpr={[1, dpr]}
      gl={{ antialias: false, powerPreference: "high-performance", alpha: false, stencil: false }}
      camera={{ fov: 36, near: 0.1, far: 200, position: [0, 3.2, 17] }}
      onPointerMissed={() => useBlazam.getState().set({ coinHover: false })}
    >
      <PerformanceMonitor
        bounds={(refresh) => (refresh > 90 ? [55, 80] : [42, 58])}
        flipflops={3}
        onDecline={() => {
          const q = useBlazam.getState().quality;
          if (q === "high") useBlazam.getState().set({ quality: "medium" });
          else if (q === "medium") useBlazam.getState().set({ quality: "low" });
          setDpr((d) => Math.max(1, d - 0.25));
        }}
        onIncline={() => setDpr((d) => Math.min(mobile ? 1.25 : 1.75, d + 0.25))}
      />
      <color attach="background" args={[palette.bgDeep]} />
      <fogExp2 attach="fog" args={[palette.fog, 0.027]} />

      <hemisphereLight args={[sceneColors.skyHorizon, palette.bgDeep, 0.35]} />
      {/* cold back light: rims the grass and dunes against the fog */}
      <directionalLight position={[-6, 9, -14]} intensity={1.6} color={palette.glowSoft} />
      <directionalLight position={[5, 4, 8]} intensity={0.35} color={palette.glow} />
      <Environment resolution={64} frames={1}>
        <Lightformer form="rect" intensity={0.9} color={palette.glowSoft} position={[-4, 4, 3]} scale={[2, 5, 1]} />
        <Lightformer form="rect" intensity={0.6} color={palette.glow} position={[5, 1, 2]} scale={[1.5, 4, 1]} />
        <Lightformer form="ring" intensity={0.5} color={palette.lime} position={[0, 5, -4]} scale={3} />
      </Environment>

      <CameraRig reducedMotion={reducedMotion} />
      <Atmosphere dust={quality === "low" ? 60 : mobile ? 90 : 180} />
      <Landscape quality={quality} />
      <Suspense fallback={null}>
        <Coin reducedMotion={reducedMotion} />
        <ReadySignal />
      </Suspense>
      <Rings />
      <Sparks kind="fire" count={sparkCount} reducedMotion={reducedMotion} />
      <Sparks kind="smoke" count={reducedMotion ? 120 : 400} reducedMotion={reducedMotion} />
      <Effects quality={quality} reducedMotion={reducedMotion} />
    </Canvas>
  );
}
