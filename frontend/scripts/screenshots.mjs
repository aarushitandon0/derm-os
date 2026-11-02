// 390 px screenshots of the strategy v2 flow (riya + beginner), plus a layout check on every screen
// (written to shots-390.json). For every viewport from 360 px to 2560 px, see scripts/layout-check.mjs.
//
//   1. API in demo mode, YouCam key empty:
//        cd backend; $env:DEMO_MODE="1"; $env:YOUCAM_API_KEY=""; python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
//   2. App: cd frontend; $env:DERMOS_API_PROXY="http://127.0.0.1:8010"; npx vite --host 127.0.0.1 --port 5180
//   3. node scripts/screenshots.mjs [--base http://127.0.0.1:5180] [--out ../docs/screenshots]
//
// Drives headless Chrome (or Edge) over the DevTools protocol with Node's built-in WebSocket: no
// installs, no camera, no face photo (the demo faces are prepared data). Reduced motion is on.
// For every screen it reports sideways scroll and tap targets smaller than 44 x 44 px.
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? process.argv[i + 1] : d;
};
const BASE = arg("--base", "http://127.0.0.1:5180");
const OUT = resolve(arg("--out", "../docs/screenshots"));
const PORT = 9333;
const W = 390;
const H = 844;
const BROWSERS = [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "/usr/bin/google-chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(url, tries = 60) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return r;
    } catch {}
    await sleep(500);
  }
  throw new Error(`Not reachable: ${url}`);
}

