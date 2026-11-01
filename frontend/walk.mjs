/**
 * Phase C walk: the three moments plus Start here, at 390x844, headless, no YouCam key.
 *
 *   cd frontend
 *   DERMOS_WALK_BASE=http://127.0.0.1:5190 DERMOS_WALK_API=http://127.0.0.1:8008 node walk.mjs
 *
 * Reports, per step: the exact on-screen verdict and next-step text, console errors, failed
 * requests, and whether anything overflows horizontally at 390 px.
 */
import { mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";

// Playwright is not a dependency of the app, so this script resolves it wherever it happens to
// live: DERMOS_PW can point at an install outside the repo, which keeps it out of package.json
// and out of CI (where `npm ci` would otherwise pull browser binaries nobody needs).
const pw = await import(
  process.env.DERMOS_PW ? pathToFileURL(process.env.DERMOS_PW).href : "playwright"
);
// A CommonJS build imported by path arrives under `default`.
const { chromium } = pw.chromium ? pw : pw.default;

const BASE = process.env.DERMOS_WALK_BASE ?? "http://127.0.0.1:5190";
const API = process.env.DERMOS_WALK_API ?? "http://127.0.0.1:8008";
const SHOTS = process.env.DERMOS_WALK_SHOTS ?? "walk-shots";
mkdirSync(SHOTS, { recursive: true });

const consoleErrors = [];
const failedRequests = [];
const steps = [];

// Use a browser that is already on the machine rather than downloading one: the installed
// Chrome by default, or DERMOS_BROWSER as an explicit path.
const browser = await chromium.launch(
  process.env.DERMOS_BROWSER ? { executablePath: process.env.DERMOS_BROWSER } : { channel: "chrome" }
);
const page = await browser.newPage({
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
});

page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(`${page.url()} :: ${m.text()}`);
});
page.on("pageerror", (e) => consoleErrors.push(`${page.url()} :: pageerror: ${e.message}`));
page.on("requestfailed", (r) =>
  failedRequests.push(`${r.method()} ${r.url()} :: ${r.failure()?.errorText ?? "failed"}`)
);
page.on("response", (r) => {
  if (r.status() >= 400) failedRequests.push(`${r.request().method()} ${r.url()} :: HTTP ${r.status()}`);
});

/** Horizontal overflow at 390 px: the document, and any element wider than the viewport. */
async function overflow() {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const doc = document.documentElement.scrollWidth;
    const wide = [];
    for (const el of document.querySelectorAll("body *")) {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && (r.right > vw + 1 || r.left < -1)) {
        const cls = typeof el.className === "string" ? el.className : "";
        wide.push(`${el.tagName.toLowerCase()}${cls ? "." + cls.split(" ")[0] : ""} (${Math.round(r.left)}..${Math.round(r.right)})`);
      }
    }
    return { viewport: vw, scrollWidth: doc, overflows: doc > vw + 1, wideElements: [...new Set(wide)].slice(0, 8) };
  });
}

const text = async (sel) => (await page.locator(sel).first().textContent().catch(() => null))?.trim() ?? null;
const allText = async (sel) =>
  (await page.locator(sel).allTextContents().catch(() => [])).map((t) => t.trim()).filter(Boolean);

async function record(name, grab) {
  await page.waitForLoadState("networkidle").catch(() => {});
  const o = await overflow();
  const captured = (await grab?.()) ?? {};
  await page.screenshot({ path: `${SHOTS}/${name.replace(/[^a-z0-9]+/gi, "-")}.png`, fullPage: true });
  steps.push({ step: name, url: page.url().replace(BASE, ""), overflow: o, ...captured });
  return captured;
}

/**
 * Tap an element the way a person would: bring it to the middle of the screen first, then click.
 * Falls back to a DOM click if something transient is over it, because this harness is here to
 * read the engine's words, not to be a hit-testing test. Real layout problems are caught by the
 * overflow() check on every step instead.
 */
