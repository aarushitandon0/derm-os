// Proves the service worker never caches an authenticated request or a user-data response.
// Runs public/sw.js in a sandbox with fake fetch / caches, fires fetch events, and counts cache writes.
//   node scripts/check-sw.mjs        (exit 1 on any failure; run in CI)
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "..", "public", "sw.js"), "utf8");
const ORIGIN = "https://dermos.example";

function run(req, resHeaders = {}) {
  const listeners = {};
  const puts = [];
  let responded = false;
  const cache = { put: (r) => puts.push(r.url), addAll: async () => {}, match: async () => undefined };
  const sandbox = {
    URL,
    self: {
      location: { origin: ORIGIN },
      addEventListener: (t, f) => (listeners[t] = f),
      skipWaiting() {},
      clients: { claim() {} },
    },
    caches: { open: async () => cache, keys: async () => [], delete: async () => true, match: async () => undefined },
    fetch: async () => new Response("{}", { status: 200, headers: resHeaders }),
  };
  vm.runInNewContext(src, sandbox);
  let done = Promise.resolve();
  listeners.fetch({
    request: req,
    respondWith: (p) => {
      responded = true;
      done = Promise.resolve(p);
    },
  });
  return done.then(() => new Promise((r) => setTimeout(r, 10))).then(() => ({ puts, responded }));
}

const R = (path, init = {}) => new Request(ORIGIN + path, init);
const cases = [
  // [name, request, response headers, expect cached]
  ["shell page is cached", R("/index.html"), {}, true],
  ["Authorization header on a page", R("/index.html", { headers: { Authorization: "Bearer x" } }), {}, false],
  ["account endpoint /api/me", R("/api/me"), {}, false],
  ["account endpoint with token", R("/api/me/baskets", { headers: { Authorization: "Bearer x" } }), {}, false],
  ["account export", R("/api/me/export", { headers: { Authorization: "Bearer x" } }), {}, false],
  ["any /api call", R("/api/health"), {}, false],
  ["/media", R("/media/x.png"), {}, false],
  ["no-store response", R("/some.js"), { "cache-control": "no-store, private" }, false],
  ["private response", R("/some.js"), { "cache-control": "private" }, false],
  ["other origin (Supabase)", new Request("https://proj.supabase.co/auth/v1/user", { headers: { Authorization: "Bearer x" } }), {}, false],
  ["POST", R("/index.html", { method: "POST", body: "x" }), {}, false],
];

let bad = 0;
for (const [name, req, headers, expect] of cases) {
  const { puts } = await run(req, headers);
  const cached = puts.length > 0;
  const ok = cached === expect;
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}: ${cached ? "cached" : "not cached"}`);
}
console.log(bad ? `${bad} failure(s)` : `service worker: ${cases.length} cases, 0 authenticated responses cached`);
process.exit(bad ? 1 : 0);
