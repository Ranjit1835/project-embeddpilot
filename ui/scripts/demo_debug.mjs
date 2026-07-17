import { chromium } from "playwright";

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (m) => console.log(`[${m.type()}] ${m.text()}`));
await page.goto("http://localhost:3100", { waitUntil: "networkidle" });
await page.waitForTimeout(1500);
const html = await page.content();
console.log("has 'recorded':", html.includes("recorded"));
console.log("sample buttons:", await page.getByRole("button", { name: /BME280|W25Q64|ESP32/ }).count());
const status = await page.evaluate(async () => {
  const r = await fetch("/api/samples");
  return r.status;
});
console.log("/api/samples status:", status);
await browser.close();
