/* 巴菲遠 Service Worker:只負責跳出通知與點通知回到網站(不做離線快取,避免看到舊資料) */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("notificationclick", e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || self.registration.scope;
  e.waitUntil(self.clients.matchAll({type: "window", includeUncontrolled: true}).then(list => {
    for (const c of list) if (c.url.startsWith(self.registration.scope)) { c.focus(); c.navigate && c.navigate(url).catch(() => {}); return; }
    return self.clients.openWindow(url);
  }));
});
self.addEventListener("push", e => {   // 預留:之後接伺服器推播(網站關閉也能收到)
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (x) { d = {title: "巴菲遠", body: e.data && e.data.text()}; }
  e.waitUntil(self.registration.showNotification(d.title || "巴菲遠警示", {body: d.body || "", icon: "icon-192.png", badge: "favicon-32.png", tag: d.tag, renotify: true, requireInteraction: true, data: {url: d.url || self.registration.scope + "#vp"}}));
});
