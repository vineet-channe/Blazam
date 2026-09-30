"use client";

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { live } from "@/lib/live";
import { useBlazam } from "@/lib/store";
import { sceneColors } from "@/lib/theme";
import { COIN_Y } from "./Coin";

/**
 * Recording progress arc plus a live mic-level ring around the coin, drawn as distance
 * fields on one camera-facing quad (additive, so bloom picks them up).
 */
export function Rings() {
  const mesh = useRef<THREE.Mesh>(null);
  const opacity = useRef(0);
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        fog: false,
        uniforms: {
          uTime: { value: 0 },
          uProgress: { value: 0 },
          uLevel: { value: 0 },
          uOpacity: { value: 0 },
          uProcessing: { value: 0 },
          uRing: { value: new THREE.Color(sceneColors.ring) },
          uLevelColor: { value: new THREE.Color(sceneColors.level) },
        },
        vertexShader: /* glsl */ `
          varying vec2 vP;
          void main() { vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
        fragmentShader: /* glsl */ `
          uniform float uTime, uProgress, uLevel, uOpacity, uProcessing;
          uniform vec3 uRing, uLevelColor;
          varying vec2 vP;
          float band(float r, float c, float w) { return 1.0 - smoothstep(0.0, w, abs(r - c)); }
          void main() {
            float r = length(vP);
            // angle from 12 o'clock, clockwise, 0..1
            float a = fract(atan(vP.x, vP.y) / 6.28318530718 + 1.0);
            // faint full track + bright progress arc with a hot leading tip
            float track = band(r, 1.52, 0.006) * 0.25;
            float arc = band(r, 1.52, 0.012) * step(a, uProgress);
            float ta = (a - uProgress) * 60.0;
            float tip = exp(-ta * ta) * band(r, 1.52, 0.05) * step(0.001, uProgress);
            // level ring: radius wobbles with the live mic level
            float wob = sin(a * 6.28318 * 9.0 + uTime * 5.0) * 0.5 + sin(a * 6.28318 * 23.0 - uTime * 7.0) * 0.5;
            float lr = 1.66 + uLevel * 0.06 + wob * uLevel * 0.022;
            float lvl = band(r, lr, 0.006 + uLevel * 0.008) * (0.2 + uLevel * 0.6);
            // processing: orbiting comet
            float orbit = fract(uTime * 0.6);
            float ca = fract(a - orbit + 1.0) * 8.0;
            float comet = exp(-ca * ca) * band(r, 1.52, 0.02) * uProcessing;
            vec3 col = uRing * (track + arc * 1.8 + tip * 5.0 + comet * 3.0) + uLevelColor * lvl * 2.0;
            gl_FragColor = vec4(col * uOpacity, 1.0);
          }`,
      }),
    [],
  );

  useFrame(({ clock }, dt) => {
    const phase = useBlazam.getState().phase;
    const on = phase === "listening" || phase === "processing" ? 1 : 0;
    opacity.current += (on - opacity.current) * (1 - Math.exp(-dt * (on ? 6 : 2.5)));
    const u = material.uniforms;
    u.uTime.value = clock.elapsedTime;
    u.uProgress.value = phase === "listening" ? live.recordProgress : phase === "processing" ? 1 : u.uProgress.value;
    u.uLevel.value = live.micLevel;
    u.uProcessing.value += ((phase === "processing" ? 1 : 0) - u.uProcessing.value) * (1 - Math.exp(-dt * 4));
    u.uOpacity.value = opacity.current;
    if (mesh.current) mesh.current.visible = opacity.current > 0.002;
  });

  return (
    <mesh ref={mesh} position={[0, COIN_Y, 0]} material={material} renderOrder={4}>
      <planeGeometry args={[4, 4]} />
    </mesh>
  );
}
