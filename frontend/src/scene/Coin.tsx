"use client";

import { Center, Text3D } from "@react-three/drei";
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { toggleListen } from "@/lib/controller";
import { live } from "@/lib/live";
import { useBlazam, type Phase } from "@/lib/store";
import { sceneColors } from "@/lib/theme";
import { COIN_FIELD_Z, createCoinGeometry } from "./coinGeometry";
import { createCoinMaterial } from "./coinMaterial";
import { sceneRefs } from "./refs";

export const COIN_Y = 1.3;
const TAU = Math.PI * 2;

type SpinState = {
  angle: number;
  vel: number;
  mode: "drive" | "settle";
  target: number;
  bounceY: number;
  bounceV: number;
  lastImpulse: number;
  flash: number;
  dull: number;
  reveal: number;
};

/** Critically / under-damped spring step toward `target`; returns new [x, v]. */
function spring(x: number, v: number, target: number, k: number, zeta: number, dt: number): [number, number] {
  const c = 2 * zeta * Math.sqrt(k);
  const a = k * (target - x) - c * v;
  const nv = v + a * dt;
  return [x + nv * dt, nv];
}

export function Coin({ reducedMotion }: { reducedMotion: boolean }) {
  const outer = useRef<THREE.Group>(null);
  const spinner = useRef<THREE.Group>(null);
  const glowLight = useRef<THREE.PointLight>(null);
  const geometry = useMemo(() => createCoinGeometry(), []);
  const { material, uniforms } = useMemo(() => createCoinMaterial(), []);
  const letter = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: sceneColors.letter,
        emissive: sceneColors.letter,
        emissiveIntensity: 0.9,
        roughness: 0.45,
        metalness: 0,
      }),
    [],
  );
  const letterBase = useMemo(() => new THREE.Color(sceneColors.letter), []);
  const phaseRef = useRef<Phase>(useBlazam.getState().phase);
  const s = useRef<SpinState>({
    angle: 0,
    vel: 0,
    mode: "settle",
    target: 0,
    bounceY: 0,
    bounceV: 0,
    lastImpulse: live.impulse,
    flash: 0,
    dull: 0,
    reveal: 0,
  });

  const peak = reducedMotion ? 7 : 25;

  useEffect(() => {
    return useBlazam.subscribe((state) => {
      const prev = phaseRef.current;
      const next = state.phase;
      if (prev === next) return;
      phaseRef.current = next;
      const st = s.current;
      if (next === "listening" || next === "processing") {
        st.mode = "drive";
      } else {
        // settle on the nearest face ahead of where momentum would carry the coin
        st.mode = "settle";
        const ahead = st.angle + st.vel * 0.3;
        st.target = Math.ceil(ahead / Math.PI) * Math.PI + (next === "reveal" && !reducedMotion ? TAU : 0);
        if (next === "reveal") st.flash = 1;
      }
    });
  }, [reducedMotion]);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
      letter.dispose();
    },
    [geometry, material, letter],
  );

  useFrame((state, rawDt) => {
    const dt = Math.min(rawDt, 1 / 30);
    const t = state.clock.elapsedTime;
    const st = s.current;
    const phase = phaseRef.current;
    const { introStarted } = useBlazam.getState();

    // click impulse: instant kick plus a vertical hop
    if (live.impulse !== st.lastImpulse) {
      st.lastImpulse = live.impulse;
      st.vel += reducedMotion ? 3 : 9;
      if (!reducedMotion) st.bounceV += 3.4;
    }

    if (st.mode === "drive") {
      const target = phase === "listening" ? peak * (0.92 + live.micLevel * 0.12) : 2.4;
      const rate = phase === "listening" ? 2.4 : 1.1;
      st.vel += (target - st.vel) * (1 - Math.exp(-dt * rate));
      st.angle += st.vel * dt;
    } else {
      const k = phase === "reveal" ? 16 : phase === "no_match" ? 10 : 7;
      const zeta = phase === "reveal" ? 0.32 : phase === "no_match" ? 0.55 : 0.7;
      [st.angle, st.vel] = spring(st.angle, st.vel, st.target, k, zeta, dt);
      if (phase === "no_match" && Math.abs(st.vel) > 0.4 && !reducedMotion) {
        st.vel += (Math.random() - 0.5) * 14 * dt; // sputter
      }
    }
    live.spin = Math.min(1, Math.abs(st.vel) / 25);

    [st.bounceY, st.bounceV] = spring(st.bounceY, st.bounceV, 0, 55, 0.28, dt);
    st.flash = Math.max(0, st.flash - dt * 0.9);
    const wantDull = phase === "no_match" ? 1 : phase === "error" ? 0.6 : 0;
    st.dull += (wantDull - st.dull) * (1 - Math.exp(-dt * 1.6));
    if (introStarted) st.reveal = Math.min(1, st.reveal + dt / 3.2);
    const revealEased = st.reveal * st.reveal * (3 - 2 * st.reveal);

    const spinner_ = spinner.current;
    const outer_ = outer.current;
    if (!spinner_ || !outer_) return;

    // spin plus precession wobble that grows with speed
    const wob = reducedMotion ? 0 : live.spin;
    spinner_.rotation.set(Math.sin(t * 7.1) * 0.07 * wob, st.angle, Math.cos(t * 5.3) * 0.06 * wob);

    // idle float, sway and pointer/gyro parallax; tilt toward the cursor when hovered
    const hover = live.hover;
    const px = live.pointer.x + live.tilt.x;
    const py = live.pointer.y + live.tilt.y;
    const calm = 1 - live.spin;
    const floatY = reducedMotion ? 0 : Math.sin(t * 0.8) * 0.07;
    outer_.position.y = COIN_Y + floatY + st.bounceY * 0.35 + (1 - revealEased) * -0.4;
    const tiltY = (px * 0.22 + hover * px * 0.25) * calm;
    const tiltX = (-py * 0.14 - hover * py * 0.2) * calm;
    outer_.rotation.y += (tiltY - outer_.rotation.y) * (1 - Math.exp(-dt * 4));
    outer_.rotation.x += (tiltX - outer_.rotation.x) * (1 - Math.exp(-dt * 4));
    outer_.rotation.z = reducedMotion ? 0 : Math.sin(t * 0.5) * 0.035 * calm;

    const breathing = reducedMotion ? 0.04 : 0.14;
    const pulse = phase === "processing" ? 0.35 * (0.5 + 0.5 * Math.sin(t * 5)) : 0;
    const glow = 1 + Math.sin(t * 1.2) * breathing + hover * 0.5 + live.spin * 0.9 + pulse + st.flash * 1.4 + live.micLevel * 0.4 * live.spin;
    uniforms.uTime.value = t;
    uniforms.uGlow.value = glow;
    uniforms.uReveal.value = revealEased;
    uniforms.uDull.value = st.dull;

    letter.emissiveIntensity = (0.85 + live.spin * 1.6 + hover * 0.8 + st.flash * 3 + pulse * 1.4) * (1 - st.dull * 0.75) * revealEased;
    letter.color.copy(letterBase).multiplyScalar(revealEased);
    if (glowLight.current) glowLight.current.intensity = (3 + glow * 3) * revealEased * (1 - st.dull * 0.6);
  });

  const onOver = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    live.hover = 1;
    useBlazam.getState().set({ coinHover: true });
  };
  const onOut = () => {
    live.hover = 0;
    useBlazam.getState().set({ coinHover: false });
  };
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    toggleListen();
  };

  return (
    <group ref={outer} position={[0, COIN_Y, 0]}>
      <pointLight ref={glowLight} color={sceneColors.coinRim} distance={9} decay={1.6} position={[0, 0, 0.8]} />
      <group
        ref={(g) => {
          spinner.current = g;
          sceneRefs.coin = g;
        }}
      >
        <mesh geometry={geometry} material={material} onPointerOver={onOver} onPointerOut={onOut} onClick={onClick} castShadow={false} />
        {[1, -1].map((side) => (
          <group key={side} position={[0, 0, side * COIN_FIELD_Z]} rotation={[0, side === 1 ? 0 : Math.PI, 0]}>
            <Center disableZ>
              <Text3D
                material={letter}
                font="/fonts/coin-b.typeface.json"
                size={1.02}
                height={0.045}
                curveSegments={10}
                bevelEnabled
                bevelThickness={0.018}
                bevelSize={0.012}
                bevelSegments={3}
              >
                B
              </Text3D>
            </Center>
          </group>
        ))}
      </group>
    </group>
  );
}