async function tap(locator) {
  const el = locator.first();
  await el.scrollIntoViewIfNeeded().catch(() => {});
  await el.evaluate((n) => n.scrollIntoView({ block: "center", behavior: "instant" })).catch(() => {});
  await page.waitForTimeout(80);
  try {
    await el.click({ timeout: 4000 });
  } catch {
    await el.evaluate((n) => n.click());
  }
  await page.waitForTimeout(120);
}

async function scene(name) {
  const r = await page.request.post(`${API}/api/demo/scene/${name}`);
  if (!r.ok()) throw new Error(`scene ${name}: HTTP ${r.status()}`);
  return r.json();
}

async function goto(hash) {
  const target = `${BASE}/#${hash}`;
  // Navigating to the URL the page is already on is not a navigation, so the app would keep
  // showing data it loaded before the scene changed. Reload explicitly in that case.
  const same = page.url() === target;
  await page.goto(target, { waitUntil: "domcontentloaded" });
  if (same) await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
}

// Start from a clean slate, then mark onboarding done so Home is Home.
await page.goto(BASE);
await page.evaluate(() => {
  localStorage.clear();
  // The app's own key prefix (src/local.ts), so Home is Home rather than the welcome screen.
  localStorage.setItem("dermos.onboarded", "true");
});

// ---------------------------------------------------------------- 1. Home
await scene("riya-store");
await goto("/");
await record("1-home", async () => ({
  question: await text("h1.title"),
  valueLine: await text(".pagehead .subtitle"),
  moments: await allText(".moment__label"),
  startHere: await text(".starthere__label"),
}));

// ---------------------------------------------------------------- 2. the sale
await tap(page.locator(".moment__label", { hasText: "about to buy" }));
await record("2-store", async () => ({
  sale: await text(".pagehead .subtitle--meta, .pagehead p"),
  items: await allText(".sale__name"),
  buttons: (await allText(".sale__item .btn")).length,
}));

// ---------------------------------------------------------------- 3. the three checks
for (const [label, name] of [
  ["A", "Glow Shot Vitamin C"],
  ["B", "Dew Veil Barrier Cream"],
  ["C", "Pore Clarity Gel Serum"],
]) {
  await goto("/store");
  await tap(page.locator(".sale__item").filter({ hasText: name }).locator(".btn"));
  await page.waitForSelector(".standout", { timeout: 15000 });
  await record(`3-check-${label}`, async () => ({
    product: name,
    verdict: await text("h1.title"),
    kicker: await text(".standout__kicker"),
    tags: await allText(".standout .tag"),
    history: await allText("section:has(.srclines) .srclines li"),
    sections: await allText(".section__label"),
    nextStep: (await allText(".section")).length ? await nextStepText() : null,
    changeNothing: await changeNothingText(),
  }));
}

async function sectionProse(label) {
  const sec = page.locator(".section").filter({ has: page.locator(".section__label", { hasText: label }) });
  return (await sec.locator(".prose").first().textContent().catch(() => null))?.trim() ?? null;
}
async function nextStepText() {
  return sectionProse("Your next step");
}
async function changeNothingText() {
  return sectionProse("Or change nothing");
}

// ---------------------------------------------------------------- 4. the breakout
await scene("riya-breakout");
await goto("/");
await tap(page.locator(".moment__label", { hasText: "broke out" }));
await page.waitForSelector("h1.title", { timeout: 15000 });
// Let the demo prefill land before tapping, so the page isn't relaying out under the cursor.
await page.waitForLoadState("networkidle").catch(() => {});
await page.waitForTimeout(400);
// Answer the two questions a real user answers: where it is, and whether anything hurts.
if ((await page.locator(".symchip.is-on").count()) === 0) {
  await tap(page.locator(".symchip", { hasText: "Cheeks" }));
}
await tap(page.locator(".symchip--none"));
await tap(page.locator(".btn", { hasText: "What changed?" }));
await page.waitForSelector(".ranking", { timeout: 20000 });
const triage = await record("4-breakout", async () => ({
  headline: await text(".standout__text"),
  zones: await sectionProse("Where the spots are"),
  purge: await sectionProse("Could it be purging?"),
  ranking: await allText(".ranking__item strong"),
  topReason: await text(".ranking__item .ranking__why"),
  nextStep: await nextStepText(),
}));

