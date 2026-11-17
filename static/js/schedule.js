/* Tutor sessions page: the "Your schedule" list.
   Loads the tutor's slots, shows them, and lets the tutor cancel one or send it to the
   form for editing. Talks to sessions.js through events: it listens for "slot:saved" and
   "slot:edit-ended" and fires "slot:edit" and "slot:cancelled". */
(function () {
  "use strict";

  var section = document.getElementById("schedule-section");
  if (!section) return;

  var listEl = document.getElementById("schedule-list");
  var statusEl = document.getElementById("schedule-status");
  var errorBox = document.getElementById("schedule-alert");
  var successBox = document.getElementById("schedule-success");
  var showAllBox = document.getElementById("schedule-show-all");

  var LOCATIONS = { online: "Online", in_person: "In person" };

  var slots = [];
  var confirmingId = null;   // the slot whose "Cancel?" question is open
  var editingId = null;      // the slot currently loaded into the form

  // ---------- helpers ----------

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function isPast(slot) {
    return new Date(slot.end_time) <= new Date();
  }

  // The urls in the page have 0 where the slot id goes.
  function urlFor(attribute, id) {
    return section.getAttribute(attribute).replace("/0/", "/" + id + "/");
  }

  function csrfToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]").value;
  }

  function showError(text) {
    errorBox.textContent = text;
    errorBox.hidden = false;
  }

  function clearMessages() {
    errorBox.hidden = true;
    successBox.hidden = true;
  }

  function dayLabel(slot) {
    return new Date(slot.start_time).toLocaleDateString(undefined, {
      weekday: "long", month: "long", day: "numeric", year: "numeric"
    });
  }

  function timeLabel(slot) {
    var options = { hour: "numeric", minute: "2-digit" };
    return new Date(slot.start_time).toLocaleTimeString(undefined, options) + " – " +
      new Date(slot.end_time).toLocaleTimeString(undefined, options);
  }

  function badgeFor(slot) {
    if (slot.status === "cancelled") return make("span", "badge text-bg-secondary", "Cancelled");
    if (isPast(slot)) return make("span", "badge text-bg-light border", "Past");
    if (slot.status === "booked") return make("span", "badge text-bg-primary", "Booked");
    return make("span", "badge text-bg-success", "Available");
  }

  // ---------- drawing the list ----------

  function button(label, action, id, className) {
    var node = make("button", "btn btn-sm " + className, label);
    node.type = "button";
    node.setAttribute("data-action", action);
    node.setAttribute("data-id", id);
    return node;
  }

  function buildActions(slot) {
    var box = make("div", "d-flex flex-wrap align-items-center gap-2");
    var open = slot.status === "available" && !isPast(slot);

    if (open && confirmingId === slot.id) {
      box.appendChild(make("span", "small", "Cancel this session?"));
      box.appendChild(button("Yes, cancel", "confirm", slot.id, "btn-danger"));
      box.appendChild(button("Keep", "keep", slot.id, "btn-outline-secondary"));
    } else if (open) {
      box.appendChild(button("Edit", "edit", slot.id, "btn-outline-green"));
      box.appendChild(button("Cancel", "cancel", slot.id, "btn-outline-danger"));
    } else if (slot.status === "booked" && !isPast(slot)) {
      box.appendChild(make("span", "small text-muted", "A student booked this time"));
    }
    return box;
  }

  function buildRow(slot) {
    var row = make("li", "list-group-item px-0 d-flex flex-wrap justify-content-between align-items-center gap-2");
    if (slot.id === editingId) row.classList.add("bg-light");
    if (slot.status === "cancelled" || isPast(slot)) row.classList.add("text-muted");

    var info = make("div");
    info.appendChild(make("div", "fw-semibold", dayLabel(slot)));
    info.appendChild(make("div", "small",
      timeLabel(slot) + " · $" + Number(slot.price_per_hour).toFixed(2) + " per hour · " +
      (LOCATIONS[slot.location_type] || slot.location_type)));

    var side = make("div", "d-flex flex-wrap align-items-center gap-3");
    side.appendChild(badgeFor(slot));
    side.appendChild(buildActions(slot));

    row.appendChild(info);
    row.appendChild(side);
    return row;
  }

  function render() {
    var visible = slots.filter(function (slot) {
      return showAllBox.checked || (slot.status !== "cancelled" && !isPast(slot));
    });

    listEl.textContent = "";
    visible.forEach(function (slot) { listEl.appendChild(buildRow(slot)); });

    if (visible.length) {
      statusEl.hidden = true;
    } else {
      statusEl.textContent = showAllBox.checked
        ? "You have no sessions yet."
        : "No upcoming sessions. Add one with the form.";
      statusEl.hidden = false;
    }
  }

  // ---------- talking to the server ----------

  function load() {
    fetch(section.getAttribute("data-list-url"), {
      credentials: "same-origin",
      headers: { Accept: "application/json" }
    })
      .then(function (response) {
        if (!response.ok) throw new Error("bad response");
        return response.json();
      })
      .then(function (data) {
        slots = data.slots;
        render();
      })
      .catch(function () {
        statusEl.hidden = true;
        showError("Could not load your sessions. Reload the page and try again.");
      });
  }

  function cancelSlot(id) {
    clearMessages();
    fetch(urlFor("data-delete-url", id), {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" }
    })
      .then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        confirmingId = null;
        if (result.ok) {
          successBox.textContent = "Session cancelled.";
          successBox.hidden = false;
          document.dispatchEvent(new CustomEvent("slot:cancelled", { detail: { id: id } }));
        } else {
          showError(result.data.error || "The session could not be cancelled.");
        }
        load();   // always reload, in case the slot changed meanwhile
      })
      .catch(function () {
        showError("Something went wrong. Please try again.");
      });
  }

  // ---------- events ----------

  listEl.addEventListener("click", function (event) {
    var target = event.target.closest("[data-action]");
    if (!target) return;
    var id = Number(target.getAttribute("data-id"));
    var action = target.getAttribute("data-action");

    if (action === "edit") {
      var slot = slots.filter(function (item) { return item.id === id; })[0];
      if (!slot) return;
      clearMessages();
      editingId = id;
      render();
      document.dispatchEvent(new CustomEvent("slot:edit", { detail: slot }));
    } else if (action === "cancel") {
      confirmingId = id;
      render();
    } else if (action === "keep") {
      confirmingId = null;
      render();
    } else if (action === "confirm") {
      cancelSlot(id);
    }
  });

  showAllBox.addEventListener("change", render);

  // The form saved a session: show the change.
  document.addEventListener("slot:saved", function () {
    editingId = null;
    clearMessages();
    load();
  });

  // The tutor stopped editing: remove the highlight.
  document.addEventListener("slot:edit-ended", function () {
    editingId = null;
    render();
  });

  load();
})();