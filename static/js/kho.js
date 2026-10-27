// Các màn Kho: Kiểm kê báo lệch ngay khi gõ; Đặt hàng tự chọn nhà cung cấp chính và hiện đơn vị của nguyên liệu.
(function () {
  "use strict";

  var fmt = function (n) {
    return n.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
  };
  // Đọc số như máy chủ: số lượng "1.866" là 1866 và "1,5" là 1,5; số tiền bỏ mọi dấu phân cách hàng nghìn.
  var qtyNum = function (v) {
    v = (v || "").trim().replace(/\s/g, "");
    if (v === "") return NaN;
    if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(v)) v = v.replace(/\./g, "");
    return Number(v.replace(",", "."));
  };
  var moneyNum = function (v) {
    v = (v || "").replace(/đ|\s/g, "");
    if (v === "") return NaN;
    if (/^\d{1,3}([.,]\d{3})+$/.test(v)) return Number(v.replace(/[.,]/g, ""));
    return Math.round(Number(v.replace(",", ".")));
  };

  document.querySelectorAll(".count-form").forEach(function (form) {
    var input = form.querySelector("[name=counted]");
    var reason = form.querySelector("[name=reason]");
    var box = form.querySelector(".count-reason");
    var out = form.querySelector(".count-diff");
    var physical = parseFloat(form.dataset.physical) || 0;
    var limit = parseFloat(form.dataset.threshold) || 0;
    var unit = form.dataset.unit || "";

    var update = function () {
      var raw = input.value.trim();
      var value = qtyNum(raw);
      var over = false;
      out.className = "count-diff";
      if (raw === "") {
        out.textContent = "";
      } else if (!isFinite(value) || value < 0) {
        out.textContent = "Số đếm chưa hợp lệ";
        out.classList.add("is-bad");
      } else {
        var diff = value - physical;
        var pct = physical > 0 ? Math.abs(diff) / physical * 100 : (diff ? 100 : 0);
        over = pct > limit;
        if (Math.abs(diff) < 0.005) {
          out.textContent = "Khớp sổ";
          out.classList.add("is-ok");
        } else {
          out.textContent = "Lệch " + (diff > 0 ? "+" : "−") + fmt(Math.abs(diff)) + " " + unit + " (" + fmt(pct) + "%)"
            + (over ? " · cần lý do để Chủ quán xác nhận" : " · tồn được điều chỉnh ngay");
          out.classList.add(over ? "is-over" : "is-ok");
        }
      }
      box.hidden = !over && !reason.value;
      reason.required = over;
    };

    box.hidden = !reason.value;
    input.addEventListener("input", update);
    update();
  });

  // Đặt hàng: chọn nguyên liệu thì điền sẵn nhà cung cấp chính (nếu chưa chọn) và hiện đơn vị tính cạnh ô số lượng.
  document.querySelectorAll(".po-form").forEach(function (form) {
    var ingredient = form.querySelector("[data-po-ingredient]");
    var supplier = form.querySelector("[data-po-supplier]");
    var unit = form.querySelector("[data-po-unit]");
    var touched = false;
    supplier.addEventListener("change", function () { touched = true; });
    var sync = function () {
      var opt = ingredient.selectedOptions[0];
      unit.textContent = opt && opt.dataset.unit ? opt.dataset.unit : "";
      if (!touched && opt && opt.dataset.supplier) supplier.value = opt.dataset.supplier;
    };
    ingredient.addEventListener("change", sync);
    sync();
  });

  // Ô số tiền: nhóm hàng nghìn bằng dấu chấm khi gõ (máy chủ nhận cả số có hay không có dấu chấm).
  document.querySelectorAll("input[data-money]").forEach(function (input) {
    var tidy = function () {
      if (input.value.indexOf(",") >= 0) return;  // có phần lẻ (đơn giá theo gram): để nguyên
      var digits = input.value.replace(/\D/g, "");
      input.value = digits ? Number(digits).toLocaleString("vi-VN") : "";
    };
    input.addEventListener("input", function () {
      if (input.selectionStart === input.value.length) tidy();
    });
    input.addEventListener("blur", tidy);
  });

  // Phiếu nhập: hiện từng dòng khi cần, gợi ý hàng đang chờ giao của nhà cung cấp, tự tính thành tiền và tổng phiếu.
  document.querySelectorAll(".rc-form").forEach(function (form) {
    var lines = Array.prototype.slice.call(form.querySelectorAll("[data-rc-line]"));
    var supplier = form.querySelector("[data-rc-supplier]");
    var addBtn = form.querySelector("[data-rc-add]");
    var posBox = form.querySelector("[data-rc-pos]");
    var posList = form.querySelector("[data-rc-pos-list]");
    var money = function (n) { return Math.round(n).toLocaleString("vi-VN") + " đ"; };
    var used = function (line) {
      return Array.prototype.some.call(line.querySelectorAll("input, select"), function (el) { return el.value; });
    };
    var field = function (line, sel) { return line.querySelector(sel); };

    var syncLine = function (line) {
      var ing = field(line, "[data-rc-ingredient]");
      var opt = ing.selectedOptions[0];
      var unit = opt && opt.dataset.unit ? opt.dataset.unit : "";
      field(line, "[data-rc-unit]").textContent = unit;
      field(line, "[data-rc-price-unit]").textContent = unit ? "đ/" + unit : "đ";
      // Chỉ cho chọn lần đặt của đúng nguyên liệu (và nhà cung cấp, nếu đã chọn).
      var po = field(line, "[data-rc-po]");
      Array.prototype.forEach.call(po.options, function (o) {
        if (!o.value) return;
        var ok = o.dataset.ingredient === ing.value && (!supplier.value || o.dataset.supplier === supplier.value);
        o.hidden = !ok;
        o.disabled = !ok;
      });
      if (po.selectedOptions[0] && po.selectedOptions[0].disabled) po.value = "";
      var qty = qtyNum(field(line, "[data-rc-qty]").value);
      var price = moneyNum(field(line, "[data-rc-price]").value);
      // Đơn giá lệch quá 3 lần so với lần nhập trước thường là nhập theo kg hay hộp thay vì đơn vị tính.
      var hint = field(line, "[data-rc-hint]");
      var last = opt && opt.dataset.lastPrice ? Number(opt.dataset.lastPrice) : null;
      var typed = field(line, "[data-rc-price]").value;
      if (hint) {
        var off = last > 0 && typed && price > 0 && (price > last * 3 || price * 3 < last);
        hint.hidden = last === null;
        hint.classList.toggle("text-warn", !!off);
        hint.textContent = last === null ? "" : (off ? "Khác nhiều so với lần nhập trước (" : "Lần nhập trước ")
          + Math.round(last).toLocaleString("vi-VN") + " đ/" + unit + (off ? "); kiểm tra đơn vị tính." : ".");
      }
      var out = field(line, "[data-rc-sum]");
      out.textContent = qty > 0 && price >= 0 && field(line, "[data-rc-price]").value ? money(qty * price) : "";
      return qty > 0 && price > 0 ? qty * price : 0;
    };
    var total = function () {
      var sum = 0;
      lines.forEach(function (line) { sum += syncLine(line); });
      form.querySelectorAll("[data-rc-total]").forEach(function (el) { el.textContent = money(sum); });
      var hidden = lines.filter(function (l) { return l.hidden; });
      addBtn.hidden = hidden.length === 0;
    };
    var show = function (line) { line.hidden = false; };
    var nextFree = function () {
      return lines.filter(function (l) { return !l.hidden && !field(l, "[data-rc-ingredient]").value; })[0]
        || lines.filter(function (l) { return l.hidden; })[0];
    };

    lines.forEach(function (line, k) {
      line.hidden = k > 0 && !used(line);
      line.addEventListener("input", total);
      line.addEventListener("change", function (e) {
        if (e.target.matches("[data-rc-po]") && e.target.value) {
          var o = e.target.selectedOptions[0];
          var qty = field(line, "[data-rc-qty]");
          if (!qty.value && o.dataset.remaining) qty.value = fmt(Number(o.dataset.remaining));
        }
        total();
        if (e.target.matches("[data-rc-po], [data-rc-ingredient]")) renderPos();
      });
      field(line, "[data-rc-remove]").addEventListener("click", function () {
        line.querySelectorAll("input, select").forEach(function (el) { el.value = ""; });
        if (lines.filter(function (l) { return !l.hidden; }).length > 1) line.hidden = true;
        form.dispatchEvent(new Event("input"));
        total();
        renderPos();
      });
    });
    addBtn.addEventListener("click", function () {
      var line = lines.filter(function (l) { return l.hidden; })[0];
      if (line) { show(line); field(line, "[data-rc-ingredient]").focus(); }
      total();
    });

    // Hàng đang chờ giao của nhà cung cấp: mỗi lần đặt một nút, bấm thì điền vào dòng trống tiếp theo.
    var po0 = lines[0].querySelector("[data-rc-po]");
    var renderPos = function () {
      posList.innerHTML = "";
      var opts = Array.prototype.filter.call(po0.options, function (o) {
        return o.value && o.dataset.supplier === supplier.value
          && !lines.some(function (l) { return field(l, "[data-rc-po]").value === o.value; });
      });
      opts.forEach(function (o) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "chip-btn";
        b.textContent = "+ " + o.textContent;
        b.addEventListener("click", function () {
          var line = nextFree();
          if (!line) return;
          show(line);
          field(line, "[data-rc-ingredient]").value = o.dataset.ingredient;
          syncLine(line);
          field(line, "[data-rc-po]").value = o.value;
          field(line, "[data-rc-qty]").value = fmt(Number(o.dataset.remaining));
          form.dispatchEvent(new Event("input"));
          total();
          renderPos();
          field(line, "[data-rc-price]").focus();
        });
        posList.appendChild(b);
      });
      posBox.hidden = opts.length === 0;
    };
    supplier.addEventListener("change", function () { renderPos(); total(); });

    // Trả ngay thì hỏi nguồn tiền, trả sau thì hỏi hạn trả.
    var now = form.querySelector("[data-rc-now]");
    var later = form.querySelector("[data-rc-later]");
    var pay = function () {
      var picked = form.querySelector("[data-rc-paytype]:checked");
      now.hidden = !picked || picked.value !== "tra_ngay";
      later.hidden = !picked || picked.value !== "tra_sau";
    };
    form.querySelectorAll("[data-rc-paytype]").forEach(function (r) { r.addEventListener("change", pay); });
    pay();
    renderPos();
    total();
  });

  // Hao hụt: hiện đơn vị và tồn trên sổ của nguyên liệu đang chọn.
  document.querySelectorAll(".waste-form").forEach(function (form) {
    var ing = form.querySelector("[data-w-ingredient]");
    var unit = form.querySelector("[data-w-unit]");
    var stock = form.querySelector("[data-w-stock]");
    var sync = function () {
      var opt = ing.selectedOptions[0];
      var u = opt && opt.value ? opt.dataset.unit : "";
      unit.textContent = u;
      stock.textContent = opt && opt.value ? "Trên sổ còn " + opt.dataset.stock + " " + u : "";
    };
    ing.addEventListener("change", sync);
    sync();
  });
})();
