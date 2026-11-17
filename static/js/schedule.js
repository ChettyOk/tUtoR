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
    var start = new Date(slot.start_time);
    var options = { weekday: "long", month: "long", day: "numeric" };
    if (start.getFullYear() !== new Date().getFullYear()) options.year = "numeric";   // only show a different year
    return start.toLocaleDateString(undefined, options);
  }

  function timeLabel(slot) {
    var options = { hour: "numeric", minute: "2-digit" };
    return new Date(slot.start_time).toLocaleTimeString(undefined, options) + " – " +
      new Date(slot.end_time).toLocaleTimeString(undefined, options);
  }

  // "is-available", "is-booked", "is-cancelled" or "is-past": used for the colours.
  function stateOf(slot) {
    if (slot.status === "cancelled") return "is-cancelled";
    if (isPast(slot)) return "is-past";
    return slot.status === "booked" ? "is-booked" : "is-available";
  }

  var STATE_LABELS = {
    "is-available": "Available",
    "is-booked": "Booked",
    "is-cancelled": "Cancelled",
    "is-past": "Past"
  };

  // ---------- drawing the list ----------

  function button(label, action, id, className) {
    var node = make("button", "btn-slot " + className, label);
    node.type = "button";
    node.setAttribute("data-action", action);
    node.setAttribute("data-id", id);
    return node;
  }

  function buildActions(slot) {
    var box = make("div", "slot-actions");
    var open = slot.status === "available" && !isPast(slot);

    if (open && confirmingId === slot.id) {
      box.appendChild(make("span", "slot-note", "Cancel this session?"));
      box.appendChild(button("Yes, cancel", "confirm", slot.id, "btn-slot-danger"));
      box.appendChild(button("Keep", "keep", slot.id, "btn-slot-keep"));
    } else if (open) {
      box.appendChild(button("Edit", "edit", slot.id, "btn-slot-edit"));
      box.appendChild(button("Cancel", "cancel", slot.id, "btn-slot-cancel"));
    } else if (slot.status === "booked" && !isPast(slot)) {
      box.appendChild(make("span", "slot-note", "Booked by a student"));
    }
    return box;
  }

  function buildTile(slot) {
    var start = new Date(slot.start_time);
    var tile = make("div", "slot-tile");
    tile.setAttribute("aria-hidden", "true");
    tile.appendChild(make("span", "slot-tile-month", start.toLocaleDateString(undefined, { month: "short" })));
    tile.appendChild(make("span", "slot-tile-day", String(start.getDate())));
    return tile;
  }

  function buildRow(slot) {
    var state = stateOf(slot);
    var row = make("li", "slot-row " + state);
    if (slot.id === editingId) row.classList.add("is-editing");

    var main = make("div", "slot-main");
    var headline = make("div", "slot-headline");
    headline.appendChild(make("span", "slot-time", timeLabel(slot)));
    headline.appendChild(make("span", "slot-badge " + state, STATE_LABELS[state]));
    main.appendChild(headline);
    main.appendChild(make("div", "slot-day", dayLabel(slot)));
    var meta = make("div", "slot-meta");
    meta.appendChild(make("span", "slot-chip", "$" + Number(slot.price_per_hour).toFixed(2) + " per hour"));
    meta.appendChild(make("span", "slot-chip", LOCATIONS[slot.location_type] || slot.location_type));
    main.appendChild(meta);

    var side = make("div", "slot-side");
    side.appendChild(buildActions(slot));

    row.appendChild(buildTile(slot));
    row.appendChild(main);
    row.appendChild(side);
    return row;
  }

  // The two numbers in the page header: how many upcoming sessions, and which is next.
  function updateStats() {
    var upcoming = slots.filter(function (slot) {
      return slot.status !== "cancelled" && !isPast(slot);
    });
    var upcomingEl = document.getElementById("stat-upcoming");
    var nextEl = document.getElementById("stat-next");
    if (!upcomingEl || !nextEl) return;

    upcomingEl.textContent = String(upcoming.length);
    if (!upcoming.length) {
      nextEl.textContent = "None yet";
      return;
    }
    var next = new Date(upcoming[0].start_time);   // the server sends them in time order
    nextEl.textContent = next.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) +
      " · " + next.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
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
        updateStats();
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