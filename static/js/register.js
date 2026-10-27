// Đăng ký ca: chọn nhanh cả tuần, tổng số ca và giờ đang chọn, báo hai ca trùng giờ, báo có thay đổi chưa gửi.
(function () {
  var form = document.querySelector(".reg-form");
  if (!form) return;
  var rows = Array.prototype.slice.call(form.querySelectorAll("[data-shift]"));

  function picked(row) {
    var input = row.querySelector("input:checked");
    return input ? input.value : "";
  }
  function pick(row, value) {
    var input = row.querySelector('input[value="' + value + '"]');
    if (input && !input.checked) {
      input.checked = true;
      input.dispatchEvent(new Event("change", { bubbles: true }));  // để nháp trên thiết bị ghi lại
    }
  }
  function minutes(t) { var p = t.split(":"); return Number(p[0]) * 60 + Number(p[1]); }
  function hoursText(h) { return (Math.round(h * 10) / 10).toString().replace(".", ","); }

  function refresh() {
    var count = 0, hours = 0, dirty = false;
    rows.forEach(function (row) {
      var value = picked(row);
      row.classList.toggle("is-picked", value !== "");
      if (value) { count += 1; hours += Number(row.dataset.hours) || 0; }
      if (value !== row.dataset.initial) dirty = true;
    });
    form.querySelector("[data-sum]").textContent = count + " ca · " + hoursText(hours) + " giờ";
    form.querySelector("[data-dirty]").hidden = !dirty;
    // Hai ca cùng ngày trùng giờ: Chủ quán chỉ xếp được một ca.
    form.querySelectorAll(".reg-day").forEach(function (day) {
      var chosen = Array.prototype.filter.call(day.querySelectorAll("[data-shift]"), function (r) { return picked(r); });
      var clash = [];
      for (var i = 0; i < chosen.length; i++) {
        for (var j = i + 1; j < chosen.length; j++) {
          var a = chosen[i].dataset, b = chosen[j].dataset;
          if (minutes(a.start) < minutes(b.end) && minutes(b.start) < minutes(a.end)) clash.push(a.name + " và " + b.name);
        }
      }
      var warn = day.querySelector("[data-overlap]");
      warn.hidden = !clash.length;
      warn.textContent = clash.length ? clash.join(", ") + " trùng giờ nhau; Chủ quán chỉ xếp bạn vào một trong hai ca." : "";
    });
  }

  form.addEventListener("change", refresh);
  form.addEventListener("click", function (event) {
    var byName = event.target.closest("[data-pick-name]");
    if (byName) {
      rows.forEach(function (row) {
        if (row.dataset.name === byName.dataset.pickName && !picked(row)) pick(row, row.dataset.best);
      });
      refresh();
    }
    if (event.target.closest("[data-pick-none]")) {
      rows.forEach(function (row) { pick(row, ""); });
      refresh();
    }
  });
  // Nháp trên thiết bị có thể được khôi phục sau khi trang tải; tính lại sau đó.
  refresh();
  window.addEventListener("load", refresh);
})();
