"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import { live } from "@/lib/live";
import { useBlazam } from "@/lib/store";
import { COIN_Y } from "./Coin";

const INTRO_FROM = new THREE.Vector3(0, 2.6, 17);
const HOME = new THREE.Vector3(0, 1.25, 7.6);
const INTRO_SECONDS = 5.5;

const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * Slow intro push-in, pointer/gyro parallax, reveal dolly (framing the coin beside the result
 * card), and camera shake at peak spin (skipped under prefers-reduced-motion).
 */
export function CameraRig({ reducedMotion }: { reducedMotion: boolean }) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const st = useRef({ intro: 0, dolly: 0, pos: INTRO_FROM.clone(), look: new THREE.Vector3(0, COIN_Y, 0) });
  const goal = useRef(new THREE.Vector3());
  const lookGoal = useRef(new THREE.Vector3());

  useFrame((state, rawDt) => {
    const dt = Math.min(rawDt, 1 / 30);
    const s = st.current;
    const { introStarted, phase } = useBlazam.getState();
    if (introStarted) s.intro = Math.min(1, s.intro + dt / (reducedMotion ? 1.5 : INTRO_SECONDS));
    const k = ease(s.intro);

    // outcomes (card or panel on the right) reframe the coin to the left
    const revealing = phase === "reveal" || phase === "no_match" || phase === "error" ? 1 : 0;
    s.dolly += (revealing - s.dolly) * (1 - Math.exp(-dt * 1.6));
    const wide = size.width / size.height > 1.05;

    // intro path
    goal.current.lerpVectors(INTRO_FROM, HOME, k);
    lookGoal.current.set(0, COIN_Y - 0.4, 0);

    // reveal: ease in and frame the coin left of the card (wide) or above the sheet (narrow)
    if (wide) {
      goal.current.x += 1.55 * s.dolly;
      goal.current.z -= 0.6 * s.dolly;
      lookGoal.current.x += 1.9 * s.dolly;
    } else {
      goal.current.z += 1.2 * s.dolly;
      goal.current.y += 0.2 * s.dolly;
      lookGoal.current.y -= 1.35 * s.dolly;
    }

    // non-home routes and narrow screens pull back a little so the coin stays in frame
    if (!wide) goal.current.z += 2.2 * k;

    // parallax
    const px = live.pointer.x + live.tilt.x;
    const py = live.pointer.y + live.tilt.y;
    const par = reducedMotion ? 0.1 : 0.4;
    goal.current.x += px * par * k;
    goal.current.y += py * par * 0.5 * k;

    s.pos.lerp(goal.current, 1 - Math.exp(-dt * 2.2));
    s.look.lerp(lookGoal.current, 1 - Math.exp(-dt * 2.2));
    camera.position.copy(s.pos);

    // shake at peak spin
    if (!reducedMotion) {
      const peak = Math.max(0, live.spin - 0.72) / 0.28;
      const amp = 0.035 * peak * (0.6 + live.micLevel);
      const t = state.clock.elapsedTime;
      camera.position.x += Math.sin(t * 47.3) * amp + Math.sin(t * 23.1) * amp * 0.6;
      camera.position.y += Math.cos(t * 41.7) * amp;
    }
    camera.lookAt(s.look);
  });

  return null;
}
