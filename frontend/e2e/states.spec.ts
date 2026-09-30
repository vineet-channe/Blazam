import { expect, test } from "@playwright/test";
import externalMatch from "./fixtures/external-match.json";
import { AUDIO, launch, openHome, shot } from "./helpers";

/**
 * Every designed state, captured as a screenshot in e2e/screenshots. Real backend unless a
 * test says STUB: only the single response that can't be produced on demand is replaced.
 */

test("no match: noise into the mic, real backend", async () => {
  const { browser, page } = await launch({ audio: AUDIO.noise });
  try {
    await openHome(page);
    await page.waitForTimeout(3500); // let the intro camera settle so the coin is where we aim
    // hover the coin: custom "Listen" cursor label; click it to start listening
    await page.mouse.move(720, 400);
    await expect(page.locator(".cursor-label.is-on")).toBeVisible();
    await expect(page.locator(".cursor-label")).toContainText("Listen");
    await shot(page, "01b-hover");
    await page.mouse.click(720, 400);
    await expect(page.getByTestId("status-listening")).toBeVisible();
    const panel = page.getByTestId("no-match");
    await expect(panel).toBeVisible({ timeout: 60_000 });
    await expect(panel).toContainText("Couldn’t catch that.");
    await expect(panel).toContainText("Try again closer to the source.");
    await page.waitForTimeout(2000);
    await shot(page, "05-no-match");
  } finally {
    await browser.close();
  }
});

test("external match with null confidence (STUB: /api/recognize replays a recorded real AudD response)", async () => {
  // A live external match auto-learns the song, so the same clip is an own match on the next
  // run. The recorded response (captured from this app against the real backend) keeps the
  // test repeatable; recording, upload and the rest of the flow are still real.
  const { browser, page } = await launch({ audio: AUDIO.external });
  try {
    await page.route("**/api/recognize", (route) => route.fulfill({ json: externalMatch }));
    await openHome(page);
    await page.keyboard.press("Space");
    const card = page.getByTestId("result-card");
    await expect(card).toBeVisible({ timeout: 60_000 });
    await expect(card).toHaveAttribute("data-source", "external");
    await expect(page.getByTestId("badge-external")).toHaveText("Recognized by: External API 🌐");
    await expect(page.getByTestId("confidence")).toHaveCount(0);
    await expect(page.getByTestId("toast")).toContainText("Added to library");
    await expect(card).toContainText("0:58");
    await page.waitForTimeout(2200);
    await shot(page, "06-reveal-external");
  } finally {
    await browser.close();
  }
});

test("error: microphone permission denied", async () => {
  const { browser, page } = await launch({ micAllowed: false });
  try {
    await openHome(page);
    await page.keyboard.press("Space");
    const panel = page.getByTestId("error-mic_denied");
    await expect(panel).toBeVisible({ timeout: 20_000 });
    await expect(panel).toContainText("Microphone access is blocked");
    await page.waitForTimeout(1500);
    await shot(page, "07-error-mic-denied");
  } finally {
    await browser.close();
  }
});

test("error: backend unreachable during recognition (STUB: /api/recognize network failure)", async () => {
  const { browser, page } = await launch({ audio: AUDIO.own });
  try {
    await page.route("**/api/recognize", (route) => route.abort("connectionrefused"));
    await openHome(page);
    await page.keyboard.press("Space");
    const panel = page.getByTestId("error-offline");
    await expect(panel).toBeVisible({ timeout: 30_000 });
    await expect(panel).toContainText("The Blazam server is offline");
    await page.waitForTimeout(1500);
    await shot(page, "08-error-offline");
  } finally {
    await browser.close();
  }
});

