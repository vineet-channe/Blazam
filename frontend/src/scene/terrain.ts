/**
 * Deterministic terrain height, shared by the dune mesh and the grass placement so every
 * blade sits exactly on the ground. The pool is a bowl carved below y = 0 around the coin;
 * the water plane at y = 0 shows through wherever the ground dips under it.
 */

function hash(x: number, y: number) {
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function noise(x: number, y: number) {
  const ix = Math.floor(x);
  const iy = Math.floor(y);
  const fx = x - ix;
  const fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx);
  const uy = fy * fy * (3 - 2 * fy);
  const a = hash(ix, iy);
  const b = hash(ix + 1, iy);
  const c = hash(ix, iy + 1);
  const d = hash(ix + 1, iy + 1);
  return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy;
}

function fbm(x: number, y: number, octaves = 4) {
  let s = 0;
  let a = 0.5;
  for (let i = 0; i < octaves; i++) {
    s += a * noise(x, y);
    x = x * 2.03 + 3.1;
    y = y * 2.03 + 1.7;
    a *= 0.5;
  }
  return s;
}

// the coin stands over the back of the pool; the water runs toward the camera, where a low
// viewpoint actually sees the coin's reflection
export const POOL = { x: 0.4, z: 1.6, rx: 6.2, rz: 3.6 };

/** 0 at the pool center, 1 at its (noisy) shoreline */
export function poolDistance(x: number, z: number) {
  const dx = (x - POOL.x) / POOL.rx;
  const dz = (z - POOL.z) / POOL.rz;
  const a = Math.atan2(dz, dx);
  const wobble = 1 + (noise(Math.cos(a) * 2 + 5, Math.sin(a) * 2 + 5) - 0.5) * 0.45;
  return Math.hypot(dx, dz) / wobble;
}

export function terrainHeight(x: number, z: number) {
  // long soft dunes, taller with distance
  const far = Math.min(1, Math.max(0, (-z - 4) / 30));
  const dunes = fbm(x * 0.045 + 10, z * 0.07 + 3) * 2.6 + Math.sin(x * 0.11 + z * 0.05) * 0.6;
  let h = (dunes - 1.1) * (0.35 + far * 1.8) + far * 1.4;
  // gentle foreground lip so the pool reads as sunk into the sand
  h += smoothstep(4.5, 7, z) * 0.3;
  // carve the pool bowl with a soft wet shore
  const d = poolDistance(x, z);
  const bowl = 1 - smoothstep(0.75, 1.25, d);
  h = h * (1 - bowl) + -0.35 * bowl;
  return h + 0.12;
}

function smoothstep(a: number, b: number, x: number) {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

/** seeded PRNG so the landscape is identical on every load */
export function mulberry32(seed: number) {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
