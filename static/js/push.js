// Thông báo đẩy (NFR-17): bật trên thiết bị, gửi thử, xem ba mốc gửi, dịch vụ đẩy nhận, điện thoại hiện.
(function () {
  const box = document.querySelector("[data-push]");
  if (!box) return;
  const text = box.querySelector("[data-push-text]");
  const enable = box.querySelector("[data-push-enable]");
  const test = box.querySelector("[data-push-test]");
  const log = box.querySelector("[data-push-log]");
  const post = (url, body) => fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": box.dataset.csrf }, body: body || "{}",
  });
  // Thẻ của nhân viên ẩn sẵn, chỉ hiện khi có điều cần nói, để trang không giật khi máy chủ chưa bật thông báo.
  const say = (msg) => { text.textContent = msg; box.hidden = false; };
  const time = (iso) => iso ? new Date(iso).toLocaleTimeString("vi-VN") : "—";
  function b64(key) {
    const pad = "=".repeat((4 - (key.length % 4)) % 4);
    const raw = atob((key + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from(raw, (c) => c.charCodeAt(0));
  }
  function cell(row, value) { const td = document.createElement("td"); td.textContent = value; row.appendChild(td); }
  async function refreshLog() {
    if (!log) return;
    const data = await (await fetch(box.dataset.logUrl, { credentials: "same-origin" })).json();
    const body = log.querySelector("tbody");
    body.textContent = "";
    data.messages.forEach((m) => {
      const tr = document.createElement("tr");
      const th = document.createElement("th"); th.scope = "row"; th.textContent = m.title; tr.appendChild(th);
      cell(tr, time(m.sent));
      cell(tr, m.accepted ? "Có (mã " + m.codes.join(", ") + ")" : "Không (mã " + m.codes.join(", ") + ")");
      cell(tr, m.received ? time(m.received) : "Chưa");
      cell(tr, m.opened ? time(m.opened) : "Chưa");
      body.appendChild(tr);
    });
    log.hidden = !data.messages.length;
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    say("Trình duyệt này chưa hỗ trợ thông báo đẩy. Trên iPhone cần iOS 16.4 trở lên và mở ứng dụng từ biểu tượng đã thêm vào màn hình chính.");
    return;
  }
  if (!window.isSecureContext) { say("Thông báo đẩy cần mở ứng dụng qua HTTPS."); return; }
  fetch(box.dataset.statusUrl, { credentials: "same-origin" }).then((r) => r.json()).then(async (st) => {
    if (!st.ready) {
      // Nhân viên không sửa được cấu hình máy chủ: ẩn thẻ, hoặc ở trang Cảnh báo chỉ nói ngắn gọn;
      // Chủ quán xem lý do kỹ thuật để chuyển cho người cài đặt máy chủ.
      if (!log) { box.hidden = true; return; }
      if (!("owner" in box.dataset)) { say("Quán chưa bật thông báo trên điện thoại. Khi Chủ quán bật, bạn sẽ bật được ở đây."); return; }
      say("Chưa gửi được thông báo lên điện thoại. " + st.reason + " Người cài đặt máy chủ cần xử lý việc này."); return;
    }
    const reg = await navigator.serviceWorker.ready;
    const current = await reg.pushManager.getSubscription();
    say(current ? "Thiết bị này đã bật thông báo." : (Notification.permission === "denied"
      ? "Bạn đã chặn thông báo cho trang này; mở cài đặt trình duyệt để cho phép lại."
      : "Thiết bị này chưa bật thông báo."));
    enable.hidden = !!current;
    test.hidden = !st.devices && !current;
    refreshLog();
    enable.addEventListener("click", async () => {
      enable.disabled = true;
      try {
        if (await Notification.requestPermission() !== "granted") { say("Bạn chưa cho phép thông báo."); return; }
        const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(st.public_key) });
        const res = await post(box.dataset.subscribeUrl, JSON.stringify(sub.toJSON()));
        try { if (res.ok) localStorage.setItem("lam-push-user", document.body.dataset.user || ""); } catch (e) {}
        say(res.ok ? "Đã bật thông báo trên thiết bị này. Bấm Gửi thử để kiểm tra." : "Không lưu được đăng ký; thử lại.");
        enable.hidden = res.ok; test.hidden = !res.ok;
      } catch (e) { say("Không bật được thông báo: " + e.message); } finally { enable.disabled = false; }
    });
    test.addEventListener("click", async () => {
      test.disabled = true;
      const r = await (await post(box.dataset.testUrl)).json();
      say(r.ok ? "Máy chủ đã gửi; dịch vụ đẩy đã nhận cho " + r.accepted + " thiết bị. Chờ xem điện thoại có hiện thông báo không."
               : "Không gửi được: " + r.reason);
      test.disabled = false;
      setTimeout(refreshLog, 3000); setTimeout(refreshLog, 10000);
    });
  }).catch(() => say("Không kiểm tra được trạng thái thông báo."));
})();
