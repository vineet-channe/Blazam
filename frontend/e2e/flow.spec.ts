import { expect, test } from "@playwright/test";
import { AUDIO, launch, openHome, shot } from "./helpers";

/**
 * Smoke test of the whole product against the real backend, no stubs:
 * an indexed song plays into the fake mic -> Space -> listening -> processing -> reveal
 * (own engine) -> the recognition shows up in History and Stats.
 */
test("full flow: listen, recognize with own engine, see it in history and stats", async () => {
  const { browser, page } = await launch({ audio: AUDIO.own });
  try {
    await openHome(page);
    await shot(page, "01-idle");

    const recognize = page.waitForResponse((r) => r.url().includes("/api/recognize"), { timeout: 60_000 });
    await page.keyboard.press("Space");
    await expect(page.getByTestId("status-listening")).toBeVisible();
    await expect(page.getByTestId("dock-listen")).toHaveText(/Stop/);
    await page.waitForTimeout(2500);
    await shot(page, "02-listening-sparks");

    await expect(page.getByTestId("status-processing")).toBeVisible({ timeout: 15_000 });
    await shot(page, "03-processing");

    const res = await recognize;
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe("match");
    expect(body.source).toBe("own");
    expect(typeof body.confidence).toBe("number");

    const card = page.getByTestId("result-card");
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-source", "own");
    await expect(page.getByTestId("badge-own")).toHaveText("Recognized by: Own engine ⚡");
    await expect(page.getByTestId("confidence")).toBeVisible();
    await expect(card.getByRole("heading", { level: 2 })).toHaveText(body.song.title);
    await expect(page.getByTestId("announcer")).toContainText(`Found ${body.song.title}`);
    await page.waitForTimeout(2500);
    await shot(page, "04-reveal-own");

    // the preview URL points at the backend and actually serves audio
    const preview = await page.request.get(body.song.preview_url, { headers: { Range: "bytes=0-1023" } });
    expect([200, 206]).toContain(preview.status());

    // lyrics drawer (song 1, the prepared test song, has lyrics); its Escape closes only the drawer
    await page.getByTestId("open-lyrics").click();
    await expect(page.getByTestId("lyrics")).toBeVisible();
    await page.waitForTimeout(900);
    await shot(page, "04b-lyrics");
    await page.keyboard.press("Escape");
    await expect(page.getByTestId("lyrics")).toBeHidden();
    await expect(card).toBeVisible();

    // Escape closes the card and returns to idle
    await page.keyboard.press("Escape");
    await expect(card).toBeHidden();

    await page.getByRole("link", { name: "History" }).click();
    await expect(page.getByTestId("history-list")).toBeVisible();
    await expect(page.getByTestId("history-list").locator("li").first()).toContainText(body.song.title);

    await page.getByRole("link", { name: "Stats" }).click();
    await expect(page.getByTestId("stats")).toBeVisible();
    await expect(page.getByTestId("donut-own")).toBeVisible();
  } finally {
    await browser.close();
  }
});
