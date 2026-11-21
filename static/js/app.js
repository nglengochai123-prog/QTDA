// Hành vi chung của khung ứng dụng. Không phụ thuộc thư viện ngoài.
(function () {
  "use strict";

  // --- Hết phiên đăng nhập khi trang đang mở: máy chủ trả 401 kèm đường đăng nhập; hiện một dải báo có nút ---
  if (window.fetch) {
    var plainFetch = window.fetch;
    var expiredShown = false;
    window.fetch = function () {
      return plainFetch.apply(this, arguments).then(function (r) {
        if (r.status === 401 && !expiredShown) {
          r.clone().json().then(function (d) {
            if (!d || !d.login || expiredShown) return;
            expiredShown = true;
            var bar = document.createElement("div");
            bar.className = "notice notice-warn session-expired";
            bar.setAttribute("role", "alert");
            var text = document.createElement("div");
            text.textContent = "Phiên đăng nhập đã hết hạn. Nội dung đang soạn trên máy này vẫn còn. ";
            var link = document.createElement("a");
            link.href = d.login;
            link.textContent = "Đăng nhập lại";
            text.appendChild(link);
            bar.appendChild(text);
            var main = document.querySelector("main") || document.body;
            main.insertBefore(bar, main.firstChild);
          }).catch(function () {});
        }
        return r;
      });
    };
  }

  // --- Service worker (cài lên màn hình chính) ---
  if ("serviceWorker" in navigator && document.body.dataset.swUrl) {
    navigator.serviceWorker.register(document.body.dataset.swUrl, { scope: "/" }).catch(function () {});
  }

  // --- Máy dùng chung: thông báo đẩy của thiết bị đi theo người đang đăng nhập, không theo người bật trước ---
  var me = document.body.dataset.user, pushUrl = document.body.dataset.pushUrl;
  if (me && pushUrl && "serviceWorker" in navigator && window.Notification && Notification.permission === "granted") {
    var pushOwner = null;
    try { pushOwner = localStorage.getItem("lam-push-user"); } catch (e) {}
    if (pushOwner !== me) {
      navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); }).then(function (sub) {
        if (!sub) return;
        var token = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return fetch(pushUrl, { method: "POST", credentials: "same-origin", body: JSON.stringify(sub.toJSON()),
                                headers: { "Content-Type": "application/json", "X-CSRFToken": token ? decodeURIComponent(token[1]) : "" } })
          .then(function (r) { if (r.ok) { try { localStorage.setItem("lam-push-user", me); } catch (e) {} } });
      }).catch(function () {});
    }
  }
  var logout = document.querySelector("form[data-logout]");
  if (logout && me && document.body.dataset.pushOffUrl && "serviceWorker" in navigator && navigator.sendBeacon) {
    logout.addEventListener("submit", function (event) {
      if (logout.dataset.sent) return;
      event.preventDefault();
      logout.dataset.sent = "1";
      var left = false;
      var done = function () {
        if (left) return;
        left = true;
        try { localStorage.removeItem("lam-push-user"); } catch (e) {}
        logout.submit();
      };
      var timer = setTimeout(done, 1500);  // không chờ lâu nếu trình duyệt chậm trả lời
      navigator.serviceWorker.getRegistration().then(function (reg) { return reg && reg.pushManager.getSubscription(); })
        .then(function (sub) {
          if (sub) {
            var data = new FormData();
            data.append("endpoint", sub.endpoint);
            data.append("csrfmiddlewaretoken", logout.querySelector("[name=csrfmiddlewaretoken]").value);
            navigator.sendBeacon(document.body.dataset.pushOffUrl, data);
          }
        }).catch(function () {}).then(function () { clearTimeout(timer); done(); });
    });
  }

  // --- Thẻ trang cuộn ngang trên điện thoại: đưa thẻ đang mở vào tầm nhìn ---
  var subTabs = document.querySelector(".sub-tabs");
  var currentTab = subTabs && subTabs.querySelector('[aria-current="page"]');
  if (currentTab && subTabs.scrollWidth > subTabs.clientWidth) {
    subTabs.scrollLeft = currentTab.offsetLeft - (subTabs.clientWidth - currentTab.offsetWidth) / 2;
  }

  // --- Thanh trên: đưa phân hệ đang mở vào tầm nhìn khi màn hình hẹp ---
  var topTabs = document.querySelector(".top-tabs");
  var currentGroup = topTabs && topTabs.querySelector('[aria-current="true"]');
  if (currentGroup && topTabs.scrollWidth > topTabs.clientWidth) {
    topTabs.scrollLeft = currentGroup.offsetLeft - (topTabs.clientWidth - currentGroup.offsetWidth) / 2;
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

  // --- Thu ngân: báo khi các bàn thay đổi; không tự tải lại để nút Thu tiền không đổi chỗ dưới tay ---
  var changed = document.getElementById("cashier-changed");
  function pollCashier() {
    if (!changed || !changed.hidden || document.hidden || offline) return;
    fetch(changed.dataset.url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { if (data && data.sig && data.sig !== changed.dataset.sig) changed.hidden = false; })
      .catch(function () {});
  }
  if (changed) setInterval(pollCashier, 8000);

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
          (data.cups || data.count) + " ly đã pha xong · Bàn " + data.tables.join(", ");
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

  // --- Trang tự làm mới phần thân (Tổng quan ca); hết phiên đăng nhập thì giữ nguyên nội dung cũ ---
  document.querySelectorAll("[data-live-url]").forEach(function (box) {
    var every = (parseInt(box.dataset.liveEvery, 10) || 15) * 1000;
    function refresh() {
      if (document.hidden || offline) return;
      fetch(box.dataset.liveUrl, { credentials: "same-origin", cache: "no-store" })
        .then(function (r) { return r.ok && !r.redirected ? r.text() : null; })
        .then(function (html) { if (html !== null) box.innerHTML = html; })
        .catch(function () {});
    }
    setInterval(refresh, every);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
  });

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

  // --- Lưu nháp biểu mẫu trên thiết bị (NFR-16) ---
  // Biểu mẫu có data-draft được lưu nháp khi gõ, kể cả mã nghiệp vụ, nên gửi lại sau mất mạng
  // vẫn là cùng một yêu cầu và máy chủ không ghi trùng. Nháp được xóa khi trang báo đã lưu thành công.
  var savedOk = document.querySelector(".notice-ok");
  document.querySelectorAll("form[data-draft]").forEach(function (form) {
    var key = "nhap:" + (document.body.dataset.user || "") + ":" + location.pathname + ":" + form.dataset.draft;
    var fields = function () {
      return Array.prototype.filter.call(form.elements, function (el) {
        return el.name && el.type !== "file" && el.type !== "submit" && el.name !== "csrfmiddlewaretoken";
      });
    };
    var stored = null;
    try { stored = JSON.parse(localStorage.getItem(key) || "null"); } catch (e) { stored = null; }
    var stale = stored && stored.sent && (Date.now() - (stored.at || 0) > 30 * 60 * 1000);
    if (stored && stored.sent && (savedOk || stale)) {
      try { localStorage.removeItem(key); } catch (e) { /* bộ nhớ thiết bị không dùng được */ }
    } else if (stored && stored.values) {
      fields().forEach(function (el) {
        if (!(el.name in stored.values)) return;
        var v = stored.values[el.name];
        if (el.type === "checkbox" || el.type === "radio") el.checked = Array.isArray(v) ? v.indexOf(el.value) >= 0 : v === el.value;
        else if (el.multiple) Array.prototype.forEach.call(el.options, function (o) { o.selected = (v || []).indexOf(o.value) >= 0; });
        else el.value = v;
      });
      var note = document.createElement("p");
      note.className = "hint";
      note.textContent = stored.sent ? "Đã khôi phục nội dung vừa gửi nhưng chưa chắc máy chủ đã nhận; kiểm tra rồi gửi lại (không bị ghi trùng)."
                                     : "Đã khôi phục nội dung đang nhập dở trên thiết bị này.";
      form.insertBefore(note, form.firstChild);
    }
    var save = function (sent) {
      var values = {};
      fields().forEach(function (el) {
        if (el.type === "checkbox" || el.type === "radio") {
          if (!el.checked) return;
          values[el.name] = (values[el.name] || []).concat([el.value]);
        } else if (el.multiple) {
          values[el.name] = Array.prototype.filter.call(el.options, function (o) { return o.selected; }).map(function (o) { return o.value; });
        } else values[el.name] = el.value;
      });
      try { localStorage.setItem(key, JSON.stringify({ values: values, sent: !!sent, at: Date.now() })); } catch (e) { /* bỏ qua */ }
    };
    form.addEventListener("input", function () { save(false); });
    form.addEventListener("change", function () { save(false); });
    form.addEventListener("submit", function () { save(true); });
  });

  // --- Không ghi thanh toán, phê duyệt, kết quả xem xét khi mất kết nối (NFR-16) ---
  document.querySelectorAll("form[data-online-only]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (offline || navigator.onLine === false) {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.alert("Đang mất kết nối. Thao tác này chỉ ghi khi có mạng; chờ có mạng rồi bấm lại.");
      }
    }, true);
  });

  // --- Hỏi lại trước thao tác không hoàn tác được (hủy lô) ---
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm)) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    }, true);
  });

  // --- Thu chuyển khoản: nhắc ngay tại chỗ nếu chưa đánh dấu đã thấy tiền về, giữ nguyên lựa chọn của thu ngân ---
  document.querySelectorAll("form").forEach(function (form) {
    var box = form.querySelector('input[name="transfer_confirmed"]');
    if (!box || !form.querySelector('input[name="method"][value="chuyen_khoan"]')) return;
    var hint = document.createElement("p");
    hint.className = "transfer-hint";
    hint.hidden = true;
    hint.textContent = "Đánh dấu ô này khi đã thấy tiền về tài khoản quán.";
    box.closest("label").insertAdjacentElement("afterend", hint);
    box.addEventListener("change", function () { hint.hidden = true; });
    form.addEventListener("change", function (event) { if (event.target.name === "method") hint.hidden = true; });
    form.addEventListener("submit", function (event) {
      var transfer = form.querySelector('input[name="method"][value="chuyen_khoan"]');
      if (transfer && transfer.checked && !box.checked) {
        event.preventDefault();
        event.stopImmediatePropagation();
        hint.hidden = false;
        box.focus();
      }
    }, true);
  });

  // --- Ô chọn lô chỉ hiện lô của nguyên liệu đang chọn (ghi hao hụt) ---
  document.querySelectorAll("select[data-lots-for]").forEach(function (lotSelect) {
    var ingredient = document.getElementById(lotSelect.dataset.lotsFor);
    if (!ingredient) return;
    function sync() {
      Array.prototype.forEach.call(lotSelect.options, function (opt) {
        if (!opt.value) return;
        opt.hidden = opt.dataset.ingredient !== ingredient.value;
        if (opt.hidden && opt.selected) lotSelect.value = "";
      });
    }
    ingredient.addEventListener("change", sync);
    sync();
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
  // --- Ô chọn tệp: nút và tên tệp bằng tiếng Việt thay cho "Choose File / No file chosen" của trình duyệt ---
  function enhanceFile(input) {
    if (input.getAttribute("data-pick")) return;
    input.setAttribute("data-pick", "1");
    var isImage = /image/.test(input.getAttribute("accept") || "");
    var empty = isImage ? "Chưa chọn ảnh" : "Chưa chọn tệp";
    var box = document.createElement("span");
    box.className = "file-pick";
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-quiet btn-sm";
    btn.textContent = isImage ? "Chọn ảnh" : "Chọn tệp";
    var name = document.createElement("span");
    name.className = "file-pick-name";
    name.textContent = empty;
    input.parentNode.insertBefore(box, input);
    box.appendChild(input);
    box.appendChild(btn);
    box.appendChild(name);
    input.classList.add("file-pick-input");
    input.tabIndex = -1;
    btn.addEventListener("click", function (e) { e.preventDefault(); input.click(); });
    function show() {
      var n = input.files ? input.files.length : 0;
      name.textContent = n > 1 ? n + " tệp" : n === 1 ? input.files[0].name : empty;
      box.classList.toggle("has-file", n > 0);
      box.classList.remove("is-invalid");
      // Câu nhắc bằng tiếng Việt thay cho câu mặc định của trình duyệt khi ô bắt buộc còn trống.
      if (input.required) input.setCustomValidity(n ? "" : (isImage ? "Chọn ảnh trước khi lưu." : "Chọn tệp trước khi lưu."));
    }
    input.addEventListener("invalid", function () {
      box.classList.add("is-invalid");
      name.textContent = isImage ? "Cần chọn ảnh trước khi lưu" : "Cần chọn tệp trước khi lưu";
    });
    show();
    input.addEventListener("change", show);
    if (input.form) input.form.addEventListener("reset", function () { setTimeout(show, 0); });
  }
  Array.prototype.forEach.call(document.querySelectorAll('input[type="file"]'), enhanceFile);

  // Câu nhắc khi ô chưa hợp lệ bằng tiếng Việt, không phụ thuộc ngôn ngữ của trình duyệt. Ô nào đã có câu nhắc riêng
  // (ví dụ chọn ảnh) thì giữ nguyên.
  function viMessage(el) {
    var v = el.validity;
    if (v.valueMissing) {
      if (el.tagName === "SELECT") return "Chọn một mục trong danh sách.";
      if (el.type === "checkbox") return "Đánh dấu ô này để tiếp tục.";
      if (el.type === "radio") return "Chọn một lựa chọn.";
      return "Điền ô này trước khi lưu.";
    }
    if (v.badInput) return el.type === "number" ? "Nhập một số." : "Giá trị chưa đúng.";
    if (v.rangeUnderflow) return "Nhập số từ " + el.min + " trở lên.";
    if (v.rangeOverflow) return "Nhập số không quá " + el.max + ".";
    if (v.stepMismatch) return "Số này không hợp lệ, kiểm tra lại phần lẻ.";
    if (v.tooShort) return "Nhập ít nhất " + el.minLength + " ký tự.";
    if (v.typeMismatch) return el.type === "email" ? "Nhập đúng địa chỉ email." : "Giá trị chưa đúng định dạng.";
    if (v.patternMismatch) return el.title || "Giá trị chưa đúng định dạng.";
    return "";
  }
  document.addEventListener("invalid", function (e) {
    var el = e.target;
    if (!el.validity || (el.validity.customError && !el.dataset.viMsg)) return;
    el.setCustomValidity("");
    var text = viMessage(el);
    if (text) { el.setCustomValidity(text); el.dataset.viMsg = "1"; }
  }, true);
  function clearViMessage(e) {
    var el = e.target;
    if (el && el.dataset && el.dataset.viMsg) { el.setCustomValidity(""); delete el.dataset.viMsg; }
  }
  document.addEventListener("input", clearViMessage, true);
  document.addEventListener("change", clearViMessage, true);

  // Nhóm tùy chọn chỉ chọn một (Đá, Đường) trên phiếu nhập bù: chọn mục mới thì bỏ mục cũ cùng nhóm, cùng dòng.
  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t.matches || !t.matches("input[type=checkbox][data-single]") || !t.checked) return;
    var row = t.closest("fieldset") || t.form;
    if (!row) return;
    Array.prototype.forEach.call(row.querySelectorAll('input[data-single="' + t.dataset.single + '"]'), function (o) {
      if (o !== t) o.checked = false;
    });
  });
})();
