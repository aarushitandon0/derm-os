// Minimal offline shell. API calls always go to the network: verdicts must be fresh.
// Never cached, by rule (frontend/scripts/check-sw.mjs proves it): any request with an
// Authorization header, anything under /api (including /api/me, the account endpoints) or /media,
// any other origin (the API host, Supabase sign-in), and any response marked no-store or private.
const CACHE = "dermos-shell-v2";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/index.html", "/manifest.webmanifest", "/icon.svg"])));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});

function cacheable(req) {
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return false;
  if (req.method !== "GET") return false;
  if (req.headers.has("authorization")) return false;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/media")) return false;
  return true;
}

function storable(res) {
  if (!res || !res.ok || res.type === "opaque") return false;
  const cc = (res.headers.get("cache-control") || "").toLowerCase();
  return !/no-store|private/.test(cc);
}

self.addEventListener("fetch", (e) => {
  if (!cacheable(e.request)) return; // straight to the network, nothing kept
  e.respondWith(
    fetch(e.request)
      .then((r) => {
        if (storable(r)) {
          const copy = r.clone();
          caches.open(CACHE).then((c) => c.put(e.request, copy));
        }
        return r;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/index.html")))
  );
});
