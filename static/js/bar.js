// Quầy pha chế: tự cập nhật hàng chờ; mỗi nút "Xong" mang mã nghiệp vụ riêng nên bấm nhiều lần chỉ trừ kho một lần.
(function () {
  "use strict";
  var root = document.getElementById("bar-screen");
  if (!root) return;
  var queue = document.getElementById("bar-queue");
  var status = document.getElementById("bar-refresh");
  var feedback = document.getElementById("bar-feedback");
  var busy = false;
  var seen = null;
  var autoPrint = document.getElementById("auto-print");
  if (autoPrint) {
    try { autoPrint.checked = localStorage.getItem("lam-auto-print") === "1"; } catch (e) {}
    autoPrint.addEventListener("change", function () {
      try { localStorage.setItem("lam-auto-print", autoPrint.checked ? "1" : "0"); } catch (e) {}
    });
  }

  // Phiếu mới xuất hiện lần đầu thì có một chuyển động ngắn; các lần cập nhật sau thì đứng yên.
  function markArrivals() {
    var ids = Array.prototype.map.call(queue.querySelectorAll(".bar-ticket"), function (t) {
      return t.getAttribute("aria-labelledby");
    });
    if (seen) {
      queue.querySelectorAll(".bar-ticket").forEach(function (t) {
        if (seen.indexOf(t.getAttribute("aria-labelledby")) < 0) {
          t.classList.add("arrive");
          if (autoPrint && autoPrint.checked) {
            var link = t.querySelector("[data-print]");
            if (link) window.open(link.href + "?in=1", "_blank");
          }
        }
      });
    }
    seen = ids;
  }

  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function refresh() {
    if (busy || document.hidden) return;
    fetch(root.dataset.queueUrl, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(); return r.text(); })
      .then(function (html) {
        if (busy) return;
        queue.innerHTML = html;
        markArrivals();
        var t = new Date();
        status.textContent = "Cập nhật lúc " + t.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      })
      .catch(function () { status.textContent = "Không cập nhật được, đang thử lại…"; });
  }
  var clearTimer = null;
  function notify(kind, text) {
    feedback.innerHTML = "";
    clearTimeout(clearTimer);
    if (!text) return;
    var box = document.createElement("div");
    box.className = "notice notice-" + kind;
    box.setAttribute("role", kind === "error" ? "alert" : "status");
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(ns, "use");
    use.setAttribute("href", kind === "ok" ? "#i-check" : "#i-alert");
    svg.appendChild(use);
    var body = document.createElement("div");
    body.textContent = text;
    box.appendChild(svg);
    box.appendChild(body);
    feedback.appendChild(box);
    if (kind === "ok") clearTimer = setTimeout(function () { feedback.innerHTML = ""; }, 4000);
  }

  queue.addEventListener("click", function (event) {
    var button = event.target.closest("[data-complete]");
    if (!button || button.getAttribute("aria-busy") === "true") return;
    busy = true;
    var row = button.closest(".bar-line");
    row.querySelectorAll("[data-complete]").forEach(function (b) { b.setAttribute("aria-busy", "true"); });
    fetch(root.dataset.completeUrl, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify({ operation_key: button.dataset.op, line: Number(button.dataset.line),
                             cups: Number(button.dataset.cups), expected_done: Number(button.dataset.done) }),
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        notify(data.ok && !data.message ? "ok" : data.ok ? "info" : "error",
               data.ok ? (data.message || "Đã ghi pha xong " + data.applied + " ly.") : data.error);
      })
      .catch(function () {
        // Mất phản hồi: giữ nguyên nút và mã; bấm lại an toàn vì cùng mã không trừ kho lần hai.
        row.querySelectorAll("[data-complete]").forEach(function (b) { b.removeAttribute("aria-busy"); });
        notify("error", "Chưa chắc đã ghi được. Bấm lại cùng nút; hệ thống không trừ kho hai lần.");
      })
      .then(function () { busy = false; refresh(); });
  });

  markArrivals();
  setInterval(refresh, 2000);
  document.addEventListener("visibilitychange", refresh);
})();
