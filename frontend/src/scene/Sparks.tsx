"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { live } from "@/lib/live";
import { useBlazam } from "@/lib/store";
import { ACTIVE_SPARK_RAMP, SMOKE } from "@/lib/theme";
import { COIN_HALF_THICKNESS, COIN_RADIUS } from "./coinGeometry";
import { sceneRefs } from "./refs";

/**
 * GPU sparks. Each particle is one instance of a quad; the CPU only writes its birth state
 * (position, velocity, birth time, life, seed) into a ring buffer when it is emitted. The
 * vertex shader integrates motion analytically (gravity or heat buoyancy + linear drag +
 * turbulence), projects the head and a slightly older tail position and stretches the quad
 * between them, so fast sparks read as streaks and slow embers as dots.
 *
 * Two instances of the system run: "fire" (additive, white-hot -> ember ramp) and "smoke"
 * (normal blending, grey-green puffs used when a recognition fails).
 */

const vertexShader = /* glsl */ `
attribute vec3 aP0;
attribute vec3 aV0;
attribute vec4 aMeta; // birth time, life, seed, buoyancy
uniform float uTime, uDrag, uGravity, uSize, uPixelRatio, uTrail, uSmoke, uViewHeight;
varying vec2 vUv;
varying float vAge;
varying float vSeed;
varying float vDepth;
varying float vWater;

vec3 posAt(float t) {
  float k = uDrag * (1.0 + uSmoke * 1.5);
  float e = (1.0 - exp(-k * t)) / k;
  vec3 acc = vec3(0.0, -uGravity + aMeta.w, 0.0);
  vec3 p = aP0 + aV0 * e + acc * (t - e) / k;
  float s = aMeta.z * 43.0;
  p += vec3(sin(t * 3.1 + s), sin(t * 2.3 + s * 1.7) * 0.6, cos(t * 2.7 + s * 2.3)) * (0.18 + uSmoke * 0.5) * t * t;
  return p;
}

void main() {
  // locals only: never read varyings back in the vertex stage (breaks on ANGLE/Metal)
  float age = uTime - aMeta.x;
  float life = aMeta.y;
  float ageN = age / life;
  float seed = aMeta.z;
  vAge = ageN;
  vSeed = seed;
  // quad coords from position (x: -0.5..0.5 across, y: 0..1 tail -> head)
  vUv = vec2(position.x + 0.5, position.y);
  if (age < 0.0 || ageN > 1.0 || life <= 0.0) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); return; }

  vec3 head = posAt(age);
  vec3 tail = posAt(max(age - uTrail * (1.0 - uSmoke), 0.0));
  // a spark that falls into the pool is quenched
  vWater = 1.0 - smoothstep(-0.05, 0.05, head.y);

  mat4 vp = projectionMatrix * viewMatrix;
  vec4 ch = vp * vec4(head, 1.0);
  vec4 ct = vp * vec4(tail, 1.0);
  vDepth = ch.w;
  vec2 sh = ch.xy / ch.w;
  vec2 st = ct.xy / ct.w;
  // aspect straight from the projection matrix (x scale = y scale / aspect)
  vec2 aspect = vec2(projectionMatrix[1][1] / projectionMatrix[0][0], 1.0);
  vec2 d = (sh - st) * aspect;
  float len = length(d);
  // never divide by zero, even in the unused branch of a select: smoke has head == tail, and a
  // NaN vertex turns into a NaN pixel that bloom smears into a black block
  vec2 dir = mix(vec2(0.0, 1.0), d / max(len, 1e-4), step(1e-4, len));
  // (perp, dir) must stay right-handed like the quad's (x, y), or the quad is mirrored and culled
  vec2 perp = vec2(dir.y, -dir.x);

  float grow = mix(1.0, 1.0 + ageN * 6.0, uSmoke);
  float sizePx = uSize * uPixelRatio * (0.5 + fract(seed * 7.13)) * grow * mix(1.0 - ageN * 0.5, 1.0, uSmoke);
  float w = sizePx / uViewHeight * 2.0;
  // quad: x across (-0.5..0.5), y along tail (0) -> head (1), padded by w at both ends
  vec4 c = mix(ct, ch, position.y);
  vec2 along = dir * (position.y - 0.5) * w;
  vec2 across = perp * position.x * w;
  c.xy += (along + across) / aspect * c.w;
  gl_Position = c;
}
`;

