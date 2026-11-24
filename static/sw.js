const CACHE_VERSION = "motoride-pwa-v24";
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;

const PRECACHE_URLS = [
  "/",
  "/customer",
  "/bookings",
  "/offline",
  "/manifest.webmanifest",
  "/static/css/style.css?v=24",
  "/static/js/pwa.js?v=23",
  "/static/js/calls.js?v=18",
  "/static/js/push.js?v=18",
  "/static/js/storefront.js?v=19",
  "/static/js/bookings.js?v=19",
  "/static/js/partner.js?v=22",
  "/static/assets/camiguin-hero.jpg?v=24",
  "/static/icons/icon-192.png?v=20",
  "/static/icons/icon-512.png?v=20",
  "/static/icons/icon.svg?v=20"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return Promise.allSettled(
        PRECACHE_URLS.map((url) => cache.add(new Request(url, { cache: "reload" })))
      );
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => !key.startsWith(CACHE_VERSION))
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Never cache admin or partner/rider endpoints/pages
  if (
    url.pathname.startsWith("/api/admin") ||
    url.pathname.startsWith("/admin") ||
    url.pathname.startsWith("/api/partner") ||
    url.pathname.startsWith("/partner") ||
    url.pathname.startsWith("/rider") ||
    url.pathname === "/shop"
  ) {
    return;
  }

  // Public read-only API: network-first with runtime cache fallback
  if (
    url.pathname.startsWith("/api/bikes") ||
    url.pathname === "/api/shops" ||
    url.pathname === "/api/settings"
  ) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Other API calls stay network-only
  if (url.pathname.startsWith("/api/")) {
    return;
  }

  // HTML Navigation: network-first, fallback to cached page or /offline
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          if (cached) return cached;
          return caches.match("/offline");
        })
    );
    return;
  }

  // App scripts & stylesheets: network-first so UI deploys never run stale JS behind fresh HTML
  if (url.pathname.startsWith("/static/js/") || url.pathname.startsWith("/static/css/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Media assets (icons/images): cache-first with background refresh
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const networkFetch = fetch(request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          })
          .catch(() => cached);

        return cached || networkFetch;
      })
    );
  }
});

// Web Push Notifications
self.addEventListener("push", (event) => {
  let data = {};
  if (event.data) {
    try {
      data = event.data.json();
    } catch (_) {
      data = { title: "Motorbike Rentals Camiguin", body: event.data.text() };
    }
  }
  const title = data.title || "Motorbike Rentals Camiguin";
  const options = {
    body: data.body || "",
    icon: data.icon || "/static/icons/icon-192.png?v=20",
    badge: "/static/icons/icon.svg?v=20",
    tag: data.tag || "motoride-notification",
    data: { url: data.url || "/" },
    vibrate: [250, 100, 250, 100, 400],
    requireInteraction: Boolean(data.requireInteraction),
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url && client.url.includes(targetUrl) && "focus" in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
