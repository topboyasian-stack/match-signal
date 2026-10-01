self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    let payload = {};
    try { payload = event.data ? event.data.json() : {}; } catch (_) {}
    const title = payload.title || "Match Signal";
    const body = payload.body || "A new Odds Builder batch is available.";
    const url = payload.url || "/odds-builder.html";
    const tag = payload.tag || "match-signal-odds-builder";
    await self.registration.showNotification(title, {
      body,
      tag,
      data: { url }
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification?.data?.url || "/odds-builder.html";
  event.waitUntil((async () => {
    const clients = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const same = clients.find((client) => {
      try { return new URL(client.url).pathname === new URL(url, self.location.origin).pathname; }
      catch (_) { return false; }
    });
    if (same) {
      await same.focus();
      if (same.navigate) await same.navigate(url);
      return;
    }
    await self.clients.openWindow(url);
  })());
});
