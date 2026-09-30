"use client";

import { Sparkles } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";
import { palette, sceneColors } from "@/lib/theme";
import { valueNoise2 } from "./glsl";
import { mulberry32 } from "./terrain";

const hexToVec3 = (hex: string) => {
  const c = new THREE.Color(hex);
  return `vec3(${c.r.toFixed(4)}, ${c.g.toFixed(4)}, ${c.b.toFixed(4)})`;
};

/** Gradient sky dome with a hazy glow on the horizon behind the coin and drifting mist. */
function Sky() {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        side: THREE.BackSide,
        depthWrite: false,
        fog: false,
        uniforms: { uTime: { value: 0 } },
        vertexShader: /* glsl */ `
          varying vec3 vDir;
          void main() {
            vDir = normalize(position);
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: /* glsl */ `
          uniform float uTime;
          varying vec3 vDir;
          ${valueNoise2}
          void main() {
            vec3 d = normalize(vDir);
            float h = d.y;
            vec3 top = ${hexToVec3(sceneColors.skyTop)};
            vec3 hor = ${hexToVec3(palette.fog)};
            vec3 col = mix(hor, top, pow(smoothstep(-0.01, 0.26, h), 0.7));
            // glow low on the horizon, straight behind the coin
            float g = pow(max(dot(d, normalize(vec3(0.0, 0.04, -1.0))), 0.0), 10.0);
            float band = 1.0 - smoothstep(0.0, 0.16, h);
            col += ${hexToVec3(sceneColors.horizonGlow)} * g * band * 0.55;
            // slow mist bands
            vec2 uv = vec2(atan(d.x, -d.z) * 2.0, h * 7.0);
            float m = vfbm(uv * vec2(1.2, 1.0) + vec2(uTime * 0.01, 0.0));
            col = mix(col, ${hexToVec3(sceneColors.skyHorizon)}, m * 0.35 * (1.0 - smoothstep(0.0, 0.4, h)));
            gl_FragColor = vec4(col, 1.0);
            #include <colorspace_fragment>
          }`,
      }),
    [],
  );
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = clock.elapsedTime;
  });
  return (
    <mesh material={material} renderOrder={-1}>
      <sphereGeometry args={[90, 48, 24]} />
    </mesh>
  );
}

/** Soft volumetric-looking light shafts: additive gradient planes that slowly breathe. */
function LightShafts() {
  const material = useMemo(
    () =>
      new THREE.ShaderMaterial({
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        side: THREE.DoubleSide,
        fog: false,
        uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(sceneColors.shaft) } },
        vertexShader: /* glsl */ `
          varying vec2 vUv;
          varying float vSeed;
          attribute float aSeed;
          void main() {
            vUv = uv;
            vSeed = aSeed;
            gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0);
          }`,
        fragmentShader: /* glsl */ `
          uniform float uTime;
          uniform vec3 uColor;
          varying vec2 vUv;
          varying float vSeed;
          ${valueNoise2}
          void main() {
            float edge = smoothstep(0.0, 0.35, vUv.x) * (1.0 - smoothstep(0.65, 1.0, vUv.x));
            float fall = smoothstep(0.0, 0.5, vUv.y) * (1.0 - smoothstep(0.75, 1.0, vUv.y));
            float n = vnoise(vec2(vUv.x * 3.0 + vSeed * 10.0, vUv.y * 2.0 - uTime * 0.05));
            float breathe = 0.6 + 0.4 * sin(uTime * 0.25 + vSeed * 6.28);
            gl_FragColor = vec4(uColor * edge * fall * (0.5 + n) * breathe * 0.022, 1.0);
          }`,
      }),
    [],
  );
  const geometry = useMemo(() => {
    const g = new THREE.PlaneGeometry(1, 1);
    const seeds = new Float32Array([0.1, 0.4, 0.7, 0.9, 0.25]);
    g.setAttribute("aSeed", new THREE.InstancedBufferAttribute(seeds, 1));
    return g;
  }, []);
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = clock.elapsedTime;
  });
  const shafts: [x: number, z: number, w: number, rot: number][] = [
    [-7, -10, 2.8, 0.42],
    [-3.5, -12, 1.6, 0.38],
    [1.5, -14, 3.6, 0.4],
    [6, -11, 1.9, 0.44],
    [-11, -16, 4.5, 0.36],
  ];
  return (
    <instancedMesh
      args={[geometry, material, shafts.length]}
      frustumCulled={false}
      ref={(mesh) => {
        if (!mesh) return;
        const m = new THREE.Matrix4();
        shafts.forEach(([x, z, w, rot], i) => {
          m.compose(new THREE.Vector3(x, 7, z), new THREE.Quaternion().setFromEuler(new THREE.Euler(0, 0, rot)), new THREE.Vector3(w, 22, 1));
          mesh.setMatrixAt(i, m);
        });
        mesh.instanceMatrix.needsUpdate = true;
      }}
    />
  );
}

/** A few distant birds drifting across the haze, wings flapping. */
function Birds() {
  const birds = useMemo(() => {
    const rand = mulberry32(3);
    return Array.from({ length: 6 }, () => ({
      x: -30 + rand() * 60,
      y: 6 + rand() * 7,
      z: -22 - rand() * 18,
      speed: 0.6 + rand() * 0.8,
      phase: rand() * 10,
      flap: 5 + rand() * 3,
      scale: 0.25 + rand() * 0.2,
    }));
  }, []);
  const refs = useRef<(THREE.Group | null)[]>([]);
  const wing = useMemo(() => {
    const g = new THREE.BufferGeometry();
    // body along x, tip out along +z; the second wing is the same triangle yawed by PI
    g.setAttribute("position", new THREE.Float32BufferAttribute([0.14, 0, 0, -0.12, 0, 0, 0.06, 0.06, 1], 3));
    return g;
  }, []);
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ color: sceneColors.bird, side: THREE.DoubleSide }), []);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    birds.forEach((b, i) => {
      const g = refs.current[i];
      if (!g) return;
      const x = ((b.x + t * b.speed + 40) % 80) - 40;
      g.position.set(x, b.y + Math.sin(t * 0.4 + b.phase) * 0.6, b.z);
      const flap = Math.sin(t * b.flap + b.phase) * 0.55;
      const [l, r] = g.children;
      l.rotation.x = flap;
      r.rotation.x = -flap;
    });
  });
  return (
    <>
      {birds.map((b, i) => (
        <group
          key={i}
          ref={(g) => {
            refs.current[i] = g;
          }}
          scale={b.scale}
          rotation={[0.25, 0.85, 0]}
        >
          <mesh geometry={wing} material={mat} />
          <mesh geometry={wing} material={mat} rotation={[0, Math.PI, 0]} />
        </group>
      ))}
    </>
  );
}

export function Atmosphere({ dust }: { dust: number }) {
  return (
    <>
      <Sky />
      <LightShafts />
      <Birds />
      <Sparkles count={dust} scale={[16, 5, 12]} position={[0, 2.4, -1]} size={2.2} speed={0.18} opacity={0.55} noise={0.6} color={sceneColors.dust} />
    </>
  );
}