class Page {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && this.pending.has(m.id)) {
        const { ok, fail } = this.pending.get(m.id);
        this.pending.delete(m.id);
        m.error ? fail(new Error(JSON.stringify(m.error))) : ok(m.result);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((ok, fail) => this.pending.set(id, { ok, fail }));
  }
  async eval(expr) {
    const r = await this.send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + " " + (r.exceptionDetails.exception?.description ?? ""));
    return r.result.value;
  }
  async go(hash) {
    await this.eval(`location.hash = ${JSON.stringify(hash)}; true`);
    await sleep(900);
  }
  /** Wait until the page shows this text (the screen finished loading its data). */
  async waitText(text, ms = 8000) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      if (await this.eval(`document.body.innerText.includes(${JSON.stringify(text)})`)) return;
      await sleep(200);
    }
    throw new Error(`Timed out waiting for "${text}" on ${await this.eval("location.hash")}`);
  }
  async click(text) {
    const ok = await this.eval(`(() => {
      const el = [...document.querySelectorAll("button, a")].find((b) => b.innerText.trim().startsWith(${JSON.stringify(text)}));
      if (!el) return false; el.click(); return true; })()`);
    if (!ok) throw new Error(`No button "${text}"`);
    await sleep(1200);
  }
  async audit() {
    return this.eval(`(() => {
      const sideways = document.documentElement.scrollWidth > window.innerWidth + 1;
      const small = [];
      for (const el of document.querySelectorAll("a[href], button, select, input, textarea, [role=tab], [role=radio]")) {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        if (!r.width || !r.height || cs.visibility === "hidden" || el.closest("[hidden], .print-only")) continue;
        if (el.tagName === "A" && el.closest("p, li") && !el.className) continue;   // links inside a sentence
        if (r.width < 44 || r.height < 44) small.push(\`\${el.tagName.toLowerCase()} "\${(el.innerText || el.getAttribute("aria-label") || el.value || "").trim().slice(0, 30)}" \${Math.round(r.width)}x\${Math.round(r.height)}\`);
      }
      return { sideways, scrollWidth: document.documentElement.scrollWidth, small };
    })()`);
  }
  /** Scroll an element into view and capture just that element (full width). */
  async shotEl(name, selector) {
    const r = await this.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null; const b = el.getBoundingClientRect();
      return { y: Math.max(0, b.top + window.scrollY - 12), h: b.height + 24 }; })()`);
    if (!r) throw new Error(`No element ${selector}`);
    const { data } = await this.send("Page.captureScreenshot", {
      format: "png", captureBeyondViewport: true, clip: { x: 0, y: r.y, width: W, height: Math.ceil(r.h), scale: 1 },
    });
    writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
    const a = await this.audit();
    report.push({ name, ...a });
    console.log(`${name}: ${a.sideways ? "SIDEWAYS SCROLL " + a.scrollWidth + "px" : "no sideways scroll"}, ${a.small.length} small target(s)`);
  }
  /** Click the first element matching a CSS selector whose text includes `text` (or any, if empty). */
  async tap(selector, text = "") {
    const ok = await this.eval(`(() => {
      const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((b) => b.innerText.includes(${JSON.stringify(text)}));
      if (!el) return false; el.scrollIntoView({ block: "center" }); el.click(); return true; })()`);
    if (!ok) throw new Error(`No ${selector} with "${text}"`);
    await sleep(1200);
  }
  async waitSel(selector, ms = 15000) {
    const t0 = Date.now();
    while (Date.now() - t0 < ms) {
      if (await this.eval(`!!document.querySelector(${JSON.stringify(selector)})`)) return;
      await sleep(200);
    }
    throw new Error(`Timed out waiting for ${selector}`);
  }
  async api(path) {
    return this.eval(`fetch(${JSON.stringify(path)}, { method: "POST" }).then((r) => r.ok)`);
  }
  async shot(name) {
    // Full-page capture: a fixed tab bar would be stamped mid-page, so put it at the end of the page.
    await this.eval(`(() => { let s = document.getElementById("shot-css"); if (!s) { s = document.createElement("style");
      s.id = "shot-css"; s.textContent = ".tabbar{position:static!important;transform:none!important;margin:0 auto}"; document.head.append(s); } return true; })()`);
    await sleep(150);
    const h = await this.eval("Math.ceil(document.documentElement.scrollHeight)");
    const { data } = await this.send("Page.captureScreenshot", {
      format: "png",
      captureBeyondViewport: true,
      clip: { x: 0, y: 0, width: W, height: Math.max(H, h), scale: 1 },
    });
    writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
    const a = await this.audit();
    report.push({ name, ...a });
    console.log(`${name}: ${a.sideways ? "SIDEWAYS SCROLL " + a.scrollWidth + "px" : "no sideways scroll"}, ${a.small.length} small target(s)`);
    for (const s of a.small) console.log(`    small: ${s}`);
  }
}

const report = [];

async function main() {
  mkdirSync(OUT, { recursive: true });
  await waitFor(`${BASE}/health`);
  const exe = BROWSERS.find((p) => existsSync(p));
  if (!exe) throw new Error("No Chrome or Edge found");
  const profile = mkdtempSync(join(tmpdir(), "dermos-shots-"));
  const browser = spawn(exe, [
    "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "--no-first-run",
    "--no-default-browser-check", "--disable-extensions", `--window-size=${W},${H}`, "about:blank",
  ], { stdio: "ignore" });
  try {
    await waitFor(`http://127.0.0.1:${PORT}/json/version`);
    const targets = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
    const t = targets.find((x) => x.type === "page");
    const ws = new WebSocket(t.webSocketDebuggerUrl);
    await new Promise((r) => ws.addEventListener("open", r, { once: true }));
    const p = new Page(ws);
    await p.send("Page.enable");
    await p.send("Runtime.enable");
    await p.send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 2, mobile: true });
    await p.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
    await p.send("Page.navigate", { url: `${BASE}/#/` });
    await sleep(1500);
    // A fresh start, as a first-time visitor: prepared data reset, nothing saved on the device.
    await p.eval(`fetch("/api/demo/reset", {method: "POST"}).then(() => { localStorage.clear();
      location.reload(); return true; })`);
    await sleep(2500);

    // ---- Riya: selfie -> face map -> history -> basket -> start plan -> try-on
    await p.go("/");
    await p.waitSel(".hero");
    await p.shot("01-home.png");

    await p.tap(".hero");
    await p.waitSel(".choices");
    await p.shot("02-basket-start.png");

    await p.tap(".row", "Use Riya's demo face");
    await p.waitSel("[role=radiogroup], .radiogroup");
    await sleep(800);
    await p.shot("03-questions-and-history-chips.png");

    await p.tap(".btn", "Build my basket");
    await p.waitSel(".bcards");
    await sleep(800);
    await p.shot("04-riya-basket-full.png");
    await p.shotEl("05-riya-face-map.png", ".facemap");
    await p.shotEl("06-riya-basket-cards.png", ".bcards");
    await p.shotEl("07-riya-skipped-with-reasons.png", ".skips");
    await p.shotEl("08-riya-start-plan.png", ".plan");

    // Paste any label: a fragranced label, checked against riya's history.
    await p.eval(`(() => { const t = document.querySelector(".paste__text");
      const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
      set.call(t, "Aqua, Glycerin, Alcohol Denat., Niacinamide, Parfum, Linalool");
      t.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
    await sleep(300);
    await p.tap("button", "Check it");
    await p.waitSel(".pasteres");
    await p.shotEl("09-paste-a-label.png", ".paste");

    await p.tap(".btn", "See the finish on you");
    await p.waitSel(".tryon");
    await sleep(600);
    await p.shot("10-try-on-matte-vs-dewy.png");

    // ---- Breakout helper (prepared scene)
    await p.api("/api/demo/scene/riya-breakout");
    await p.go("/");
    await p.tap(".moment__label", "broke out");
    await sleep(800);
    if (!(await p.eval(`!!document.querySelector(".symchip.is-on")`))) await p.tap(".symchip", "Cheeks");
    await p.tap(".symchip--none");
    await p.tap(".btn", "What changed?");
    await p.waitSel(".ranking", 20000);
    await p.shot("11-breakout-helper.png");

    // ---- Beginner: nothing tried yet, gentle start
    await p.go("/");
    await p.tap(".hero");
    await p.waitSel(".choices");
    await p.tap(".row", "Use a beginner demo face");
    await p.waitSel("[role=radiogroup], .radiogroup");
    await sleep(800);
    await p.shot("12-beginner-questions.png");
    await p.tap(".btn", "Build my basket");
    await p.waitSel(".bcards");
    await sleep(800);
    await p.shot("13-beginner-basket-full.png");
    await p.shotEl("14-beginner-basket-cards.png", ".bcards");
    await p.shotEl("15-beginner-start-plan.png", ".plan");

    // layout-check.json holds the multi-viewport check (scripts/layout-check.mjs); this is the 390 px set.
    writeFileSync(join(OUT, "shots-390.json"), JSON.stringify(report, null, 2));
    const bad = report.filter((r) => r.sideways);
    console.log(`\n${report.length} screens at ${W}px: ${bad.length} with sideways scroll, ${report.reduce((n, r) => n + r.small.length, 0)} small targets.`);
    ws.close();
  } finally {
    browser.kill();
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
