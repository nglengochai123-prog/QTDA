// Màn hình tạo đơn: phiếu order là giỏ món, luôn ở trên; thực đơn ở dưới, mở từng món tại chỗ.
// Gửi đơn bằng mã nghiệp vụ; mất phản hồi thì gửi lại cùng mã, máy chủ không tạo trùng (NFR-04).
(function () {
  "use strict";

  var root = document.getElementById("order-screen");
  if (!root) return;
  var menu = JSON.parse(document.getElementById("menu-data").textContent);
  // Tồn có thể dùng theo nguyên liệu, để tính ngay số ly còn đáp ứng cho lựa chọn đang chọn (FR-01, AC-03).
  var stockLeft = JSON.parse(document.getElementById("stock-data").textContent);
  // Nháp theo từng tài khoản: máy dùng chung ở quầy thì người đăng nhập sau không gửi nhầm nháp của người trước.
  var DRAFT_KEY = "lam-order-draft:" + (document.body.dataset.user || "");
  try {
    var legacy = localStorage.getItem("lam-order-draft");  // nháp lưu trước khi tách theo tài khoản
    if (legacy !== null) {
      if (localStorage.getItem(DRAFT_KEY) === null) localStorage.setItem(DRAFT_KEY, legacy);
      localStorage.removeItem("lam-order-draft");
    }
  } catch (e) {}
  var vnd = new Intl.NumberFormat("vi-VN");
  var items = {};
  menu.forEach(function (group) { group.items.forEach(function (item) { items[item.id] = item; }); });

  var state = loadDraft() || { table: null, tableCode: "", lines: [], key: root.dataset.operationKey, pending: false };
  var sending = false;
  // Khi đang mở một món, nút cố định ở vùng ngón cái trở thành nút "Thêm" của món đó.
  var activeAdd = null;

  function money(n) { return vnd.format(n) + " đ"; }
  function csrf() {
    var m = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function newKey() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID().replace(/-/g, "");
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 12);
  }
  function saveDraft() { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(state)); } catch (e) {} }
  function loadDraft() {
    try {
      var s = JSON.parse(localStorage.getItem(DRAFT_KEY));
      if (s && Array.isArray(s.lines)) return s;
    } catch (e) {}
    return null;
  }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function icon(name) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "icon");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  // ---------- Số ly còn đáp ứng ----------
  function usageFor(item, sizeId, optionIds) {
    var usage = {};
    function addAll(map) { Object.keys(map || {}).forEach(function (k) { usage[k] = (usage[k] || 0) + map[k]; }); }
    var size = item.sizes.find(function (s) { return s.id === sizeId; });
    if (size) addAll(size.usage);
    item.optionGroups.forEach(function (g) {
      g.options.forEach(function (o) { if (optionIds.indexOf(o.id) >= 0) addAll(o.usage); });
    });
    return usage;
  }
  function inTicket() {
    var used = {};
    state.lines.forEach(function (line) {
      Object.keys(line.usage || {}).forEach(function (k) { used[k] = (used[k] || 0) + line.usage[k] * line.quantity; });
    });
    return used;
  }
  function cupsLeft(usage) {
    var keys = Object.keys(usage);
    if (!keys.length) return null;
    var used = inTicket();
    return Math.max(0, Math.min.apply(null, keys.map(function (k) {
      return Math.floor(((stockLeft[k] || 0) - (used[k] || 0) + 1e-9) / usage[k]);
    })));
  }

  // ---------- Bàn ----------
  var tableLabel = document.getElementById("ticket-table");
  root.querySelectorAll('input[name="table"]').forEach(function (input) {
    if (String(state.table) === input.value) input.checked = true;
    input.addEventListener("change", function () {
      if (state.pending) { input.checked = String(state.table) === input.value; return; }
      state.table = Number(input.value);
      state.tableCode = input.dataset.code;
      root.classList.remove("picking");
      saveDraft();
      render();
    });
  });

  var changeTable = document.getElementById("change-table");
  changeTable.addEventListener("click", function () { root.classList.toggle("picking"); });

  // ---------- Thực đơn ----------
  function sizeLeftText(size) {
    if (size.left === null || size.left === undefined) return "";
    return size.left > 0 ? "còn " + size.left : "hết";
  }

  function renderMeta() {
    root.querySelectorAll(".menu-item").forEach(function (li) {
      var item = items[li.dataset.item];
      var meta = li.querySelector("[data-meta]");
      var prices = item.sizes.map(function (s) { return s.name + " " + vnd.format(s.price / 1000) + "k"; }).join(" · ");
      var out = item.sizes.every(function (s) { return s.left === 0; });
      var lows = item.sizes.filter(function (s) { return s.left !== null && s.left > 0 && s.left <= 5; });
      meta.textContent = prices + (out ? " · hết nguyên liệu" : "");
      if (!out && lows.length) {
        var low = el("span", "low", " · còn " + lows[0].left + " ly " + lows[0].name);
        meta.appendChild(low);
      }
      li.classList.toggle("is-out", out);
    });
  }

  function openItem(li) {
    var item = items[li.dataset.item];
    var body = li.querySelector(".menu-item-body");
    var head = li.querySelector(".menu-item-head");
    var isOpen = !body.hidden;
    root.querySelectorAll(".menu-item-body").forEach(function (b) {
      b.hidden = true;
      b.previousElementSibling.setAttribute("aria-expanded", "false");
      b.innerHTML = "";
    });
    activeAdd = null;
    if (isOpen) { render(); return; }
    body.hidden = false;
    head.setAttribute("aria-expanded", "true");

    var pick = { size: (item.sizes.find(function (s) { return s.left !== 0; }) || item.sizes[0]).id,
                 options: [], quantity: 1, note: "" };

    var sizeRow = el("div", "choice-row");
    sizeRow.setAttribute("role", "radiogroup");
    sizeRow.setAttribute("aria-label", "Kích cỡ");
    item.sizes.forEach(function (size) {
      var label = el("label", "pick pick-size");
      var input = el("input");
      input.type = "radio"; input.name = "size-" + item.id; input.value = size.id;
      input.checked = size.id === pick.size;
      input.disabled = size.left === 0;
      input.addEventListener("change", function () { pick.size = size.id; update(); });
      var span = el("span");
      span.appendChild(el("strong", null, size.name));
      span.appendChild(el("span", "pick-sub", money(size.price) + (sizeLeftText(size) ? " · " + sizeLeftText(size) : "")));
      label.appendChild(input); label.appendChild(span);
      sizeRow.appendChild(label);
    });
    body.appendChild(sizeRow);

    item.optionGroups.forEach(function (group) {
      if (!group.options.length) return;
      var fs = el("fieldset", "option-group");
      fs.appendChild(el("legend", null, group.name + (group.required ? " (bắt buộc)" : "")));
      var row = el("div", "choice-row");
      group.options.forEach(function (option) {
        var label = el("label", "pick");
        var input = el("input");
        input.type = group.multiple ? "checkbox" : "radio";
        input.name = "opt-" + item.id + "-" + group.id;
        input.value = option.id;
        input.addEventListener("click", function () {
          // Nhóm chọn một: bấm lại lựa chọn đang chọn thì bỏ chọn (trừ khi bắt buộc).
          if (!group.multiple && input.dataset.was === "1" && !group.required) { input.checked = false; }
          row.querySelectorAll("input").forEach(function (i) { i.dataset.was = i.checked ? "1" : ""; });
          pick.options = Array.prototype.map.call(
            body.querySelectorAll(".option-group input:checked"), function (i) { return Number(i.value); });
          update();
        });
        label.appendChild(input);
        label.appendChild(el("span", null, option.name + (option.extra ? " +" + vnd.format(option.extra / 1000) + "k" : "")));
        row.appendChild(label);
      });
      fs.appendChild(row);
      body.appendChild(fs);
    });

    var noteField = el("div", "field");
    var noteId = "note-" + item.id;
    var noteLabel = el("label", null, "Ghi chú cho pha chế");
    noteLabel.setAttribute("for", noteId);
    var note = el("input", "input");
    note.id = noteId; note.maxLength = 120; note.placeholder = "Ví dụ: ít ngọt, mang về";
    note.addEventListener("input", function () { pick.note = note.value; });
    noteField.appendChild(noteLabel); noteField.appendChild(note);
    body.appendChild(noteField);

    var actions = el("div", "add-row");
    var stepper = el("div", "stepper");
    var minus = el("button", "btn btn-quiet stepper-btn"); minus.type = "button"; minus.appendChild(icon("minus"));
    minus.setAttribute("aria-label", "Bớt một ly");
    var qty = el("output", "stepper-value", "1");
    qty.setAttribute("aria-live", "polite");
    var plus = el("button", "btn btn-quiet stepper-btn"); plus.type = "button"; plus.appendChild(icon("plus"));
    plus.setAttribute("aria-label", "Thêm một ly");
    minus.addEventListener("click", function () { pick.quantity = Math.max(1, pick.quantity - 1); update(); });
    plus.addEventListener("click", function () { pick.quantity = Math.min(50, pick.quantity + 1); update(); });
    stepper.appendChild(minus); stepper.appendChild(qty); stepper.appendChild(plus);
    var add = el("button", "btn btn-primary add-btn"); add.type = "button";
    actions.appendChild(stepper); actions.appendChild(add);
    body.appendChild(actions);
    var hint = el("p", "add-hint");
    hint.setAttribute("aria-live", "polite");
    body.appendChild(hint);

    function unitPrice() {
      var size = item.sizes.find(function (s) { return s.id === pick.size; });
      var extra = 0;
      item.optionGroups.forEach(function (g) {
        g.options.forEach(function (o) { if (pick.options.indexOf(o.id) >= 0) extra += o.extra; });
      });
      return size.price + extra;
    }
    function missingRequired() {
      return item.optionGroups.filter(function (g) {
        return g.required && !g.options.some(function (o) { return pick.options.indexOf(o.id) >= 0; });
      });
    }
    function update() {
      qty.textContent = pick.quantity;
      var missing = missingRequired();
      var left = cupsLeft(usageFor(item, pick.size, pick.options));
      var tooMany = left !== null && pick.quantity > left;
      add.disabled = missing.length > 0 || state.pending || tooMany;
      if (left === null) {
        hint.textContent = "";
      } else if (left === 0) {
        hint.textContent = "Hết nguyên liệu cho lựa chọn này (đã tính các món trong phiếu).";
      } else {
        hint.textContent = "Còn đáp ứng " + left + " ly cho lựa chọn này (đã tính các món trong phiếu).";
      }
      hint.classList.toggle("low", left !== null && left <= 5);
      add.textContent = missing.length ? "Chọn " + missing[0].name
        : left === 0 ? "Hết nguyên liệu"
        : tooMany ? "Chỉ còn đáp ứng " + left + " ly"
        : "Thêm " + pick.quantity + " ly · " + money(unitPrice() * pick.quantity);
      activeAdd = { label: add.textContent, disabled: add.disabled, run: function () { add.click(); } };
      render();
    }
    add.addEventListener("click", function () {
      if (state.pending) return;
      var size = item.sizes.find(function (s) { return s.id === pick.size; });
      var optionNames = [];
      item.optionGroups.forEach(function (g) {
        g.options.forEach(function (o) { if (pick.options.indexOf(o.id) >= 0) optionNames.push(o.name); });
      });
      state.lines.push({ item: item.id, size: size.id, options: pick.options.slice().sort(),
                         quantity: pick.quantity, note: pick.note.trim(), name: item.name, sizeName: size.name,
                         optionText: optionNames.join(", "), unitPrice: unitPrice(),
                         usage: usageFor(item, size.id, pick.options) });
      saveDraft();
      openItem(li);
      render();
      setFeedback("");
    });
    update();
  }

  root.querySelectorAll(".menu-item-head").forEach(function (head) {
    head.addEventListener("click", function () { openItem(head.parentElement); });
  });

  // ---------- Phiếu ----------
  var linesEl = document.getElementById("ticket-lines");
  var emptyEl = document.getElementById("ticket-empty");
  var sendBtn = document.getElementById("send-order");

  function totals() {
    return state.lines.reduce(function (acc, l) {
      acc.cups += l.quantity; acc.money += l.unitPrice * l.quantity; return acc;
    }, { cups: 0, money: 0 });
  }

  function render() {
    tableLabel.textContent = state.table ? "Bàn " + state.tableCode : tableLabel.dataset.empty;
    tableLabel.classList.toggle("is-set", !!state.table);
    root.classList.toggle("has-table", !!state.table);
    changeTable.hidden = !state.table || state.pending;
    linesEl.innerHTML = "";
    state.lines.forEach(function (line, index) {
      var li = el("li", "ticket-line");
      li.appendChild(el("span", "ticket-qty", line.quantity + "×"));
      var main = el("span", "ticket-main");
      main.appendChild(el("span", "ticket-name", line.name + " " + line.sizeName));
      var detail = [line.optionText, line.note].filter(Boolean).join(" · ");
      if (detail) main.appendChild(el("span", "ticket-detail", detail));
      li.appendChild(main);
      li.appendChild(el("span", "ticket-price", money(line.unitPrice * line.quantity)));
      var remove = el("button", "ticket-remove");
      remove.type = "button";
      remove.setAttribute("aria-label", "Bỏ " + line.name + " " + line.sizeName);
      remove.appendChild(icon("x"));
      remove.disabled = state.pending;
      remove.addEventListener("click", function () {
        state.lines.splice(index, 1); saveDraft(); render();
      });
      li.appendChild(remove);
      linesEl.appendChild(li);
    });
    emptyEl.hidden = state.lines.length > 0;
    var t = totals();
    var label = sendBtn.querySelector("[data-label]");
    var sendIcon = sendBtn.querySelector("use");
    sendIcon.setAttribute("href", activeAdd && !sending && !state.pending ? "#i-plus" : "#i-send");
    if (activeAdd && !sending && !state.pending) {
      label.textContent = activeAdd.label;
      sendBtn.disabled = activeAdd.disabled;
      sendBtn.classList.add("is-add");
      root.classList.toggle("is-pending", state.pending);
      return;
    }
    sendBtn.classList.remove("is-add");
    if (sending) {
      label.textContent = "Đang gửi…";
    } else if (state.pending) {
      label.textContent = "Gửi lại đơn này";
    } else if (!state.table) {
      label.textContent = "Chọn bàn để gửi";
    } else if (!state.lines.length) {
      label.textContent = "Thêm món để gửi";
    } else {
      label.textContent = "Gửi pha chế · " + t.cups + " ly · " + money(t.money);
    }
    sendBtn.disabled = sending || !state.table || !state.lines.length;
    root.classList.toggle("is-pending", state.pending);
  }

  // ---------- Gửi đơn ----------
  var feedback = document.getElementById("order-feedback");
  function setFeedback(kind, title, items, extra) {
    feedback.innerHTML = "";
    if (!kind) return;
    var box = el("div", "notice notice-" + kind);
    box.setAttribute("role", kind === "ok" ? "status" : "alert");
    box.appendChild(icon(kind === "ok" ? "check" : kind === "warn" ? "offline" : "alert"));
    var text = el("div");
    text.appendChild(el("strong", null, title));
    if (items && items.length) {
      var ul = el("ul", "notice-list");
      items.forEach(function (t) { ul.appendChild(el("li", null, t)); });
      text.appendChild(ul);
    }
    if (extra) text.appendChild(el("p", "notice-extra", extra));
    box.appendChild(text);
    feedback.appendChild(box);
    feedback.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // Khách phải đổi món vì thiếu nguyên liệu: ghi trường hợp thiếu (BRU-26), mỗi nguyên liệu một lần mỗi ngày.
  function addSwitchButton(ingredientIds) {
    var box = feedback.querySelector(".notice");
    if (!box || !ingredientIds.length) return;
    var button = el("button", "btn btn-quiet switch-btn", "Khách đổi món vì thiếu nguyên liệu");
    button.type = "button";
    var key = newKey();
    button.addEventListener("click", function () {
      button.disabled = true;
      fetch(root.dataset.switchUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ operation_key: key, ingredients: ingredientIds }),
      }).then(function (r) { return r.json(); }).then(function (data) {
        button.textContent = data.ok ? "Đã ghi nhận khách đổi món" : (data.error || "Chưa ghi được");
      }).catch(function () { button.disabled = false; button.textContent = "Chưa ghi được, bấm lại"; });
    });
    box.querySelector("div").appendChild(button);
    // Quầy cho rằng còn hàng: đề nghị pha chế kiểm kê lại; kết quả có hiệu lực thì gửi lại đơn.
    var recount = el("button", "btn btn-quiet switch-btn", "Đề nghị pha chế kiểm kê lại");
    recount.type = "button";
    var recountKey = newKey();
    recount.addEventListener("click", function () {
      recount.disabled = true;
      fetch(root.dataset.recountUrl, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ operation_key: recountKey, ingredients: ingredientIds }),
      }).then(function (r) { return r.json(); }).then(function (data) {
        recount.textContent = data.ok ? "Đã báo pha chế kiểm kê lại" : (data.error || "Chưa gửi được");
      }).catch(function () { recount.disabled = false; recount.textContent = "Chưa gửi được, bấm lại"; });
    });
    box.querySelector("div").appendChild(recount);
  }

  function refreshAvailability() {
    fetch(root.dataset.availabilityUrl, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;
        if (data.available) stockLeft = data.available;
        Object.keys(items).forEach(function (id) {
          items[id].sizes.forEach(function (s) { if (s.id in data.left || String(s.id) in data.left) s.left = data.left[String(s.id)]; });
        });
        renderMeta();
      })
      .catch(function () {});
  }

  sendBtn.addEventListener("click", function () {
    if (activeAdd && !sending && !state.pending) { activeAdd.run(); return; }
    if (sending || !state.table || !state.lines.length) return;
    sending = true;
    state.pending = true; // Từ đây giữ nguyên phiếu và mã cho đến khi máy chủ trả lời chắc chắn.
    saveDraft();
    render();
    var payload = {
      operation_key: state.key,
      order: { table: state.table, note: "", lines: state.lines.map(function (l) {
        return { item: l.item, size: l.size, options: l.options, quantity: l.quantity, note: l.note };
      }) },
    };
    fetch(root.dataset.submitUrl, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(payload),
    }).then(function (r) {
      return r.json().then(function (data) { return { status: r.status, data: data }; });
    }).then(function (res) {
      sending = false;
      var data = res.data;
      if (data.ok) {
        setFeedback("ok", "Đã gửi pha chế đơn " + data.code + " · Bàn " + data.table,
          null, "Tổng " + money(data.total) + ". Đơn đã khóa; cần đổi món thì gửi yêu cầu điều chỉnh.");
        state = { table: null, tableCode: "", lines: [], key: newKey(), pending: false };
        root.querySelectorAll('input[name="table"]').forEach(function (i) { i.checked = false; });
        saveDraft();
        refreshAvailability();
      } else {
        // Máy chủ trả lời rõ là chưa nhận: mở khóa phiếu để sửa, dùng mã mới cho lần gửi sau.
        state.pending = false;
        state.key = newKey();
        saveDraft();
        if (data.shortages) {
          var rows = (data.lines || []).filter(function (l) { return l.left !== null && l.left < l.quantity; })
            .map(function (l) { return l.name + ": gọi " + l.quantity + " ly, còn đáp ứng " + l.left + " ly"; });
          rows = rows.concat(data.shortages.map(function (s) {
            return s.ingredient + ": cần " + s.needed + " " + s.unit + ", còn " + s.available + " " + s.unit;
          }));
          // Bán thành phẩm (cốt, nước đường...) hết mẻ: làm thêm mẻ là đủ, không cần đổi món.
          var semi = data.shortages.filter(function (s) { return s.semi; }).map(function (s) { return s.ingredient; });
          setFeedback("error", data.error, rows, semi.length
            ? "Báo pha chế làm thêm mẻ " + semi.join(", ") + " (Kho › Làm bán thành phẩm) rồi gửi lại, hoặc giảm số ly, chọn món khác."
            : "Giảm số ly, chọn món khác, hoặc báo pha chế kiểm kê nhanh.");
          addSwitchButton(data.shortages.map(function (s) { return s.ingredient_id; }));
          refreshAvailability();
        } else {
          setFeedback("error", data.error || "Chưa gửi được đơn.");
        }
      }
      render();
    }).catch(function () {
      sending = false;
      saveDraft();
      setFeedback("warn", "Chưa chắc đơn đã tới máy chủ.",
        ["Mã nghiệp vụ: " + shortKey(state.key)],
        "Bấm \"Gửi lại đơn này\". Gửi lại an toàn: nếu đơn đã được nhận, hệ thống trả đúng đơn đó. Nếu phải bán bằng phiếu dự phòng, ghi mã này lên phiếu.");
      render();
    });
  });

  function shortKey(k) { return (k || "").slice(0, 8).toUpperCase(); }

  if (state.pending) {
    setFeedback("warn", "Đơn trước chưa có xác nhận từ máy chủ.", ["Mã nghiệp vụ: " + shortKey(state.key)],
      "Bấm \"Gửi lại đơn này\" để kiểm tra. Hệ thống không tạo đơn trùng. Nếu phải bán bằng phiếu dự phòng, ghi mã này lên phiếu.");
  }
  renderMeta();
  render();
})();
