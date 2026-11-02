// Responsive layout check: walks the strategy v2 flow at ten viewports, from a 360 px phone to a
// 2560 px desktop, and saves the results to docs/screenshots/layout-check.json. Also saves the
// desktop screenshots (1440 x 900) used in the README.
//
//   1. API in demo mode, YouCam key empty (no units are ever spent):
//        cd backend; $env:DEMO_MODE="1"; $env:YOUCAM_API_KEY=""; python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
//   2. App: cd frontend; npx vite --host 127.0.0.1 --port 5180
//   3. node scripts/layout-check.mjs [--base http://127.0.0.1:5180] [--out ../docs/screenshots]
//
// Needs Playwright (any install: set PLAYWRIGHT_DIR to its folder if it isn't resolvable from here).
// Every walk starts as a first-time visitor (local storage cleared, demo data reset).
//
// Per viewport it records: console errors, sideways scroll, tap targets under 44 x 44 px (touch
// sizes only), elements overflowing their container, and whether the main home button is fully
// visible without scrolling (and not under the tab bar).
import { createRequire } from "node:module";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_DIR ? join(process.env.PLAYWRIGHT_DIR, "index.js") : "playwright");

const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? process.argv[i + 1] : d;
};
const BASE = arg("--base", "http://127.0.0.1:5180");
const OUT = resolve(arg("--out", "../docs/screenshots"));

// [width, height, touch]
const VIEWPORTS = [
  [360, 740, true],
  [390, 844, true],
  [844, 390, true],
  [768, 1024, true],
  [1024, 768, true],
  [1280, 720, false],
  [1366, 768, false],
  [1440, 900, false],
  [1920, 1080, false],
  [2560, 1440, false],
];
const DESKTOP_SHOTS = "1440x900";
// Use an installed Chrome or Edge when there is one, so no browser download is needed.
const BROWSERS = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
].filter(Boolean);

