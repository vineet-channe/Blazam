/**
 * Per-frame values shared between the audio/controller code and the WebGL scene.
 * Plain mutable object on purpose: these change 60 times a second and must never
 * trigger React renders. Writers: recorder, controller, pointer handlers. Readers: useFrame.
 */
export type BurstKind = "fire" | "smoke";

export const live = {
  /** smoothed mic RMS level, 0..1 */
  micLevel: 0,
  /** recording progress, 0..1 */
  recordProgress: 0,
  /** pointer in normalized device coords (-1..1) */
  pointer: { x: 0, y: 0 },
  /** device tilt from gyro, -1..1 (0 when unavailable) */
  tilt: { x: 0, y: 0 },
  /** 1 while the cursor is over the coin */
  hover: 0,
  /** coin angular velocity normalized to peak spin, written by the coin every frame */
  spin: 0,
  /** incremented on every burst request; the spark system compares against its last seen id */
  burst: { id: 0, strength: 1, kind: "fire" as BurstKind },
  /** incremented on click so the coin gets its vertical bounce impulse */
  impulse: 0,
};

export function emitBurst(strength = 1, kind: BurstKind = "fire") {
  live.burst = { id: live.burst.id + 1, strength, kind };
}
