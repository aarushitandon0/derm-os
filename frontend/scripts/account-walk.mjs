// Account walk, as a FIRST-TIME visitor at 390x844 and 1440x900. Spends no YouCam units, and never
// talks to a real Supabase project.
//
//   Guest (the normal local setup, no VITE_SUPABASE_* env):
//     API on 8000 (DEMO_MODE=1, empty key), app on 5180.
//     Checks: Riya's demo basket works with no login, no login UI is shown, 0 console errors.
//
//   Account (optional, --account): a stand-in that never leaves this machine.
//     API on 8001 with SUPABASE_URL=https://localtest.supabase.co and a throwaway
//     SUPABASE_JWT_SECRET (the legacy HS256 path), app on 5181 with VITE_SUPABASE_URL set to the
//     same fake URL. The test signs its own token with that secret and puts the session where
//     supabase-js keeps it; every request to the fake Supabase host is answered locally.
//     Checks: "Log in" in the header, save Riya's basket, see it on the profile after a reload,
//     the device-history question (answer "No" sends nothing), tap targets and sideways scroll.
//
//   node scripts/account-walk.mjs [--account] [--secret <same as the API's>] [--out <dir>]
import { createRequire } from "node:module";
import { createHmac, randomUUID } from "node:crypto";
import { existsSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_DIR ? join(process.env.PLAYWRIGHT_DIR, "index.js") : "playwright");
const arg = (k, d) => {
  const i = process.argv.indexOf(k);
  return i > 0 ? process.argv[i + 1] : d;
};
const ACCOUNT = process.argv.includes("--account");
const OUT = resolve(arg("--out", "../docs/screenshots"));
const SECRET = arg("--secret", process.env.WALK_JWT_SECRET ?? "");
const FAKE = "https://localtest.supabase.co";
const SIZES = [
  [390, 844, true],
  [1440, 900, false],
];
mkdirSync(OUT, { recursive: true });

const b64 = (o) => Buffer.from(typeof o === "string" ? o : JSON.stringify(o)).toString("base64url");
function hs256(payload) {
  const h = b64({ alg: "HS256", typ: "JWT" });
  const p = b64(payload);
  return `${h}.${p}.${createHmac("sha256", SECRET).update(`${h}.${p}`).digest("base64url")}`;
}

const audit = (touch) => {
  const doc = document.documentElement;
  const small = [];
  if (touch)
    for (const el of document.querySelectorAll("a, button, input, select, [role=tab]")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0 || getComputedStyle(el).visibility === "hidden") continue;
      if (el.type === "checkbox") continue; // the whole label row is the target (44 px)
      if (r.height < 44 || r.width < 44) small.push(`${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute("aria-label") || "").trim().slice(0, 30)}" ${Math.round(r.width)}x${Math.round(r.height)}`);
    }
  return { scroll: doc.scrollWidth > doc.clientWidth + 1, small };
};

let failures = 0;
const fail = (m) => {
  failures++;
  console.log(`FAIL ${m}`);
};

