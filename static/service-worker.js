const CACHE_NAME = "modulus-static-v68";
const STATIC_ASSETS = [
  "/static/css/app.css?v=20261026-11",
  "/static/js/student-dashboard.js?v=20261026-4",
  "/static/js/curriculum-selects.js",
  "/static/js/study-planner.js?v=20261023-8",
  "/static/js/topic-practice.js?v=20261024-1",
  "/static/js/sms-ajax.js",
  "/static/js/student-resource-tabs.js?v=20261026-1",
  "/static/js/install-app.js?v=20261015-1",
  "/static/images/Nav.png",
  "/static/images/Nav-192.png",
  "/static/images/Nav-512.png",
  "/static/images/modulus-logo.png",
  "/static/images/dark_logo.png"
];
const STATIC_ASSET_PATHS = new Set(STATIC_ASSETS.map((asset) => new URL(asset, self.location.origin).pathname));

function cacheKeyFor(request, url) {
  if (url.pathname === "/static/css/app.css") {
    return new URL("/static/css/app.css?v=20261026-11", self.location.origin);
  }
  if (url.pathname === "/static/js/student-dashboard.js") {
    return new URL("/static/js/student-dashboard.js?v=20261026-4", self.location.origin);
  }
  if (url.pathname === "/static/js/study-planner.js") {
    return new URL("/static/js/study-planner.js?v=20261023-8", self.location.origin);
  }
  if (url.pathname === "/static/js/topic-practice.js") {
    return new URL("/static/js/topic-practice.js?v=20261024-1", self.location.origin);
  }
  if (url.pathname === "/static/js/install-app.js") {
    return new URL("/static/js/install-app.js?v=20261015-1", self.location.origin);
  }
  if (url.pathname === "/static/js/student-resource-tabs.js") {
    return new URL("/static/js/student-resource-tabs.js?v=20261026-1", self.location.origin);
  }
  return url.pathname;
}

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => Promise.all(
        cacheNames
          .filter((cacheName) => cacheName.startsWith("modulus-static-") && cacheName !== CACHE_NAME)
          .map((cacheName) => caches.delete(cacheName))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => new Response("You are offline. Please reconnect and try again.", {
        status: 503,
        statusText: "Service Unavailable",
        headers: { "Content-Type": "text/plain; charset=utf-8" }
      }))
    );
    return;
  }

  if (!STATIC_ASSET_PATHS.has(url.pathname)) {
    return;
  }

  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cacheKey = cacheKeyFor(request, url);
      const cachedResponse = await cache.match(cacheKey);
      if (cachedResponse) {
        return cachedResponse;
      }

      const response = await fetch(request);
      if (response.ok && response.type === "basic") {
        await cache.put(cacheKey, response.clone());
      }
      return response;
    })
  );
});
