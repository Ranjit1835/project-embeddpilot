/* Verifies recorded-demo mode: no backend -> banner + full replayed flow. */
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";

mkdirSync("../artifacts/ws3_screens", { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  colorScheme: "dark",
});

try {
  await page.goto("http://localhost:3100", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: /BME280/i }).click();
  await page.getByText("recorded case study").waitFor({ timeout: 10_000 });
  console.log("banner: OK");
  await page.getByRole("button", { name: "Generate driver" }).click();
  await page.getByText("Attempt 1").waitFor({ timeout: 15_000 });
  console.log("replay timeline: OK");
  await page
    .getByRole("button", { name: "Download bundle (.json)" })
    .waitFor({ timeout: 60_000 });
  const badge = (
    await page.locator("span").filter({ hasText: /VALIDATED|FAILED/ }).first().textContent()
  )?.trim();
  console.log(`results badge: ${badge}`);
  await page.screenshot({
    path: "../artifacts/ws3_screens/demo_offline_results.png",
  });
  if (badge !== "VALIDATED") process.exitCode = 1;
} catch (e) {
  console.error("FAILED:", e.message);
  await page.screenshot({ path: "../artifacts/ws3_screens/demo_offline_error.png" });
  process.exitCode = 1;
} finally {
  await browser.close();
}
