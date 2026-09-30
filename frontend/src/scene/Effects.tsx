"use client";

import { useFrame } from "@react-three/fiber";
import { Bloom, ChromaticAberration, DepthOfField, EffectComposer, Noise, ToneMapping, Vignette } from "@react-three/postprocessing";
import { BlendFunction, ToneMappingMode, type BloomEffect, type ChromaticAberrationEffect } from "postprocessing";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { live } from "@/lib/live";
import { COIN_Y } from "./Coin";

type Props = { quality: "high" | "medium" | "low"; reducedMotion: boolean };

/** Bloom breathes and scales with spin speed; chromatic aberration spikes at peak spin. */
export function Effects({ quality, reducedMotion }: Props) {
  const bloom = useRef<BloomEffect>(null);
  const ca = useRef<ChromaticAberrationEffect>(null);
  const caOffset = useMemo(() => new THREE.Vector2(0.0004, 0.0003), []);
  const focus = useMemo(() => new THREE.Vector3(0, COIN_Y, 0), []);

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (bloom.current) {
      const breathe = reducedMotion ? 0.02 : 0.08 * Math.sin(t * 1.2);
      bloom.current.intensity = 1.05 + breathe + live.spin * 1.5 + live.micLevel * live.spin * 0.6;
    }
    if (ca.current) {
      const peak = reducedMotion ? 0 : Math.max(0, live.spin - 0.6) / 0.4;
      const o = 0.00035 + peak * 0.0022;
      ca.current.offset.set(o, o * 0.7);
    }
  });

  return (
    <EffectComposer multisampling={quality === "high" ? 4 : 0} enableNormalPass={false}>
      <Bloom ref={bloom} mipmapBlur luminanceThreshold={0.82} luminanceSmoothing={0.2} intensity={1.05} radius={0.78} levels={quality === "low" ? 6 : 8} />
      {quality === "high" && <DepthOfField target={focus} focusRange={4.5} bokehScale={2.2} resolutionScale={0.5} />}
      <ChromaticAberration ref={ca} offset={caOffset} radialModulation modulationOffset={0.25} blendFunction={BlendFunction.NORMAL} />
      <ToneMapping mode={ToneMappingMode.NEUTRAL} />
      <Vignette offset={0.2} darkness={0.82} eskil={false} />
      <Noise blendFunction={BlendFunction.OVERLAY} opacity={0.22} />
    </EffectComposer>
  );
}
