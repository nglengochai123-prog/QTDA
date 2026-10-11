// Món sẵn sàng: phục vụ thấy món đã pha xong kèm số bàn, bấm "Đã mang ra" (bấm lại không ghi thêm).
(function () {
  "use strict";
  var root = document.getElementById("ready-screen");
  if (!root) return;
  var queue = document.getElementById("ready-queue");
  var feedback = document.getElementById("ready-feedback");
  var busy = false;

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function refresh() {
    if (busy || document.hidden) return;
    fetch(root.dataset.queueUrl, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
      .then(function (html) { if (!busy) queue.innerHTML = html; })
      .catch(function () {});
  }
  function notify(kind, text) {
    feedback.innerHTML = "";
    if (!text) return;
    var box = document.createElement("div");
    box.className = "notice notice-" + kind;
    box.setAttribute("role", kind === "error" ? "alert" : "status");
    box.textContent = text;
    feedback.appendChild(box);
  }
  queue.addEventListener("click", function (event) {
    var button = event.target.closest("[data-serve]");
    if (!button || button.getAttribute("aria-busy") === "true") return;
    busy = true;
    button.setAttribute("aria-busy", "true");
    fetch(root.dataset.serveUrl, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ operation_key: button.dataset.op, line: Number(button.dataset.line) }),
    }).then(function (r) { return r.json(); })
      .then(function (data) { notify(data.ok ? "ok" : "error", data.ok ? (data.message || "Đã ghi mang ra.") : data.error); })
      .catch(function () {
        button.removeAttribute("aria-busy");
        notify("error", "Chưa chắc đã ghi được. Bấm lại cùng nút; hệ thống không ghi hai lần.");
      })
      .then(function () { busy = false; refresh(); });
  });
  setInterval(refresh, 3000);
})();
