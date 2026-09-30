import * as THREE from "three";
import { sceneColors } from "@/lib/theme";
import { simplex3 } from "./glsl";

export type CoinUniforms = {
  uTime: { value: number };
  /** overall inner light, breathes and follows spin */
  uGlow: { value: number };
  /** 0 -> 1 while the coin fades up from darkness in the intro */
  uReveal: { value: number };
  /** 0 = healthy emerald, 1 = dull grey-green (no-match sputter) */
  uDull: { value: number };
  uBase: { value: THREE.Color };
  uPale: { value: THREE.Color };
  uVein: { value: THREE.Color };
  uRim: { value: THREE.Color };
};

/**
 * Marbled translucent emerald: MeshPhysicalMaterial (transmission, ior 1.45, clearcoat) with
 * its color and emissive terms replaced by domain-warped fbm marble whose dark veins drift
 * slowly, plus a fresnel rim, a sweeping rim light and an emissive "lamp inside the stone".
 */
export function createCoinMaterial(): { material: THREE.MeshPhysicalMaterial; uniforms: CoinUniforms } {
  const uniforms: CoinUniforms = {
    uTime: { value: 0 },
    uGlow: { value: 1 },
    uReveal: { value: 0 },
    uDull: { value: 0 },
    uBase: { value: new THREE.Color(sceneColors.coinBase) },
    uPale: { value: new THREE.Color(sceneColors.coinPale) },
    uVein: { value: new THREE.Color(sceneColors.coinVein) },
    uRim: { value: new THREE.Color(sceneColors.coinRim) },
  };

  const material = new THREE.MeshPhysicalMaterial({
    color: sceneColors.coinBase,
    roughness: 0.38,
    metalness: 0,
    // light transmission (ior 1.45, like alabaster/jade); the "lit from within" look comes from
    // the emissive lamp term below, which is far cheaper than a thick transmission pass
    transmission: 0.12,
    thickness: 0.6,
    ior: 1.45,
    attenuationColor: new THREE.Color(sceneColors.coinVein),
    attenuationDistance: 0.8,
    envMapIntensity: 0.55,
    clearcoat: 1,
    clearcoatRoughness: 0.12,
    sheen: 0.4,
    sheenColor: new THREE.Color(sceneColors.coinPale),
    emissive: new THREE.Color("#ffffff"),
  });

  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vObj;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvObj = position;");

    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>
varying vec3 vObj;
uniform float uTime, uGlow, uReveal, uDull;
uniform vec3 uBase, uPale, uVein, uRim;
${simplex3}
float gBand; float gVein;`,
      )
      .replace(
        "#include <color_fragment>",
        `#include <color_fragment>
{
  // stretched along x for the broad horizontal bands of alabaster
  vec3 p = vObj * vec3(0.42, 0.95, 1.6);
  float t = uTime * 0.045;
  // domain warp twice (Inigo Quilez) for folded, stone-like bands
  vec3 q = vec3(fbm(p + vec3(0.0, 0.0, t)), fbm(p + vec3(5.2, 1.3, -t)), 0.0) * 0.8;
  vec3 r = vec3(fbm(p + 2.6 * q + vec3(1.7, 9.2, t * 1.3)), fbm(p + 2.6 * q + vec3(8.3, 2.8, -t * 0.8)), 0.0);
  float f = fbm(p * 0.9 + 2.2 * r);
  // warped horizontal strata, like the bands in alabaster
  float strata = 0.5 + 0.5 * sin(vObj.y * 8.5 + 4.0 * (q.x - 0.4) + 3.0 * (r.y - 0.5) + t * 3.0);
  gBand = smoothstep(0.32, 0.78, mix(f, strata, 0.55));
  // veins: contour lines of the warped field (several per band), plus a finer secondary set
  float v1 = (1.0 - smoothstep(0.0, 0.07, abs(fract(f * 4.0 + strata * 0.35) - 0.5) * 2.0)) * 0.85;
  float v2 = 1.0 - smoothstep(0.0, 0.014, abs(fbm(p * 3.4 + 2.0 * q) - 0.5));
  gVein = clamp(v1 + v2 * 0.45, 0.0, 1.0);
  vec3 marble = mix(mix(uVein, uBase, 0.55), uPale, gBand * gBand);
  marble = mix(marble, uVein, gVein * 0.75);
  marble = mix(marble, vec3(dot(marble, vec3(0.3, 0.59, 0.11))) * vec3(0.55, 0.68, 0.6), uDull);
  diffuseColor.rgb = marble * uReveal;
}`,
      )
      .replace(
        "#include <emissivemap_fragment>",
        `#include <emissivemap_fragment>
{
  vec3 V = normalize(vViewPosition);
  float ndv = clamp(abs(dot(normal, V)), 0.0, 1.0);
  float fres = pow(1.0 - ndv, 3.0);
  // light scattered inside the stone: brightest in pale bands, blocked by veins
  float inner = (0.08 + 0.92 * gBand * gBand) * (1.0 - gVein * 0.9);
  vec3 lamp = mix(uBase, uPale, gBand) * inner * uGlow * 0.5;
  // sweeping rim light across the face
  float sweepPos = sin(uTime * 0.35) * 1.8;
  float sd = vObj.x * 0.85 + vObj.y * 0.5 - sweepPos;
  float sweep = exp(-sd * sd * 5.0);
  vec3 rim = uRim * (fres * (0.25 + 0.3 * uGlow) + sweep * (0.05 + fres) * 0.35);
  totalEmissiveRadiance = (lamp + rim) * (1.0 - uDull * 0.7) * uReveal;
}`,
      );
  };
  material.customProgramCacheKey = () => "blazam-coin-v1";

  return { material, uniforms };
}
