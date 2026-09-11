// Помощник приложения Архивуд (11.09.2026): только уведомления мессенджера.
// Ничего не кэширует — приложение всегда берётся свежим с сайта.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "Архивуд", {
    body: d.body || "Новое сообщение",
    icon: "ikonki/ikonka-192.png",
    badge: "ikonki/znachok-96.png",
    tag: d.tag || "archiwood",
    renotify: true,
    lang: "ru",
    data: { url: d.url || "./", chat: d.chat || "" },
  }));
});

self.addEventListener("notificationclick", e => {
  e.notification.close();
  const dannye = e.notification.data || {};
  const url = new URL(dannye.url || "./", self.registration.scope).href;
  e.waitUntil((async () => {
    const okna = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const o of okna) {
      if ("focus" in o) { o.postMessage({ chat: dannye.chat }); return o.focus(); }
    }
    return self.clients.openWindow(url);
  })());
});
