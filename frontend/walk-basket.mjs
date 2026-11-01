/**
 * Strategy v2 walk: Home -> basket flow (riya) -> try-on -> store -> breakout -> check-in,
 * at 390x844, headless, no YouCam key (the server runs in DEMO_MODE).
 *
 *   cd frontend
 *   DERMOS_WALK_BASE=http://127.0.0.1:5190 DERMOS_WALK_API=http://127.0.0.1:8008 node walk-basket.mjs
 *
 * Reports per step: the exact on-screen text, console errors, failed requests, and horizontal
 * overflow at 390 px. Playwright is resolved from DERMOS_PW (not an app dependency), as in walk.mjs.
 */
import { mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";

const pw = await import(process.env.DERMOS_PW ? pathToFileURL(process.env.DERMOS_PW).href : "playwright");
const { chromium } = pw.chromium ? pw : pw.default;

const BASE = process.env.DERMOS_WALK_BASE ?? "http://127.0.0.1:5190";
const API = process.env.DERMOS_WALK_API ?? "http://127.0.0.1:8008";
const SHOTS = process.env.DERMOS_WALK_SHOTS ?? "walk-shots-basket";
mkdirSync(SHOTS, { recursive: true });

const consoleErrors = [];
const failedRequests = [];
const steps = [];

const browser = await chromium.launch(
  process.env.DERMOS_BROWSER ? { executablePath: process.env.DERMOS_BROWSER } : { channel: "chrome" }
);
const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
page.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(`${page.url()} :: ${m.text()}`);
});
page.on("pageerror", (e) => consoleErrors.push(`${page.url()} :: pageerror: ${e.message}`));
page.on("requestfailed", (r) => failedRequests.push(`${r.method()} ${r.url()} :: ${r.failure()?.errorText ?? "failed"}`));
page.on("response", (r) => {
  if (r.status() >= 400) failedRequests.push(`${r.request().method()} ${r.url()} :: HTTP ${r.status()}`);
});

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
const allText = async (sel) => (await page.locator(sel).allTextContents().catch(() => [])).map((t) => t.trim()).filter(Boolean);

async function record(name, grab) {
  await page.waitForLoadState("networkidle").catch(() => {});
  const o = await overflow();
  const captured = (await grab?.()) ?? {};
  await page.screenshot({ path: `${SHOTS}/${name.replace(/[^a-z0-9]+/gi, "-")}.png`, fullPage: true });
  steps.push({ step: name, url: page.url().replace(BASE, ""), overflow: o, ...captured });
}
async function tap(locator) {
  const el = locator.first();
  await el.evaluate((n) => n.scrollIntoView({ block: "center", behavior: "instant" })).catch(() => {});
  await page.waitForTimeout(80);
  try {
    await el.click({ timeout: 4000 });
  } catch {
    await el.evaluate((n) => n.click());
  }
  await page.waitForTimeout(150);
}
async function scene(name) {
  const r = await page.request.post(`${API}/api/demo/scene/${name}`);
  if (!r.ok()) throw new Error(`scene ${name}: HTTP ${r.status()}`);
  return r.json();
}
async function goto(hash) {
  const target = `${BASE}/#${hash}`;
  const same = page.url() === target;
  await page.goto(target, { waitUntil: "domcontentloaded" });
  if (same) await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
}

await page.request.post(`${API}/api/demo/reset`);
await page.goto(BASE);
await page.evaluate(() => {
  localStorage.clear();
  localStorage.setItem("dermos.onboarded", "true");
});

// 1. Home
await goto("/");
await record("1-home", async () => ({
  eyebrow: await text(".pagehead .subtitle--meta"),
  hero: await text(".hero__label"),
  heroSub: await text(".hero__sub"),
  smaller: await allText(".moment--small .moment__label"),
}));

