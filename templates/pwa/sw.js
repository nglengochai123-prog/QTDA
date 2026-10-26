{% load static %}// Service worker tối thiểu: cài lên màn hình chính và hiện trang mất kết nối có đủ giao diện.
// Nhận thông báo đẩy (NFR-17): hiện thông báo kể cả khi ứng dụng đóng, chạm vào mở đúng màn hình.
const CACHE = "lam-shell-v5";
const OFFLINE_URL = "{% url 'core:offline' %}";
// Giao diện dùng chữ hệ thống của máy nên không cần lưu tệp phông.
const SHELL = [OFFLINE_URL, "{% static 'css/app.css' %}", "{% static 'js/app.js' %}", "{% static 'js/charts.js' %}"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
    return;
  }
  // Tệp giao diện: luôn lấy bản mới, chỉ dùng bản đã lưu khi mất mạng.
  if (request.method === "GET" && SHELL.some((url) => new URL(request.url).pathname === url)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});

self.addEventListener("push", (event) => {
  let data = { title: "LAM Coffee", body: "", url: "/canh-bao/" };
  try { data = Object.assign(data, event.data ? event.data.json() : {}); } catch (e) { /* nội dung không phải JSON */ }
  event.waitUntil(
    self.registration.showNotification(data.title, { body: data.body, data: data, tag: data.id || data.url })
      // Báo máy chủ: điện thoại đã thực sự hiện thông báo (khác với dịch vụ đẩy đã nhận).
      .then(() => data.receipt ? fetch(data.receipt, { method: "POST" }).catch(() => {}) : null)
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const info = event.notification.data || {};
  const url = info.url || "/";
  if (info.opened) fetch(info.opened, { method: "POST" }).catch(() => {});
  event.waitUntil(clients.matchAll({ type: "window" }).then((list) => {
    for (const client of list) { if ("focus" in client) { client.navigate(url); return client.focus(); } }
    return clients.openWindow(url);
  }));
});