// Runs in the page: one audit of the current screen.
function audit(touch) {
  const vw = window.innerWidth;
  const sideways = document.documentElement.scrollWidth > vw + 1;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && !el.closest("[hidden], .sr-only, [aria-hidden=true]");
  };
  const name = (el) =>
    `${el.tagName.toLowerCase()}${el.className && typeof el.className === "string" ? "." + el.className.trim().split(/\s+/)[0] : ""} "${(
      el.innerText || el.getAttribute("aria-label") || ""
    )
      .trim()
      .slice(0, 28)}"`;

  const small = [];
  if (touch) {
    for (const el of document.querySelectorAll("a[href], button, select, input, textarea, [role=tab], [role=radio]")) {
      if (!visible(el)) continue;
      if (el.tagName === "A" && el.closest("p, li") && !el.className) continue; // links inside a sentence
      const r = el.getBoundingClientRect();
      if (r.width < 44 || r.height < 44) small.push(`${name(el)} ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  }

  // Overflow: content wider than its own box (and not meant to scroll), or a box outside the viewport.
  const overflow = [];
  for (const el of document.querySelectorAll(".app *")) {
    if (el.closest("svg") || !visible(el)) continue;
    const cs = getComputedStyle(el);
    const scrolls = /(auto|scroll)/.test(cs.overflowX) || el.tagName === "TEXTAREA" || el.closest(".hscroll");
    if (!scrolls && cs.overflowX !== "hidden" && cs.overflowX !== "clip" && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
      overflow.push(`${name(el)} content ${el.scrollWidth}px in ${el.clientWidth}px`);
      continue;
    }
    const r = el.getBoundingClientRect();
    if (!el.closest(".hscroll") && (r.right > vw + 1 || r.left < -1)) overflow.push(`${name(el)} outside viewport (${Math.round(r.left)}..${Math.round(r.right)})`);
  }
  return { sideways, scrollWidth: document.documentElement.scrollWidth, small, overflow: overflow.slice(0, 12), overflowCount: overflow.length };
}

function heroVisible() {
  const h = document.querySelector(".hero");
  if (!h) return { ok: false, why: "no .hero" };
  const r = h.getBoundingClientRect();
  const bar = document.querySelector(".tabbar");
  const limit = bar ? bar.getBoundingClientRect().top : window.innerHeight;
  const ok = window.scrollY === 0 && r.top >= 0 && r.bottom <= Math.min(limit, window.innerHeight) + 0.5;
  return { ok, top: Math.round(r.top), bottom: Math.round(r.bottom), limit: Math.round(limit) };
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const exe = BROWSERS.find((p) => existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(exe ? { executablePath: exe } : {}) });
  const results = [];
  try {
    for (const [w, h, touch] of VIEWPORTS) {
      const key = `${w}x${h}`;
      const ctx = await browser.newContext({
        viewport: { width: w, height: h },
        deviceScaleFactor: 1,
        isMobile: touch && w < 900,
        hasTouch: touch,
        reducedMotion: "reduce",
      });
      const page = await ctx.newPage();
      const errors = [];
      page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 160)));
      page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
      const screens = [];
      const check = async (label) => {
        await page.waitForTimeout(250);
        const a = await page.evaluate(audit, touch);
        screens.push({ screen: label, ...a });
      };
      const shot = async (file, full = false) => {
        if (key === DESKTOP_SHOTS) await page.screenshot({ path: join(OUT, file), fullPage: full });
      };

      // A first-time visitor: no saved flags, prepared data reset.
      await page.goto(`${BASE}/#/`);
      await page.evaluate(() => fetch("/api/demo/reset", { method: "POST" }).then(() => localStorage.clear()));
      await page.reload();
      await page.waitForSelector(".hero");
      await page.waitForTimeout(300);
      const hero = await page.evaluate(heroVisible);
      const firstScreenIsV2 = await page.evaluate(() => document.body.innerText.includes("Build my basket from my face"));
      await check("home");
      // LAYOUT_SHOTS_ALL=1: also save the first screen at every viewport, to look at by eye.
      if (process.env.LAYOUT_SHOTS_ALL === "1") await page.screenshot({ path: join(OUT, `home-${key}.png`) });
      await shot("16-desktop-home-1440.png");

      // Riya: home -> demo face (1 tap) -> questions + chips -> face map + basket -> skipped -> plan -> paste -> try-on
      await page.click(".trybtn >> text=Use Riya's demo face");
      await page.waitForSelector("[role=radiogroup]");
      await page.waitForTimeout(400);
      await check("riya questions + chips");
      await page.click(".btn >> text=Build my basket");
      await page.waitForSelector(".bcards");
      await page.waitForTimeout(400);
      await check("riya face map + basket");
      await shot("17-desktop-face-map-basket-1440.png");
      for (const sel of [".skips", ".plan"]) {
        await page.locator(sel).scrollIntoViewIfNeeded();
        await check(sel === ".skips" ? "riya skipped" : "riya start plan");
      }
      await page.fill(".paste__text", "Aqua, Glycerin, Alcohol Denat., Niacinamide, Parfum, Linalool");
      await page.click("button >> text=Check it");
      await page.waitForSelector(".pasteres");
      await check("riya paste a label");
      await page.click(".btn >> text=See the finish on you");
      await page.waitForSelector(".tryon");
      await page.waitForTimeout(300);
      await check("riya try-on");
      await shot("18-desktop-try-on-1440.png");

      // Store page
      await page.goto(`${BASE}/#/store`);
      await page.waitForSelector(".sale");
      await check("store");

      // Beginner: home -> big button -> beginner face -> basket
      await page.goto(`${BASE}/#/`);
      await page.waitForSelector(".hero");
      await page.click(".hero");
      await page.waitForSelector(".choices");
      await check("basket start");
      await page.click(".row >> text=Use a beginner demo face");
      await page.waitForSelector("[role=radiogroup]");
      await page.click(".btn >> text=Build my basket");
      await page.waitForSelector(".bcards");
      await page.waitForTimeout(300);
      await check("beginner basket");

      const row = {
        viewport: key,
        touch,
        consoleErrors: errors.length,
        horizontalScroll: screens.filter((s) => s.sideways).length,
        smallTapTargets: screens.reduce((n, s) => n + s.small.length, 0),
        overflowing: screens.reduce((n, s) => n + s.overflowCount, 0),
        homeButtonVisible: hero.ok,
        firstVisitHomeIsV2: firstScreenIsV2,
        hero,
        errors,
        screens,
      };
      results.push(row);
      console.log(
        `${key.padEnd(10)} errors ${row.consoleErrors}  scroll ${row.horizontalScroll}  small ${row.smallTapTargets}  overflow ${row.overflowing}  home button ${hero.ok ? "visible" : "NOT visible"}  v2 ${firstScreenIsV2}`
      );
      for (const s of screens) for (const x of [...s.small, ...s.overflow]) console.log(`    ${s.screen}: ${x}`);
      for (const e of errors) console.log(`    console: ${e}`);
      await ctx.close();
    }
  } finally {
    await browser.close();
  }
  writeFileSync(join(OUT, "layout-check.json"), JSON.stringify({ base: BASE, checked: new Date().toISOString().slice(0, 10), results }, null, 2));
  const bad = results.filter((r) => r.consoleErrors || r.horizontalScroll || r.smallTapTargets || r.overflowing || !r.homeButtonVisible || !r.firstVisitHomeIsV2);
  console.log(`\n${results.length} viewports, ${bad.length} with a problem.`);
  if (bad.length) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
