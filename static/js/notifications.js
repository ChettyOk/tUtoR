(function () {
  const bell = document.getElementById("notif-bell");
  if (!bell) return;

  const csrf = bell.dataset.csrf;
  const readUrl = (id) => bell.dataset.readUrlTemplate.replace("/0/", "/" + id + "/");
  const badge = document.getElementById("notif-badge");
  const list = document.getElementById("notif-list");
  const markAllBtn = document.getElementById("notif-mark-all");

  function post(url, keepalive) {
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf },
      credentials: "same-origin",
      keepalive: !!keepalive,
    });
  }

  function setBadge(count) {
    if (count > 0) {
      badge.textContent = count > 9 ? "9+" : String(count);
      badge.hidden = false;
    } else {
      badge.hidden = true;
    }
    bell.querySelector("#notif-bell-btn").setAttribute(
      "aria-label",
      count > 0 ? "Notifications, " + count + " unread" : "Notifications"
    );
    markAllBtn.disabled = count === 0;
    // Keep the page header's own counter in sync, if we are on that page.
    const pageCount = document.getElementById("notif-page-unread");
    if (pageCount) pageCount.textContent = count;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderItem(n) {
    const item = el("div", "notif-item" + (n.is_read ? "" : " is-unread"));
    item.dataset.id = n.id;
    item.appendChild(el("span", "notif-dot"));
    const body = el("div", "notif-body");
    const title = el("a", "notif-title", n.title);
    title.href = n.url;
    title.addEventListener("click", () => {
      if (!n.is_read) post(readUrl(n.id), true);
    });
    body.appendChild(title);
    body.appendChild(el("p", "notif-msg", n.message));
    const meta = el("div", "notif-meta");
    meta.appendChild(el("span", "", n.time_ago));
    if (!n.is_read) {
      const btn = el("button", "notif-link-btn", "Mark as read");
      btn.type = "button";
      btn.addEventListener("click", async (event) => {
        event.stopPropagation();
        btn.disabled = true;
        const res = await post(readUrl(n.id));
        if (res.ok) refresh();
        else btn.disabled = false;
      });
      meta.appendChild(btn);
    }
    body.appendChild(meta);
    item.appendChild(body);
    return item;
  }

  async function refresh() {
    try {
      const res = await fetch(bell.dataset.recentUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!res.ok) return;
      const data = await res.json();
      setBadge(data.unread_count);
      list.replaceChildren();
      if (data.notifications.length === 0) {
        list.appendChild(el("p", "notif-empty", "You have no notifications yet."));
      } else {
        data.notifications.forEach((n) => list.appendChild(renderItem(n)));
      }
    } catch (err) {
      /* offline: keep what is on screen */
    }
  }

  markAllBtn.addEventListener("click", async () => {
    markAllBtn.disabled = true;
    const res = await post(bell.dataset.readAllUrl);
    if (res.ok) refresh();
  });

  document.getElementById("notif-bell-btn").addEventListener("click", refresh);

  refresh();
  setInterval(() => {
    if (!document.hidden) refresh();
  }, 60000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });

  // ---- "All notifications" page ----
  const page = document.getElementById("notif-page");
  if (!page) return;
  const deleteUrl = (id) => page.dataset.deleteUrlTemplate.replace("/0/", "/" + id + "/");

  page.querySelectorAll(".notif-item").forEach((row) => {
    const id = row.dataset.id;
    const link = row.querySelector(".notif-title");
    link.addEventListener("click", () => {
      if (row.classList.contains("is-unread")) post(readUrl(id), true);
    });

    const readBtn = row.querySelector("[data-action='read']");
    if (readBtn) {
      readBtn.addEventListener("click", async () => {
        readBtn.disabled = true;
        const res = await post(readUrl(id));
        if (!res.ok) { readBtn.disabled = false; return; }
        row.classList.remove("is-unread");
        readBtn.remove();
        refresh();
        if (page.dataset.filter === "unread") row.remove();
      });
    }

    row.querySelector("[data-action='delete']").addEventListener("click", async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      const res = await post(deleteUrl(id));
      if (!res.ok) { btn.disabled = false; return; }
      row.remove();
      refresh();
      if (!page.querySelector(".notif-item")) window.location.reload();
    });
  });

  const pageMarkAll = document.getElementById("notif-page-mark-all");
  if (pageMarkAll) {
    pageMarkAll.addEventListener("click", async () => {
      pageMarkAll.disabled = true;
      const res = await post(bell.dataset.readAllUrl);
      if (res.ok) window.location.reload();
      else pageMarkAll.disabled = false;
    });
  }
})();