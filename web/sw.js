/* Hamiz Pulse service worker.
   App shell: network-first, cache only as an offline fallback.
   API and auth: network only, cache: "no-store". Never keep a report response. */
const VERSION = "pulse-v3";
const SHELL = ["/", "/styles.css", "/calc.js", "/app.js", "/i18n.js", "/manifest.webmanifest", "/icons/icon.svg", "/icons/icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function networkOnly(request) {
  return fetch(new Request(request, {cache: "no-store"}));
}

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/auth/") || url.pathname === "/login") {
    e.respondWith(networkOnly(e.request));
    return;
  }
  e.respondWith(fetch(new Request(e.request, {cache: "no-store"})).then(r => {
    if (r.ok && !r.redirected) {
      const copy = r.clone();
      caches.open(VERSION).then(c => c.put(e.request, copy));
    }
    return r;
  }).catch(() => caches.match(e.request).then(r => r || Response.error())));
});
