// Bật thông báo đẩy trên thiết bị này (NFR-17). Cần HTTPS (hoặc localhost), máy chủ đã cấu hình khóa VAPID.
(function () {
  const box = document.querySelector("[data-push]");
  if (!box) return;
  const text = box.querySelector("[data-push-text]");
  const button = box.querySelector("button");
  function say(msg) { text.textContent = msg; }
  function b64(key) {
    const pad = "=".repeat((4 - (key.length % 4)) % 4);
    const raw = atob((key + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    say("Trình duyệt này chưa hỗ trợ thông báo đẩy. Trên iPhone cần iOS 16.4 trở lên và thêm ứng dụng vào màn hình chính.");
    return;
  }
  if (!window.isSecureContext) { say("Thông báo đẩy cần mở ứng dụng qua HTTPS."); return; }
  fetch(box.dataset.statusUrl, { credentials: "same-origin" }).then((r) => r.json()).then((st) => {
    if (!st.ready) { say("Máy chủ chưa sẵn sàng gửi thông báo: " + st.reason); return; }
    say(st.devices ? "Đã bật trên " + st.devices + " thiết bị. Bấm để bật thêm trên thiết bị này." : "Chưa bật trên thiết bị nào.");
    button.hidden = false;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        if (await Notification.requestPermission() !== "granted") { say("Bạn chưa cho phép thông báo."); return; }
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(st.public_key) });
        const res = await fetch(box.dataset.subscribeUrl, {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": box.dataset.csrf },
          body: JSON.stringify(sub.toJSON()),
        });
        say(res.ok ? "Đã bật thông báo trên thiết bị này." : "Không lưu được đăng ký; thử lại.");
      } catch (e) {
        say("Không bật được thông báo: " + e.message);
      } finally { button.disabled = false; }
    });
  }).catch(() => say("Không kiểm tra được trạng thái thông báo."));
})();
