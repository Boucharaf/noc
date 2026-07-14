import { precacheAndRoute } from "workbox-precaching";

precacheAndRoute(self.__WB_MANIFEST);

// registerType: "autoUpdate" (main.jsx's registerSW) posts this message once
// a new service worker has installed and is waiting to activate. Without
// this listener the new worker sits idle indefinitely — every open tab keeps
// running the OLD worker (and its stale cached JS) until every tab for this
// origin is closed, which reads as "my fix didn't do anything."
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") self.skipWaiting();
});

self.addEventListener("push", (event) => {
  let payload = { title: "NOC Dashboard", body: "Nouvel incident" };
  try {
    if (event.data) payload = event.data.json();
  } catch {
    // non-JSON push payload (shouldn't happen — the backend always sends JSON)
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: "/icon-192.png",
      badge: "/favicon-32x32.png",
      tag: "noc-incident",
      renotify: true,
      data: { url: payload.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
