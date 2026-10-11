// Hành vi chung của khung ứng dụng. Không phụ thuộc thư viện ngoài.
(function () {
  "use strict";

  // --- Service worker (cài lên màn hình chính) ---
  if ("serviceWorker" in navigator && document.body.dataset.swUrl) {
    navigator.serviceWorker.register(document.body.dataset.swUrl, { scope: "/" }).catch(function () {});
  }

  // --- Cảnh báo mất kết nối trong vòng 10 giây (NFR-16) ---
  var banner = document.getElementById("offline-banner");
  var healthUrl = document.body.dataset.healthUrl;
  var offline = false;

  function setOffline(value) {
    if (value === offline || !banner) return;
    offline = value;
    banner.hidden = !value;
    document.documentElement.classList.toggle("is-offline", value);
  }

  function probe() {
    if (!healthUrl || !window.fetch) return;
    var controller = "AbortController" in window ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, 4000);
    fetch(healthUrl, { cache: "no-store", credentials: "same-origin", signal: controller && controller.signal })
      .then(function (r) { setOffline(!r.ok); })
      .catch(function () { setOffline(true); })
      .then(function () { clearTimeout(timer); });
  }

  window.addEventListener("offline", function () { setOffline(true); });
  window.addEventListener("online", probe);
  if (!navigator.onLine) setOffline(true);
  setInterval(probe, 5000);

  // --- Báo món đã pha xong cho phục vụ, kèm số bàn (AC-06) ---
  var readyUrl = document.body.dataset.readyCountUrl;
  var readyBanner = document.getElementById("ready-banner");
  function pollReady() {
    if (!readyUrl || !readyBanner || document.hidden || offline) return;
    fetch(readyUrl, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        var onReadyPage = location.pathname === readyBanner.getAttribute("href");
        readyBanner.hidden = !data.count || onReadyPage;
        readyBanner.querySelector("[data-text]").textContent =
          data.count + " món đã pha xong · Bàn " + data.tables.join(", ");
      })
      .catch(function () {});
  }
  if (readyUrl) { pollReady(); setInterval(pollReady, 5000); }

  // --- Báo yêu cầu điều chỉnh đang chờ chính người dùng này duyệt (FR-11) ---
  var approvalsUrl = document.body.dataset.approvalsCountUrl;
  var approvalsBanner = document.getElementById("approvals-banner");
  function pollApprovals() {
    if (!approvalsUrl || !approvalsBanner || document.hidden || offline) return;
    fetch(approvalsUrl, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        approvalsBanner.hidden = !data.count || location.pathname === approvalsBanner.getAttribute("href");
        approvalsBanner.querySelector("[data-text]").textContent = data.count + " yêu cầu điều chỉnh chờ bạn duyệt";
      })
      .catch(function () {});
  }
  if (approvalsUrl) { pollApprovals(); setInterval(pollApprovals, 5000); }

  // --- Báo nhanh nguyên liệu chưa xử lý, cho Quản lý ca và Chủ quán (FR-23, AC-51) ---
  var stockUrl = document.body.dataset.quickReportCountUrl;
  var stockBanner = document.getElementById("stock-banner");
  function pollStock() {
    if (!stockUrl || !stockBanner || document.hidden || offline) return;
    fetch(stockUrl, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        stockBanner.hidden = !data.count || location.pathname === stockBanner.getAttribute("href");
        stockBanner.querySelector("[data-text]").textContent = "Báo nguyên liệu: " + data.items.join(" · ") +
          (data.count > data.items.length ? " và " + (data.count - data.items.length) + " báo khác" : "");
      })
      .catch(function () {});
  }
  if (stockUrl) { pollStock(); setInterval(pollStock, 5000); }

  // --- Hiện/ẩn mật khẩu ---
  document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("aria-controls"));
    if (!input) return;
    button.hidden = false;
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Ẩn" : "Hiện";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      input.focus();
    });
  });

  // --- Chống bấm gửi hai lần ---
  document.querySelectorAll("form[data-once]").forEach(function (form) {
    form.addEventListener("submit", function () {
      var button = form.querySelector("[type=submit]");
      if (button) {
        button.setAttribute("aria-busy", "true");
        if (button.dataset.busyText) button.textContent = button.dataset.busyText;
        setTimeout(function () { button.disabled = true; }, 0);
      }
    });
  });
})();
