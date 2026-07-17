/* WS3 definition-of-done driver: runs a sample through the real UI,
   screenshotting each screen. Usage:
     node scripts/demo.mjs <sampleLabelSubstring> <outPrefix> [expectVerdictSubstring]
*/

import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

const [, , sampleSub, prefix, expect] = process.argv;
const OUT = "../artifacts/ws3_screens";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  colorScheme: "dark",
});

const shot = (name) =>
  page.screenshot({ path: `${OUT}/${prefix}_${name}.png`, fullPage: false });

page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning")
    console.log(`[console.${m.type()}] ${m.text()}`);
});
page.on("pageerror", (e) => console.log(`[pageerror] ${e.message}`));
page.on("response", (r) => {
  if (r.url().includes("/api/"))
    console.log(`[net] ${r.status()} ${r.request().method()} ${r.url()}`);
});
page.on("requestfailed", (r) =>
  console.log(`[netfail] ${r.method()} ${r.url()} ${r.failure()?.errorText}`),
);

try {
  await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
  await shot("1_input");

  // load the sample map -> review screen
  await page.getByRole("button", { name: new RegExp(sampleSub, "i") }).click();
  await page.getByRole("button", { name: "Generate driver" }).waitFor();
  await page.waitForTimeout(400);
  await shot("2_review");

  // generate -> live pipeline screen (may finish fast; accept either state)
  await page.getByRole("button", { name: "Generate driver" }).click();
  await page
    .getByText("Attempt 1")
    .or(page.getByRole("button", { name: "Download all (.zip)" }))
    .first()
    .waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1200);
  await shot("3_generation");

  // wait for the terminal state: results screen or error panel
  const result = page.getByRole("button", { name: "Download all (.zip)" });
  await result.waitFor({ timeout: 300_000 });
  await page.waitForTimeout(500);
  await shot("4_results");

  // the verdict badge renders one of three exact strings; match exactly so
  // "VALIDATED" can never be satisfied by "FAILED — UNVALIDATED OUTPUT"
  const badge = (
    await page
      .locator("span")
      .filter({ hasText: /VALIDATED|FAILED/ })
      .first()
      .textContent()
  )?.trim();
  if (expect && badge !== expect) {
    console.error(`EXPECTED badge '${expect}' but got '${badge}'`);
    process.exitCode = 1;
  } else {
    console.log(`OK ${prefix}: results badge '${badge}'`);
  }
} catch (e) {
  await shot("error_state");
  console.error(`FAILED ${prefix}: ${e.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
