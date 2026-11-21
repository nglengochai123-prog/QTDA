// Chuông thông báo trên thanh trên: số chưa đọc (hỏi lại mỗi 30 giây, chỉ một truy vấn đếm), bảng việc đang chờ và
// thông báo gần nhất (chỉ tính khi mở bảng), đánh dấu đã đọc từng cái (khi mở) hoặc tất cả.
// Mọi nội dung chèn bằng textContent.
(function () {
  const box = document.querySelector("[data-notif]");
  if (!box) return;
  const badge = box.querySelector("[data-notif-badge]");
  const live = box.querySelector("[data-notif-live]");
  const body = box.querySelector("[data-notif-body]");
  const readAll = box.querySelector("[data-notif-readall]");
  const summary = box.querySelector("summary");
  const ICONS = { mon_san_sang: "ready", phe_duyet: "approve", kho: "stock", canh_bao: "alert", lich: "schedule", ca: "shift" };
  let lastUnread = null;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function icon(name) {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(ns, "use");
    use.setAttribute("href", "#i-" + name);
    svg.appendChild(use);
    return svg;
  }
  function setUnread(n) {
    badge.hidden = !n;
    badge.textContent = n > 99 ? "99+" : String(n);
    summary.setAttribute("aria-label", "Thông báo" + (n ? ", " + n + " chưa đọc" : ""));
    readAll.disabled = !n;
    // Báo cho trình đọc màn hình khi có thông báo mới (không đọc lại lúc mới tải trang).
    if (lastUnread !== null && n > lastUnread) live.textContent = "Có " + (n - lastUnread) + " thông báo mới";
    lastUnread = n;
  }
  function render(data) {
    body.textContent = "";
    if (data.waiting && data.waiting.length) {
      body.appendChild(el("p", "notif-section", "Việc chờ bạn"));
      data.waiting.forEach((t) => {
        const a = el("a", "notif-wait" + (t.urgent ? " is-urgent" : ""));
        a.href = t.url;
        a.appendChild(el("span", null, t.label));
        if (t.badge) a.appendChild(el("b", null, String(t.count)));
        body.appendChild(a);
      });
      body.appendChild(el("p", "notif-section", "Thông báo"));
    }
    if (!data.items.length) {
      body.appendChild(el("p", "notif-empty", "Chưa có thông báo nào."));
    } else {
      const ul = el("ul", "notif-list");
      data.items.forEach((n) => {
        const li = el("li");
        const a = el("a", "notif-item" + (n.read ? "" : " is-unread"));
        a.href = n.url;
        const ico = el("span", "notif-ico k-" + n.kind);
        ico.appendChild(icon(ICONS[n.kind] || "alerts"));
        const text = el("span", "notif-text");
        text.appendChild(el("strong", null, n.title));
        if (n.body) text.appendChild(el("span", null, n.body));
        const time = el("time", null, n.kind_label + " · " + n.ago);
        time.dateTime = n.at;
        text.appendChild(time);
        a.appendChild(ico); a.appendChild(text); a.appendChild(el("span", "notif-unread-dot"));
        li.appendChild(a); ul.appendChild(li);
      });
      body.appendChild(ul);
    }
    setUnread(data.unread);
  }
  function load() {
    return fetch(box.dataset.summaryUrl, { credentials: "same-origin", cache: "no-store" })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(render)
      .catch(() => { if (box.open) { body.textContent = ""; body.appendChild(el("p", "notif-empty", "Chưa tải được thông báo. Thử lại sau.")); } });
  }
  function poll() {
    if (document.hidden || navigator.onLine === false) return;
    if (box.open) { load(); return; }
    fetch(box.dataset.summaryUrl + "?chi_so=1", { credentials: "same-origin", cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (data) setUnread(data.unread); })
      .catch(() => {});
  }
  box.addEventListener("toggle", () => { if (box.open) load(); });
  // Bấm ra ngoài hoặc Esc thì đóng bảng.
  document.addEventListener("click", (e) => { if (box.open && !box.contains(e.target)) box.open = false; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && box.open) { box.open = false; summary.focus(); } });
  readAll.addEventListener("click", () => {
    readAll.disabled = true;
    fetch(box.dataset.readUrl, {
      method: "POST", credentials: "same-origin",
      headers: { "X-CSRFToken": box.dataset.csrf, Accept: "application/json" },
    }).then(() => load());
  });
  lastUnread = badge.hidden ? 0 : parseInt(badge.textContent, 10) || 0;
  setInterval(poll, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
