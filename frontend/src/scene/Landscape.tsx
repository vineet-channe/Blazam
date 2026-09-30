"use client";

import { MeshReflectorMaterial } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useMemo } from "react";
import * as THREE from "three";
import { sceneColors } from "@/lib/theme";
import { mulberry32, poolDistance, terrainHeight } from "./terrain";

function Dunes() {
  const geometry = useMemo(() => {
    const geo = new THREE.PlaneGeometry(180, 140, 220, 170);
    geo.rotateX(-Math.PI / 2);
    geo.translate(0, 0, -45);
    const pos = geo.attributes.position as THREE.BufferAttribute;
    const colors = new Float32Array(pos.count * 3);
    const dark = new THREE.Color(sceneColors.dune);
    const lit = new THREE.Color(sceneColors.duneLit);
    const wet = new THREE.Color(sceneColors.pool);
    const c = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i);
      const z = pos.getZ(i);
      const h = terrainHeight(x, z);
      pos.setY(i, h);
      const crest = THREE.MathUtils.clamp((h - terrainHeight(x, z + 0.8)) * 3 + 0.5, 0, 1);
      c.copy(dark).lerp(lit, crest * 0.8);
      const shore = 1 - THREE.MathUtils.smoothstep(poolDistance(x, z), 0.9, 1.35);
      c.lerp(wet, shore * 0.8);
      colors.set([c.r, c.g, c.b], i * 3);
    }
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    geo.computeVertexNormals();
    return geo;
  }, []);

  return (
    <mesh geometry={geometry} receiveShadow={false}>
      <meshStandardMaterial vertexColors roughness={0.95} metalness={0} />
    </mesh>
  );
}

function Pool({ quality }: { quality: "high" | "medium" | "low" }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, -2]}>
      <planeGeometry args={[40, 30]} />
      <MeshReflectorMaterial
        resolution={quality === "high" ? 512 : quality === "medium" ? 256 : 128}
        // drei multiplies the reflection by the base color, so the tint is mid-tone, not black
        blur={[300, 90]}
        mixBlur={0.55}
        mixStrength={1.25}
        mixContrast={1.05}
        mirror={0.92}
        depthScale={0.8}
        minDepthThreshold={0.25}
        maxDepthThreshold={1.6}
        roughness={1}
        metalness={0}
        color={sceneColors.poolTint}
      />
    </mesh>
  );
}

/** Instanced agave-like clumps of tall blades; wind sway is added in the vertex shader. */
function Grass({ quality }: { quality: "high" | "medium" | "low" }) {
  const { geometry, material, matrices, count } = useMemo(() => {
    // tapered, slightly curved blade, 1 unit tall
    const seg = 5;
    const verts: number[] = [];
    const idx: number[] = [];
    for (let i = 0; i <= seg; i++) {
      const v = i / seg;
      const w = 0.06 * (1 - v) ** 1.2;
      const bend = v * v * 0.25;
      verts.push(-w, v, bend, w, v, bend);
      if (i < seg) {
        const a = i * 2;
        idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
    geo.setIndex(idx);
    geo.computeVertexNormals();

    const rand = mulberry32(7);
    const list: THREE.Matrix4[] = [];
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const e = new THREE.Euler();
    const s = new THREE.Vector3();
    const p = new THREE.Vector3();
    const addClump = (cx: number, cz: number, scale: number) => {
      const blades = 6 + Math.floor(rand() * 10);
      for (let b = 0; b < blades; b++) {
        const x = cx + (rand() - 0.5) * 0.35 * scale;
        const z = cz + (rand() - 0.5) * 0.35 * scale;
        const yaw = rand() * Math.PI * 2;
        const lean = 0.15 + rand() * 0.6;
        e.set(lean * Math.cos(yaw), yaw, lean * Math.sin(yaw));
        q.setFromEuler(e);
        const h = (0.6 + rand() * 1.6) * scale;
        s.set(scale * (0.8 + rand() * 0.6), h, scale);
        p.set(x, terrainHeight(x, z) - 0.05, z);
        list.push(m.compose(p, q, s).clone());
      }
    };
    const density = quality === "low" ? 0.45 : quality === "medium" ? 0.7 : 1;
    // foreground wings (left/right of the pool), midground band and sparse far dunes
    const bands: [xMin: number, xMax: number, zMin: number, zMax: number, n: number, scale: number][] = [
      [-11, -4.2, 0.5, 5.5, 26, 1.3],
      [4.2, 11, 0.5, 5.5, 26, 1.3],
      [-16, 16, -9, -3.5, 60, 1.05],
      [-30, 30, -24, -9, 80, 1.4],
      [-40, 40, -45, -24, 60, 2],
    ];
    for (const [x0, x1, z0, z1, n, scale] of bands) {
      for (let i = 0; i < Math.round(n * density); i++) {
        const x = x0 + rand() * (x1 - x0);
        const z = z0 + rand() * (z1 - z0);
        if (poolDistance(x, z) < 1.15) continue;
        addClump(x, z, scale * (0.7 + rand() * 0.6));
      }
    }

    const mat = new THREE.MeshStandardMaterial({ color: sceneColors.grass, roughness: 1, side: THREE.DoubleSide });
    const uniforms = { uTime: { value: 0 } };
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.uTime = uniforms.uTime;
      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", "#include <common>\nuniform float uTime;\nvarying float vH;")
        .replace(
          "#include <begin_vertex>",
          `#include <begin_vertex>
vec3 ip = vec3(instanceMatrix[3]);
float gust = sin(uTime * 0.7 + ip.x * 0.15) * 0.5 + 0.5;
transformed.x += sin(uTime * 1.6 + ip.x * 0.8 + ip.z * 0.6) * 0.07 * position.y * position.y * (0.5 + gust);
transformed.z += cos(uTime * 1.3 + ip.z * 0.9) * 0.04 * position.y * position.y;
vH = position.y;`,
        );
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <common>", "#include <common>\nvarying float vH;")
        .replace("#include <color_fragment>", `#include <color_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, vec3(${new THREE.Color(sceneColors.grassTip).toArray().map((v) => v.toFixed(4)).join(",")}), vH * 0.8);`);
    };
    mat.userData.uniforms = uniforms;
    return { geometry: geo, material: mat, matrices: list, count: list.length };
  }, [quality]);

  useFrame(({ clock }) => {
    (material.userData.uniforms as { uTime: { value: number } }).uTime.value = clock.elapsedTime;
  });

  return (
    <instancedMesh
      args={[geometry, material, count]}
      frustumCulled={false}
      ref={(mesh) => {
        if (!mesh) return;
        matrices.forEach((mx, i) => mesh.setMatrixAt(i, mx));
        mesh.instanceMatrix.needsUpdate = true;
      }}
    />
  );
}

export function Landscape({ quality }: { quality: "high" | "medium" | "low" }) {
  return (
    <group>
      <Dunes />
      <Pool quality={quality} />
      <Grass quality={quality} />
    </group>
  );
}
