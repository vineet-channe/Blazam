import type * as THREE from "three";

/** Scene objects other scene components need to read each frame (e.g. sparks emit from the coin rim). */
export const sceneRefs: { coin: THREE.Object3D | null } = { coin: null };
