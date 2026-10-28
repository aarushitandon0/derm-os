// 390 px screenshots of the demo, plus a layout check on every screen.
//
//   1. API in demo mode:   cd backend; $env:DEMO_MODE="1"; python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
//   2. App (dev build, for the simulated camera):
//        cd frontend; $env:DERMOS_API_PROXY="http://127.0.0.1:8010"; npx vite --host 127.0.0.1 --port 5180
//   3. node scripts/screenshots.mjs [--base http://127.0.0.1:5180] [--out ../docs/screenshots]
//
// Drives headless Chrome (or Edge) over the DevTools protocol with Node's built-in WebSocket: no
// installs, no camera, no face photo (the capture screens use the dev-only simulated camera,
// `&preview=`). Clicks through the real guided demo. Reduced motion is on, so nothing is mid-animation.
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
    // A fresh start: first launch, prepared data reset.
    await p.eval(`fetch("/api/demo/reset", {method: "POST"}).then(() => { localStorage.clear(); location.reload(); return true; })`);
    await sleep(2000);

    await p.waitText("Same face, same light");
    await p.shot("01-landing.png");

    await p.click("Try the 90-second demo");
    await p.waitText("The 90-second demo");
    await p.shot("02-guided-demo-start.png");

    await p.click("Start the demo");
    await p.waitText("Step 1 of 8");
    await p.waitText("Velvet Rose");
    await p.shot("03-guided-history.png");

    await p.click("Next");
    await p.waitText("Step 2 of 8");
    await p.waitText("Label line");
    await p.shot("04-compare-blocked-inci.png");

    await p.click("Next");
    await p.waitText("Step 3 of 8");
    await sleep(800);
    await p.shot("05-trial-baseline.png");

    await p.click("Next");
    await p.waitText("Step 4 of 8");
    await p.waitText("Not comparable");
    await p.shot("07-not-comparable-reguide.png");

    await p.click("Next");
    await p.waitText("Step 5 of 8");
    await p.waitText("Rebuy?");
    await p.shot("08-evidence-riya-day14-rebuy.png");

    await p.click("Next");
    await p.waitText("Step 6 of 8");
    await p.waitText("Rebuy?");
    await p.shot("09-stop-card.png");

    await p.click("Next");
    await p.waitText("Step 7 of 8");
    await p.waitText("Key points");
    await p.shot("10-visit-brief.png");

    await p.click("Next");
    await p.waitText("Step 8 of 8");
    await p.waitText("Redness dropped beyond your usual variation");
    await p.shot("11-evidence-meera-moved-rebuy.png");

    // Capture with the dev-only simulated camera (no camera, no face photo).
    await p.click("Finish");
    await p.go("/capture?mode=checkin&trial=demo-riya-lamp&preview=countdown");
    await sleep(1200);
    await p.shot("06-capture-simulated.png");
    await p.go("/capture?mode=checkin&trial=demo-riya-lamp&preview=warm");
    await sleep(1200);
    await p.shot("06b-capture-warm-light-warning.png");

    writeFileSync(join(OUT, "layout-check.json"), JSON.stringify(report, null, 2));
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
