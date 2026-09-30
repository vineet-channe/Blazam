import { chromium, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

export const AUDIO = {
  own: path.resolve(__dirname, ".audio/own.wav"),
  external: path.resolve(__dirname, ".audio/external.wav"),
  noise: path.resolve(__dirname, ".audio/noise.wav"),
};

export const SHOTS = path.resolve(__dirname, "screenshots");
mkdirSync(SHOTS, { recursive: true });

const GPU = ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"];

/** A browser whose microphone plays `audio` (or has no mic permission at all). */
export async function launch(opts: { audio?: string; micAllowed?: boolean; viewport?: { width: number; height: number }; reducedMotion?: boolean } = {}) {
  const { audio = AUDIO.own, micAllowed = true, viewport = { width: 1440, height: 900 }, reducedMotion = false } = opts;
  const browser: Browser = await chromium.launch({
    channel: "chromium",
    args: [...GPU, "--use-fake-device-for-media-stream", ...(micAllowed ? ["--use-fake-ui-for-media-stream"] : []), `--use-file-for-fake-audio-capture=${audio}`],
  });
  const context: BrowserContext = await browser.newContext({ viewport, baseURL: "http://localhost:3000", reducedMotion: reducedMotion ? "reduce" : "no-preference" });
  if (micAllowed) await context.grantPermissions(["microphone"], { origin: "http://localhost:3000" });
  const page: Page = await context.newPage();
  return { browser, context, page };
}

/** Load home and wait for the loader + intro so the scene is interactive. */
export async function openHome(page: Page, query = "") {
  await page.goto(`/${query}`);
  await page.getByTestId("status-idle").waitFor({ timeout: 45_000 });
}

export const shot = (page: Page, name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