// 2. Basket: start -> riya's demo face -> the three questions -> the basket
await tap(page.locator(".hero"));
await page.waitForSelector(".choices", { timeout: 15000 });
await record("2-basket-start", async () => ({ title: await text("h1.title"), options: await allText(".row__title") }));
await tap(page.locator(".row", { hasText: "Use Riya's demo face" }));
await page.waitForSelector(".radiogroup, [role=radiogroup]", { timeout: 20000 });
await record("3-questions", async () => ({
  questions: await allText(".section__label"),
  onRecord: await text(".section .small"),
  selected: await allText(".row.is-selected .row__title"),
}));
await tap(page.locator(".btn", { hasText: "Build my basket" }));
await page.waitForSelector(".bcards", { timeout: 20000 });
await record("4-face-map-and-basket", async () => ({
  tag: await text(".tag--prepared"),
  needs: await text(".pagehead .subtitle:not(.subtitle--meta)"),
  faceMap: await allText(".facemap__zone strong"),
  faceMapSources: await allText(".facemap__src"),
  undertoneNote: await text(".facemap + .small, .facemap ~ .muted"),
  total: await text(".section__head .small"),
  cards: await page.locator(".bcard").evaluateAll((els) =>
    els.map((el) => ({
      job: el.querySelector(".bcard__job")?.textContent?.trim(),
      product: [el.querySelector(".bcard__brand")?.textContent, el.querySelector(".bcard__name")?.textContent].filter(Boolean).join(" "),
      shade: el.querySelector(".bcard__shade")?.textContent?.trim() ?? null,
      price: el.querySelector(".bcard__price")?.textContent?.trim() ?? null,
      why: [...el.querySelectorAll(".bcard__whyrow")].map((r) => `${r.querySelector("dt")?.textContent}: ${r.querySelector("dd")?.textContent}`),
      how: el.querySelector(".bcard__how")?.textContent?.trim() ?? null,
      extra: [...el.querySelectorAll(":scope > .small")].map((n) => n.textContent.trim()),
    }))
  ),
  skipped: await page.locator(".skip").evaluateAll((els) =>
    els.map((el) => `${el.querySelector(".skip__name")?.textContent} | ${el.querySelector(".skip__kind")?.textContent} | ${el.querySelector(".skip__reason")?.textContent}`)
  ),
  alreadyOwn: await page
    .locator(".section")
    .filter({ has: page.locator(".section__label", { hasText: "You already own" }) })
    .locator("li")
    .allTextContents(),
  nextStep: await text(".nextstep"),
  bodyHasScoreWords: await page.evaluate(() => /\b(scores?|points?)\b|can['’]?t tell/i.test(document.body.innerText)),
}));

// 3. Try-on
await tap(page.locator(".btn", { hasText: "See the finish on you" }));
await page.waitForSelector(".tryon", { timeout: 15000 });
await record("5-tryon", async () => ({
  title: await text("h1.title"),
  shade: await text(".tryon ~ * , .page > p.small"),
  panels: await allText(".tryon__label"),
  waiting: await allText(".tryon__wait"),
}));
await tap(page.locator(".btn", { hasText: "Back to my basket" }));
await page.waitForSelector(".bcards", { timeout: 15000 });

// 4. Store
await tap(page.locator(".btn", { hasText: "Browse the whole sale" }));
await page.waitForSelector(".sale", { timeout: 15000 });
await record("6-store", async () => ({ title: await text("h1.title"), items: await allText(".sale__name") }));

// 5. Breakout
await scene("riya-breakout");
await goto("/");
await tap(page.locator(".moment__label", { hasText: "broke out" }));
await page.waitForSelector("h1.title", { timeout: 15000 });
await page.waitForLoadState("networkidle").catch(() => {});
await page.waitForTimeout(400);
if ((await page.locator(".symchip.is-on").count()) === 0) await tap(page.locator(".symchip", { hasText: "Cheeks" }));
await tap(page.locator(".symchip--none"));
await tap(page.locator(".btn", { hasText: "What changed?" }));
await page.waitForSelector(".ranking", { timeout: 20000 });
await record("7-breakout", async () => ({
  headline: await text(".standout__text"),
  ranking: await allText(".ranking__item strong"),
}));

// 6. Check-in ("Is my product working?")
await goto("/");
await tap(page.locator(".moment__label", { hasText: "Is my product working" }));
await page.waitForLoadState("networkidle").catch(() => {});
await record("8-checkin-entry", async () => ({ title: await text("h1.title") }));
const meera = await scene("meera-pore");
await goto(`/results/${meera.trial_id}`);
await page.waitForSelector(".standout", { timeout: 20000 });
await record("9-checkin-result", async () => ({ verdict: await text(".standout__text"), next: await text(".standout__next") }));

await browser.close();
console.log(JSON.stringify({ steps, consoleErrors, failedRequests, shots: SHOTS }, null, 2));