// ...and the one next step opens a trial.
await tap(page.locator(".btn", { hasText: "Open the day-14 check-in" }));
await page.waitForURL(/#\/trial\//, { timeout: 20000 });
await record("5-trial-opened", async () => ({
  openedTrialUrl: page.url().replace(BASE, ""),
  title: await text("h1.title"),
}));

// ---------------------------------------------------------------- 5. the mirror (meera)
const meera = await scene("meera-pore");
await goto(`/results/${meera.trial_id}`);
await page.waitForSelector(".standout", { timeout: 20000 });
await record("6-evidence", async () => ({
  typicalAppLabel: await text(".typicalapp__label"),
  typicalAppLine: await text(".typicalapp__line"),
  dermosLabel: await text(".standout__label"),
  verdict: await text(".standout__text"),
  next: await text(".standout__next"),
  rebuy: await text(".rebuy span:last-child"),
  writeBackOutcome: await text(".writeback .chip"),
  writeBackNote: await text(".writeback__note"),
}));

// ---------------------------------------------------------------- 6. the write-back
await tap(page.locator(".btn", { hasText: "Write this into my history" }));
await page.waitForSelector(".section:has(.writeback) a[href='#/history']", { timeout: 20000 });
await record("7-writeback-done", async () => ({
  confirmation: await text(".section:has(.writeback) .small"),
}));

await goto("/history");
await page.waitForSelector(".outcomes", { timeout: 20000 });
await record("8-history-writeback", async () => ({
  outcomes: await allText(".outcome__head strong"),
  writtenIn: (await allText(".outcome__meta")).filter((t) => t.includes("written in")),
  chips: await allText(".outcome .chip"),
}));

// ---------------------------------------------------------------- 7. riya's write-back in History
await scene("riya-store");
await goto("/history");
await page.waitForSelector(".outcomes", { timeout: 20000 });
await record("9-riya-history", async () => ({
  outcomes: await allText(".outcome__head strong"),
  lines: await allText(".outcome__line"),
  suspects: await allText(".suspect__head strong"),
  counts: await allText(".suspect__counts"),
  headlines: await allText(".patrun__headline"),
  cannotNarrow: await allText(".patrun__cant"),
  purgeOffer: await allText(".purgeoffer p"),
}));

// ---------------------------------------------------------------- 8. Start here
const beginner = await scene("beginner");
await goto("/");
await tap(page.locator(".starthere"));
await page.waitForSelector(".choices", { timeout: 20000 });
// Answer as the beginner persona would (the scene carries her answers), so the walk reads the
// same plan the benchmark asserts on rather than whatever the first option happens to be.
const answers = beginner.situation?.answers ?? {};
const questions = await page.request.get(`${API}/api/beginner/questions`).then((r) => r.json());
const groups = page.locator(".choices");
for (const [i, q] of questions.questions.entries()) {
  const want = answers[q.id];
  const idx = Math.max(0, q.choices.findIndex((c) => c.value === want));
  await tap(groups.nth(i).locator(".row").nth(idx));
}
await tap(page.locator(".btn", { hasText: "See where to start" }));
await page.waitForSelector(".starter", { timeout: 20000 });
await record("10-start-here", async () => ({
  skinType: await text(".standout__kicker"),
  typeLabel: await text(".standout .tag"),
  typeLine: await text(".pagehead .subtitle"),
  noScanNote: await text(".standout .small"),
  concerns: await allText("section:has(.section__label) .muted"),
  starter: await allText(".starter__name"),
  verdicts: await allText(".starter__verdict"),
  oneAtATime: await sectionProse("How to start it"),
  nextStep: await sectionProse("Your next step"),
}));

await browser.close();

console.log(
  JSON.stringify(
    { steps, consoleErrors, failedRequests, shots: SHOTS },
    null,
    2
  )
);