const exe = [process.env.CHROME_PATH, "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "/usr/bin/google-chrome",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].filter(Boolean).find((x) => existsSync(x));
const browser = await chromium.launch({ headless: true, ...(exe ? { executablePath: exe } : {}) });
for (const [w, h, touch] of SIZES) {
  const tag = `${w}x${h}`;
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, hasTouch: touch, isMobile: touch });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 160)));
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 160)));
  const base = ACCOUNT ? "http://127.0.0.1:5181" : "http://127.0.0.1:5180";

  if (ACCOUNT) {
    // Nothing may reach a real sign-in service: the fake host answers locally.
    await page.route(`${FAKE}/**`, (r) => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  }

  // First-time visitor.
  await page.goto(`${base}/#/`);
  await page.evaluate(() => fetch("/api/demo/reset", { method: "POST" }).then(() => localStorage.clear()));
  await page.reload();
  await page.waitForSelector(".hero");
  const loginLink = await page.locator(".acctbtn").count();

  if (!ACCOUNT) {
    if (loginLink) fail(`${tag} login UI shown with no Supabase env`);
    await page.click(".hero");
    await page.waitForSelector(".choices");
    await page.click(".trybtn >> text=Use Riya's demo face").catch(() => page.click("text=Use Riya's demo face"));
    await page.waitForSelector("[role=radiogroup]");
    await page.click(".btn >> text=Build my basket");
    await page.waitForSelector(".bcards");
    const cards = await page.locator(".bcards > li").count();
    const save = await page.locator("text=Save this basket to your profile").count();
    if (!cards) fail(`${tag} no basket cards`);
    if (save) fail(`${tag} save button shown with no Supabase env`);
    await page.goto(`${base}/#/profile`);
    await page.waitForSelector("text=Accounts aren't set up");
    const a = await page.evaluate(audit, touch);
    if (a.scroll) fail(`${tag} sideways scroll`);
    console.log(`${tag} guest: basket cards ${cards}, login UI ${loginLink}, save button ${save}, console errors ${errors.length}`);
  } else {
    if (!SECRET) throw new Error("--account needs --secret (the stand-in API's SUPABASE_JWT_SECRET)");
    if (!loginLink) fail(`${tag} no "Log in" in the header`);
    // Guest on the basket: the save button opens the log-in form right there.
    await page.click(".hero");
    await page.waitForSelector(".choices");
    await page.click("text=Use Riya's demo face");
    await page.waitForSelector("[role=radiogroup]");
    await page.click(".btn >> text=Build my basket");
    await page.waitForSelector(".bcards");
    await page.click("text=Save this basket to your profile");
    await page.waitForSelector(".authform");
    if (w === 390) await page.locator(".savecard").screenshot({ path: join(OUT, "19-save-basket-login-390.png") });

    // "Log in": a session as supabase-js stores it, signed with the stand-in's secret.
    const uid = randomUUID();
    const now = Math.floor(Date.now() / 1000);
    const access = hs256({ sub: uid, aud: "authenticated", iss: `${FAKE}/auth/v1`, iat: now, exp: now + 3600,
                           role: "authenticated", email: "walk@example.com" });
    const session = { access_token: access, refresh_token: "r", token_type: "bearer", expires_in: 3600,
                      expires_at: now + 3600, user: { id: uid, aud: "authenticated", email: "walk@example.com",
                                                     app_metadata: {}, user_metadata: {}, created_at: new Date().toISOString() } };
    // History typed on this device before logging in: the question must appear, and "No" sends nothing.
    await page.evaluate(([s]) => {
      localStorage.setItem("sb-localtest-auth-token", JSON.stringify(s));
      localStorage.setItem("dermos.device.history", JSON.stringify({ chips: [{ chip: "vitamin_c", reaction: "itched" }], records: [], shelf: [] }));
    }, [session]);
    await page.reload();
    await page.waitForSelector(".importprompt");
    if (w === 390) await page.locator(".importprompt").screenshot({ path: join(OUT, "20-import-question-390.png") });
    await page.click(".importprompt >> text=No");
    await page.waitForSelector(".importprompt", { state: "detached" });

    // Build Riya's basket again (now logged in) and save it.
    await page.goto(`${base}/#/basket`);
    await page.click("text=Use Riya's demo face");
    await page.waitForSelector("[role=radiogroup]");
    await page.click(".btn >> text=Build my basket");
    await page.waitForSelector(".bcards");
    await page.click("text=Save this basket to your profile");
    await page.waitForSelector("text=Saved to your profile");

    // Reload the profile: the basket is still there; the "No" answer imported nothing.
    await page.goto(`${base}/#/profile`);
    await page.reload();
    await page.waitForSelector(".saved");
    const baskets = await page.locator(".savedlist").first().locator(".saved").count();
    const chipsShown = await page.locator(".editlist").first().locator("li").count();
    const again = await page.locator(".importprompt").count();
    if (baskets !== 1) fail(`${tag} expected 1 saved basket, saw ${baskets}`);
    if (chipsShown !== 0) fail(`${tag} "No" still imported ${chipsShown} chip(s)`);
    if (again) fail(`${tag} the import question was asked twice`);
    await page.click(".saved >> text=Open");
    await page.waitForTimeout(200);
    const a = await page.evaluate(audit, touch);
    if (a.scroll) fail(`${tag} profile sideways scroll`);
    if (a.small.length) fail(`${tag} small tap targets: ${a.small.join("; ")}`);
    await page.screenshot({ path: join(OUT, `21-profile-${w}.png`), fullPage: true });

    const flowErrors = errors.length;
    // Without a token the account API answers 401, never someone else's data. (The browser logs
    // that 401 itself, so console errors are counted before this probe.)
    const anon = await page.evaluate(() => fetch("/api/me/baskets").then((r) => r.status));
    if (anon !== 401) fail(`${tag} /api/me/baskets without a token answered ${anon}`);
    console.log(`${tag} account: saved baskets ${baskets}, imported on "No" ${chipsShown}, no-token status ${anon}, small targets ${a.small.length}, console errors ${flowErrors}`);
    errors.length = flowErrors;
  }
  if (errors.length) fail(`${tag} console errors: ${errors.join(" | ")}`);
  await ctx.close();
}
await browser.close();
console.log(failures ? `${failures} failure(s)` : `account walk (${ACCOUNT ? "account" : "guest"}): 0 failures`);
process.exit(failures ? 1 : 0);
