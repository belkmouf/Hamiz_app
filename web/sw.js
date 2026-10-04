/* Hamiz Pulse service worker: app shell cache-first, report data network-first with the last copy as offline fallback. */
const VERSION = "pulse-v1";
const SHELL = ["/", "/styles.css", "/calc.js", "/app.js", "/manifest.webmanifest", "/icons/icon.svg", "/icons/icon-192.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/auth/") || url.pathname === "/login") return;
  if (url.pathname === "/api/reports") {
    e.respondWith(fetch(e.request).then(r => {
      if (r.ok) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(e.request, copy)); }
      return r;
    }).catch(() => caches.match(e.request).then(r => r || Response.error())));
    return;
  }
  if (url.pathname.startsWith("/api/")) return;
  // Shell: network first so deploys show up, cache as fallback for offline starts.
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && !r.redirected) { const copy = r.clone(); caches.open(VERSION).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request).then(r => r || Response.error())));
});
