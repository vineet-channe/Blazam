import * as THREE from "three";

export const COIN_RADIUS = 1.15;
export const COIN_HALF_THICKNESS = 0.16;
/** z of the flat field on each face, where the embossed letter sits */
export const COIN_FIELD_Z = COIN_HALF_THICKNESS - 0.012;

const RIDGES = 160;
const SEGMENTS = RIDGES * 4;
const RIDGE_DEPTH = 0.009;

/**
 * Coin body as a lathe: dished field, raised inner ring, raised outer lip, bevel and a
 * knurled (ridged) edge. Profile points are doubled at hard edges so vertex normals do not
 * smooth across them. The lathe spins around Y, so the result is rotated to face +Z.
 */
export function createCoinGeometry(): THREE.BufferGeometry {
  const H = COIN_HALF_THICKNESS;
  const f = COIN_FIELD_Z;
  const R = COIN_RADIUS;
  const half: [number, number][] = [
    [0.0001, f - 0.012],
    [0.35, f - 0.008],
    [0.7, f - 0.002],
    [0.8, f],
    [0.8, f],
    [0.812, f + 0.028],
    [0.812, f + 0.028],
    [0.858, f + 0.028],
    [0.858, f + 0.028],
    [0.87, f],
    [0.87, f],
    [0.975, f],
    [0.975, f],
    [0.99, H + 0.03],
    [0.99, H + 0.03],
    [1.09, H + 0.03],
    [1.12, H + 0.018],
    [1.14, H - 0.004],
    [R, H - 0.03],
    [R, H - 0.03],
  ];
  // mirror the top half into a closed profile running bottom center -> top center, the
  // direction LatheGeometry needs for outward-facing triangles
  const bottom = half.map(([r, y]) => [r, -y] as [number, number]);
  const profile = [...bottom, ...half.slice().reverse()].map(
    ([r, y]) => new THREE.Vector2(r, y),
  );

  const geo = new THREE.LatheGeometry(profile, SEGMENTS);
  const pos = geo.attributes.position as THREE.BufferAttribute;
  const v = new THREE.Vector3();
  for (let i = 0; i < pos.count; i++) {
    v.fromBufferAttribute(pos, i);
    const r = Math.hypot(v.x, v.z);
    // knurling only on the vertical edge band
    if (r > R - 0.001 && Math.abs(v.y) < H - 0.02) {
      const a = Math.atan2(v.z, v.x);
      const ridge = Math.pow(Math.abs(Math.cos(a * RIDGES * 0.5)), 0.6);
      const nr = r - RIDGE_DEPTH * (1 - ridge);
      pos.setXYZ(i, (v.x / r) * nr, v.y, (v.z / r) * nr);
    }
  }
  geo.computeVertexNormals();
  geo.rotateX(Math.PI / 2);
  return geo;
}