const fragmentShader = /* glsl */ `
uniform vec3 uHot, uGold, uOrange, uEmber, uSmokeColor;
uniform float uTime, uBright, uSmoke, uFogDensity;
varying vec2 vUv;
varying float vAge;
varying float vSeed;
varying float vDepth;
varying float vWater;

vec3 ramp(float a) {
  if (a < 0.12) return mix(uHot, uGold, a / 0.12);
  if (a < 0.42) return mix(uGold, uOrange, (a - 0.12) / 0.3);
  return mix(uOrange, uEmber, (a - 0.42) / 0.58);
}

void main() {
  float fog = exp(-uFogDensity * uFogDensity * vDepth * vDepth);
  vec2 q = vec2(vUv.x - 0.5, vUv.y - 0.5) * 2.0;
  if (uSmoke > 0.5) {
    float r = length(q);
    float a = (1.0 - smoothstep(0.0, 1.0, r)) * (1.0 - vAge) * smoothstep(0.0, 0.15, vAge) * 0.45;
    gl_FragColor = vec4(uSmokeColor, a * mix(0.6, 1.0, fog));
    return;
  }
  // soft capsule, brighter toward the head
  float across = 1.0 - abs(q.x);
  float body = pow(max(across, 0.0), 2.2) * smoothstep(-1.0, -0.2, q.y) * (1.0 - smoothstep(0.6, 1.0, q.y));
  float flicker = 0.65 + 0.35 * sin(uTime * (22.0 + vSeed * 30.0) + vSeed * 90.0);
  float fade = pow(clamp(1.0 - vAge, 0.0, 1.0), 1.4);
  // fire writes depth (so depth of field keeps sparks sharp at the coin's distance instead of
  // blurring them with the sky behind); drop the faint fringe so it doesn't occlude
  if (body < 0.04) discard;
  vec3 col = ramp(vAge) * body * fade * flicker * uBright * (1.0 - vWater);
  gl_FragColor = vec4(col * mix(0.25, 1.0, fog), 1.0);
}
`;

type Props = { kind: "fire" | "smoke"; count: number; reducedMotion: boolean };

