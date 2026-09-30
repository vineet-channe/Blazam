/**
 * Every color in Blazam lives here. The scene reads these as hex strings; CSS gets the same
 * values through the variables injected in the root layout (see `cssVariables`).
 */
export const palette = {
  bgDeep: "#030d08",
  bgHigh: "#0b2a1a",
  fog: "#14513a",
  glow: "#5dffa8",
  glowSoft: "#b6ffd6",
  lime: "#e9f77a",
  ink: "#e8fff1",
  inkMuted: "#8fb8a2",
  inkFaint: "#4d7a63",
  danger: "#ff8a6b",
  external: "#8ad4ff",
} as const;

/** Scene-only tones, derived from the palette so the landscape stays in one hue family. */
export const sceneColors = {
  skyTop: "#010604",
  skyHorizon: "#1a6147",
  horizonGlow: "#3fae7c",
  dune: "#061a10",
  duneLit: "#15402b",
  grass: "#020805",
  grassTip: "#0c2a1c",
  pool: "#04140d",
  poolTint: "#5f8574",
  coinBase: "#0f5e3c",
  coinPale: "#9af0c4",
  coinVein: "#02200f",
  coinRim: "#7dffc0",
  letter: "#e2f25c",
  ring: "#b6ffd6",
  level: "#e9f77a",
  bird: "#03100a",
  dust: "#b6ffd6",
  shaft: "#9dffd0",
} as const;

/**
 * Stats chart identity colors (own / external / no match). Validated with the dataviz
 * palette checker against the dark panel surface #08180f: lightness band, chroma floor,
 * CVD and normal-vision separation and 3:1 contrast all pass.
 */
export const chartColors = {
  own: "#35a864",
  external: "#4a8fe0",
  noMatch: "#cf6f45",
} as const;

/**
 * Spark color ramp over a spark's life: white-hot -> gold -> orange -> ember red.
 * Switch `ACTIVE_SPARK_RAMP` to `GREEN_FLAME` for an all-green fire.
 */
export const FIRE = {
  hot: "#fffbea",
  gold: "#ffd35a",
  orange: "#ff7a1f",
  ember: "#a8190c",
} as const;

export const GREEN_FLAME = {
  hot: "#f4fff8",
  gold: "#b6ffd6",
  orange: "#5dffa8",
  ember: "#0f6b3d",
} as const;

export type SparkRamp = { hot: string; gold: string; orange: string; ember: string };

export const ACTIVE_SPARK_RAMP: SparkRamp = FIRE;

/** Grey-green smoke the sparks decay into on a no-match. */
export const SMOKE = "#6f8a7c";

export const cssVariables = Object.fromEntries(
  Object.entries(palette).map(([k, v]) => [`--c-${k.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)}`, v]),
) as Record<string, string>;
