{% load static %}// Service worker tối thiểu: cài lên màn hình chính và hiện trang mất kết nối có đủ giao diện.
// Lưu nháp, đồng bộ lại và Web Push sẽ bổ sung ở các phần sau (NFR-16, NFR-17).
const CACHE = "lam-shell-v2";
const OFFLINE_URL = "{% url 'core:offline' %}";
const SHELL = [OFFLINE_URL, "{% static 'css/app.css' %}", "{% static 'js/app.js' %}"];

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
