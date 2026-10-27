// Lịch làm tuần: mở hộp chi tiết ca, bước tăng giảm số người, hiện ô lý do khi khác gợi ý, ca mẫu và chọn nhanh ngày.
(function () {
  var root = document.querySelector(".wk");
  if (!root) return;

  function open(id, trigger) {
    var dialog = document.getElementById(id);
    if (!dialog || typeof dialog.showModal !== "function") return;
    if (id === "dlg-add" && trigger) prefillAdd(dialog, trigger.dataset);
    dialog.showModal();
  }

  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-open]");
    if (opener) { event.preventDefault(); open(opener.dataset.open, opener); return; }
    var closer = event.target.closest("[data-close]");
    if (closer) { closer.closest("dialog").close(); return; }
    // Bấm ra ngoài hộp (vùng nền mờ) thì đóng.
    if (event.target.tagName === "DIALOG") event.target.close();
    var confirmBtn = event.target.closest("[data-confirm]");
    if (confirmBtn && !window.confirm(confirmBtn.dataset.confirm)) event.preventDefault();
  });

  // Sau khi lưu trong hộp ca, trang tải lại kèm ?mo=<ca>: mở lại hộp đó và đưa thông báo vào trong hộp.
  var reopen = root.dataset.openShift;
  if (reopen && document.getElementById("ca-" + reopen)) {
    var dialog = document.getElementById("ca-" + reopen);
    var flash = dialog.querySelector("[data-flash]");
    document.querySelectorAll(".app-main > .notice").forEach(function (n) { flash.appendChild(n); });
    dialog.showModal();
    var url = new URL(location.href);
    url.searchParams.delete("mo");
    history.replaceState(null, "", url);
  }

  // Trên điện thoại dải các bước cuộn ngang: đưa bước đang làm vào giữa tầm nhìn.
  var steps = root.querySelector(".steps");
  var current = steps && steps.querySelector(".step.is-current");
  if (current && steps.scrollWidth > steps.clientWidth) steps.scrollLeft = current.offsetLeft - steps.offsetLeft - 14;

  // Bước tăng giảm và ô lý do.
  document.querySelectorAll(".needs-editor").forEach(function (form) {
    var reason = form.querySelector("[data-reason]");
    function check() {
      var differs = false;
      form.querySelectorAll("input[data-suggested]").forEach(function (input) {
        var changed = input.value !== "" && Number(input.value) !== Number(input.dataset.suggested);
        input.closest(".need-row").classList.toggle("is-changed", changed);
        differs = differs || changed;
      });
      if (reason) {
        reason.hidden = !differs && !reason.querySelector("input").value;
        reason.querySelector("input").required = differs;
      }
    }
    form.addEventListener("click", function (event) {
      var btn = event.target.closest("[data-step]");
      if (!btn) return;
      var input = btn.parentNode.querySelector("input");
      var value = Math.max(0, Math.min(20, (Number(input.value) || 0) + Number(btn.dataset.step)));
      input.value = value;
      check();
    });
    form.addEventListener("input", check);
    check();
  });

  // Hộp Thêm ca: ca mẫu, chọn nhanh ngày, điền sẵn khi bấm ô trống trong lưới.
  var add = document.getElementById("dlg-add");
  function setDays(test) {
    add.querySelectorAll("input[name=days]").forEach(function (box, i) { box.checked = test(box, i); });
  }
  function prefillAdd(dialog, data) {
    if (data.name) dialog.querySelector("[name=name]").value = data.name;
    if (data.start) dialog.querySelector("[name=start]").value = data.start;
    if (data.end) dialog.querySelector("[name=end]").value = data.end;
    if (data.day !== undefined) setDays(function (box, i) { return String(i) === data.day; });
  }
  if (add) {
    add.addEventListener("click", function (event) {
      var preset = event.target.closest("[data-preset]");
      if (preset) prefillAdd(add, { name: preset.dataset.name, start: preset.dataset.start, end: preset.dataset.end });
      var quick = event.target.closest("[data-days]");
      if (quick) {
        var mode = quick.dataset.days;
        setDays(function (box) {
          var weekend = box.dataset.weekend === "1";
          return mode === "all" || (mode === "weekend" ? weekend : !weekend);
        });
      }
    });
  }
})();