export function Sparks({ kind, count, reducedMotion }: Props) {
  const mesh = useRef<THREE.Mesh>(null);
  const light = useRef<THREE.PointLight>(null);
  const size = useThree((st) => st.size);
  const smoke = kind === "smoke";

  const { geometry, material, p0, v0, meta } = useMemo(() => {
    const base = new THREE.PlaneGeometry(1, 1, 1, 1);
    base.translate(0, 0.5, 0);
    const geo = new THREE.InstancedBufferGeometry();
    geo.index = base.index;
    geo.setAttribute("position", base.attributes.position);
    const p0 = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3).setUsage(THREE.DynamicDrawUsage);
    const v0 = new THREE.InstancedBufferAttribute(new Float32Array(count * 3), 3).setUsage(THREE.DynamicDrawUsage);
    const meta = new THREE.InstancedBufferAttribute(new Float32Array(count * 4), 4).setUsage(THREE.DynamicDrawUsage);
    for (let i = 0; i < count; i++) meta.setXYZW(i, -1000, 0, 0, 0);
    geo.setAttribute("aP0", p0);
    geo.setAttribute("aV0", v0);
    geo.setAttribute("aMeta", meta);
    geo.instanceCount = count;
    const ramp = ACTIVE_SPARK_RAMP;
    const mat = new THREE.ShaderMaterial({
      vertexShader,
      fragmentShader,
      transparent: true,
      depthWrite: !smoke,
      // double-sided: the pool's mirrored reflection camera flips triangle winding
      side: THREE.DoubleSide,
      blending: smoke ? THREE.NormalBlending : THREE.AdditiveBlending,
      uniforms: {
        uTime: { value: 0 },
        uDrag: { value: smoke ? 1.2 : 2.1 },
        uGravity: { value: smoke ? 0 : 7.5 },
        uSize: { value: smoke ? 26 : 2.4 },
        uPixelRatio: { value: 1 },
        uTrail: { value: 0.035 },
        uSmoke: { value: smoke ? 1 : 0 },
        uViewHeight: { value: 900 },
        uBright: { value: 1 },
        uFogDensity: { value: 0.045 },
        uHot: { value: new THREE.Color(ramp.hot).multiplyScalar(4.5) },
        uGold: { value: new THREE.Color(ramp.gold).multiplyScalar(3.2) },
        uOrange: { value: new THREE.Color(ramp.orange).multiplyScalar(2.2) },
        uEmber: { value: new THREE.Color(ramp.ember).multiplyScalar(1.2) },
        uSmokeColor: { value: new THREE.Color(SMOKE) },
      },
    });
    return { geometry: geo, material: mat, p0, v0, meta };
  }, [count, smoke]);

  useEffect(
    () => () => {
      geometry.dispose();
      material.dispose();
    },
    [geometry, material],
  );

  const emitter = useRef({ cursor: 0, carry: 0, lastBurst: live.burst.id, heat: 0 });
  const tmp = useMemo(
    () => ({ local: new THREE.Vector3(), world: new THREE.Vector3(), center: new THREE.Vector3(), out: new THREE.Vector3() }),
    [],
  );

  useFrame((state, rawDt) => {
    const dt = Math.min(rawDt, 1 / 30);
    const t = state.clock.elapsedTime;
    const u = material.uniforms;
    u.uTime.value = t;
    u.uPixelRatio.value = state.gl.getPixelRatio();
    u.uViewHeight.value = size.height * state.gl.getPixelRatio();
    u.uBright.value = 1 + live.micLevel * 1.8;

    const coin = sceneRefs.coin;
    const e = emitter.current;
    if (!coin) return;
    coin.updateWorldMatrix(true, false);
    tmp.center.setFromMatrixPosition(coin.matrixWorld);
    const phase = useBlazam.getState().phase;
    const omega = live.spin * 25;

    // continuous emission follows spin speed and the live mic level
    let n = 0;
    if (!smoke) {
      const drive = phase === "listening" || phase === "processing" ? Math.pow(live.spin, 1.4) : 0;
      const rate = drive * (0.35 + 1.65 * live.micLevel) * (reducedMotion ? 140 : 700);
      e.carry += rate * dt;
      n = Math.floor(e.carry);
      e.carry -= n;
      e.heat += (Math.min(1, rate / 900) - e.heat) * (1 - Math.exp(-dt * 6));
    } else if (phase === "no_match") {
      e.carry += (reducedMotion ? 6 : 22) * dt * Math.max(0.2, live.spin * 3);
      n = Math.floor(e.carry);
      e.carry -= n;
    }

    // bursts: on click, on reveal (fire) and on failure (smoke)
    let burst = 0;
    let burstStrength = 1;
    if (live.burst.id !== e.lastBurst) {
      e.lastBurst = live.burst.id;
      if ((live.burst.kind === "smoke") === smoke) {
        burstStrength = live.burst.strength;
        burst = Math.round((smoke ? 60 : 650) * burstStrength * (reducedMotion ? 0.25 : 1));
      }
    }

    const total = Math.min(n + burst, count);
    if (total > 0) {
      const start = e.cursor;
      for (let i = 0; i < total; i++) {
        const idx = e.cursor;
        e.cursor = (e.cursor + 1) % count;
        const isBurst = i >= n;
        const a = Math.random() * Math.PI * 2;
        const z = (Math.random() * 2 - 1) * COIN_HALF_THICKNESS;
        tmp.local.set(Math.cos(a) * COIN_RADIUS, Math.sin(a) * COIN_RADIUS, z);
        tmp.world.copy(tmp.local).applyMatrix4(coin.matrixWorld);
        const rx = tmp.world.x - tmp.center.x;
        const rz = tmp.world.z - tmp.center.z;
        tmp.out.copy(tmp.world).sub(tmp.center).normalize();
        let vx: number, vy: number, vz: number;
        if (smoke) {
          vx = tmp.out.x * 0.5 + (Math.random() - 0.5) * 0.4;
          vy = 0.6 + Math.random() * 0.8;
          vz = tmp.out.z * 0.5 + (Math.random() - 0.5) * 0.4;
        } else if (isBurst) {
          const sp = (2.5 + Math.random() * 5.5) * burstStrength;
          vx = tmp.out.x * sp + (Math.random() - 0.5) * 3;
          vy = tmp.out.y * sp + 1.5 + Math.random() * 3;
          vz = tmp.out.z * sp + (Math.random() - 0.5) * 3;
        } else {
          // tangential velocity of a point on a disc spinning about world Y, plus flung-off
          // radial speed and upward heat drift
          const tang = 0.2;
          const radial = 0.6 + Math.random() * 1.8;
          vx = omega * rz * tang + tmp.out.x * radial + (Math.random() - 0.5) * 1.2;
          vy = tmp.out.y * radial + 0.6 + Math.random() * 2.2;
          vz = -omega * rx * tang + tmp.out.z * radial + (Math.random() - 0.5) * 1.2;
        }
        p0.setXYZ(idx, tmp.world.x, tmp.world.y, tmp.world.z);
        v0.setXYZ(idx, vx, vy, vz);
        // 35% are light embers that rise on the heat instead of falling
        const ember = !smoke && Math.random() < 0.3;
        const life = smoke ? 2.2 + Math.random() * 1.8 : ember ? 1.2 + Math.random() * 1.4 : 0.35 + Math.random() * 0.7;
        const buoy = smoke ? 0.4 : ember ? 8 + Math.random() * 2.5 : Math.random() * 1.5;
        meta.setXYZW(idx, t - Math.random() * dt, life, Math.random(), buoy);
      }
      // upload only the touched slice(s) of the ring buffer
      const ranges: [number, number][] = start + total <= count ? [[start, total]] : [[start, count - start], [0, total - (count - start)]];
      for (const attr of [p0, v0, meta]) {
        attr.clearUpdateRanges();
        for (const [s0, c] of ranges) attr.addUpdateRange(s0 * attr.itemSize, c * attr.itemSize);
        attr.needsUpdate = true;
      }
    }

    // sparks light the fog, the grass and the pool around the coin
    if (light.current) {
      const flash = burst > 0 && !smoke ? 1 : 0;
      light.current.intensity = THREE.MathUtils.damp(light.current.intensity, (e.heat * 14 + flash * 30) * (1 + live.micLevel), 8, dt);
      light.current.position.copy(tmp.center);
    }
  });

  return (
    <>
      <mesh ref={mesh} geometry={geometry} material={material} frustumCulled={false} renderOrder={smoke ? 2 : 3} />
      {!smoke && <pointLight ref={light} color={ACTIVE_SPARK_RAMP.orange} distance={10} decay={1.4} intensity={0} />}
    </>
  );
}
