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
const API = "https://etf-alert.yuan780903.workers.dev";
self.addEventListener("push", e => {      // 雲端推播(不帶內容):收到後向雲端拿警示文字再跳出通知
  e.waitUntil((async () => {
    let items = [];
    try {
      const sub = await self.registration.pushManager.getSubscription();
      if (sub) items = (await (await fetch(API + "/pending?ep=" + encodeURIComponent(sub.endpoint), {cache: "no-store"})).json()).items || [];
    } catch (x) {}
    const url = self.registration.scope + "#vp";
    if (!items.length) return self.registration.showNotification("巴菲遠：有新的通知", {body: "點開查看最新的提醒", icon: "icon-192.png", badge: "favicon-32.png", tag: "rd-cloud", renotify: true, data: {url}});
    const allPf = items.every(x => x.code == "PF"), allMac = items.every(x => x.code == "MAC");
    const show = items.length > 3 ? [{title: `🔔 ${items.length} 則${allPf ? "配息提醒" : allMac ? "總經快訊" : "盤中警示"}`, body: items.slice(0, 4).map(x => x.title.replace(/^\S+\s/, "")).join("\n"), bad: allPf || allMac ? 0 : 1, id: "sum", code: allPf ? "PF" : allMac ? "MAC" : ""}] : items;
    for (const x of show) await self.registration.showNotification(x.title, {body: x.body, icon: "icon-192.png", badge: "favicon-32.png", tag: "rd-" + (x.id || Date.now()), renotify: true, requireInteraction: !!x.bad, vibrate: x.bad ? [300, 120, 300, 120, 300] : [150], data: {url: x.code == "BRIEF" ? self.registration.scope + "#mkt" : x.code == "PF" ? self.registration.scope + "#calc" : x.code == "MAC" ? self.registration.scope + "#macro" : url}});   // 盤勢摘要點開到大盤頁、配息提醒到配息試算頁
  })());
});