test("pages: library search, add with a live import job, history, stats", async () => {
  test.setTimeout(420_000); // real Deezer downloads + fingerprint jobs run inside this test
  const { browser, page } = await launch();
  try {
    await openHome(page);

    await page.getByRole("link", { name: "Library" }).click();
    await expect(page.getByTestId("library-grid").locator("li").first()).toBeVisible();
    await page.waitForTimeout(3000);
    await shot(page, "09-library");
    await page.getByTestId("library-search").fill("Dancing Queen");
    await expect(page.getByTestId("library-grid")).toContainText("Dancing Queen");

    await page.getByRole("link", { name: "Add songs" }).click();
    await page.getByTestId("deezer-query").fill("Fleetwood Mac Dreams");
    await page.getByRole("button", { name: "Search", exact: true }).click();
    const first = page.getByTestId("deezer-results").getByRole("button").first();
    await expect(first).toBeVisible({ timeout: 20_000 });
    await first.click();
    // real import job, progress streamed over SSE
    const job = page.getByTestId("job").first();
    await expect(job).toBeVisible();
    await expect(job).toHaveAttribute("data-status", /running|done/, { timeout: 30_000 });
    await shot(page, "10-add-live-job");
    await expect(job).toHaveAttribute("data-status", "done", { timeout: 90_000 });
    // the clicked track really ended up in the library (new, or already there)
    await expect(job).toContainText(/Done: (?:[1-9]\d* indexed|\d+ indexed, [1-9]\d* already known)/);

    // seed from the Deezer chart: a real job (already-indexed tracks are skipped server side)
    await page.getByRole("radio", { name: "10", exact: true }).check({ force: true });
    await page.getByTestId("seed-start").click();
    const seedJob = page.locator('section[aria-labelledby="seed-h"]').getByTestId("job");
    await expect(seedJob).toHaveAttribute("data-status", "done", { timeout: 150_000 });
    await expect(seedJob).toContainText(/Done: \d+ indexed, \d+ already known/);

    // upload: an undecodable file runs a real upload job whose per-file error is shown,
    // without adding anything to the library
    await page.getByTestId("upload-input").setInputFiles({ name: "Blazam Test - Not Audio.mp3", mimeType: "audio/mpeg", buffer: Buffer.from("this is not audio") });
    const upJob = page.locator('section[aria-labelledby="up-h"]').getByTestId("job");
    await expect(upJob).toHaveAttribute("data-status", /done|failed/, { timeout: 60_000 });
    await shot(page, "10b-add-seed-upload-done");

    await page.getByRole("link", { name: "History" }).click();
    await expect(page.getByTestId("history-list")).toBeVisible();
    await page.waitForTimeout(2500);
    await shot(page, "11-history");

    await page.getByRole("link", { name: "Stats" }).click();
    await expect(page.getByTestId("stats")).toBeVisible();
    await page.waitForTimeout(2000);
    await shot(page, "12-stats");
  } finally {
    await browser.close();
  }
});

test("responsive (390, 360, 2560) and no-WebGL fallback with reduced motion", async () => {
  test.setTimeout(240_000);
  const mobile = await launch({ viewport: { width: 390, height: 844 } });
  try {
    await openHome(mobile.page);
    await shot(mobile.page, "13-mobile-idle");
    await mobile.page.keyboard.press("Space");
    await expect(mobile.page.getByTestId("result-card")).toBeVisible({ timeout: 60_000 });
    await mobile.page.waitForTimeout(2500);
    await shot(mobile.page, "14-mobile-reveal");
  } finally {
    await mobile.browser.close();
  }

  for (const viewport of [
    { width: 360, height: 740 },
    { width: 2560, height: 1080 },
  ]) {
    const v = await launch({ viewport });
    try {
      await openHome(v.page);
      await v.page.waitForTimeout(2500);
      await shot(v.page, `13b-idle-${viewport.width}`);
    } finally {
      await v.browser.close();
    }
  }

  const fallback = await launch({ reducedMotion: true });
  try {
    await openHome(fallback.page, "?webgl=0");
    await expect(fallback.page.locator(".fallback-coin")).toBeVisible();
    await expect(fallback.page.getByTestId("loader")).toBeHidden();
    await shot(fallback.page, "15-fallback-idle");
    await fallback.page.keyboard.press("Space");
    await expect(fallback.page.getByTestId("result-card")).toBeVisible({ timeout: 60_000 });
    await fallback.page.waitForTimeout(1800); // card entrance
    await shot(fallback.page, "16-fallback-reveal");
  } finally {
    await fallback.browser.close();
  }
});
