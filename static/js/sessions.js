/* Tutor sessions page: the session form (new or edit) and its live summary.
   Loads the price limits and location choices from the server, checks the form in the
   browser, then sends the slot to the server, which checks it again.
   Talks to schedule.js through events: it listens for "slot:edit" and "slot:cancelled"
   and fires "slot:saved" and "slot:edit-ended". */
(function () {
  "use strict";

  var form = document.getElementById("slot-form");
  if (!form) return;

  var startInput = document.getElementById("slot-start");
  var endInput = document.getElementById("slot-end");
  var priceInput = document.getElementById("slot-price");
  var locationSelect = document.getElementById("slot-location");
  var submitButton = document.getElementById("slot-submit");
  var suggestButton = document.getElementById("slot-suggest");
  var priceHint = document.getElementById("slot-price-hint");
  var cancelEditButton = document.getElementById("slot-cancel-edit");
  var formHeading = document.getElementById("session-form-heading");
  var errorBox = document.getElementById("slot-alert");
  var successBox = document.getElementById("slot-success");

  var infoEmpty = document.getElementById("info-empty");
  var infoDetails = document.getElementById("info-details");

  var limits = { min: null, max: null, suggested: null };
  var attempted = false;   // show field errors live only after the first submit
  var editingId = null;    // the id of the slot being edited, or null for a new slot

  // ---------- small helpers ----------

  function pad(n) { return (n < 10 ? "0" : "") + n; }

  // A Date as the text a datetime-local input uses, in the browser's own time zone.
  function toInputValue(date) {
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) +
      "T" + pad(date.getHours()) + ":" + pad(date.getMinutes());
  }

  function readDate(input) {
    if (!input.value) return null;
    var date = new Date(input.value);   // read in the browser's time zone
    return isNaN(date.getTime()) ? null : date;
  }

  function readPrice() {
    var text = priceInput.value.trim();
    if (!text) return null;
    var number = Number(text);
    return isFinite(number) ? number : null;
  }

  function money(number) { return "$" + number.toFixed(2); }

  function formatDuration(minutes) {
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    if (!hours) return rest + " min";
    return rest ? hours + " h " + rest + " min" : hours + " h";
  }

  function showBox(box, text) {
    box.textContent = text;
    box.hidden = false;
  }

  function clearBoxes() {
    errorBox.hidden = true;
    successBox.hidden = true;
  }

  // ---------- field errors ----------

  function setFieldError(input, message) {
    var note = document.getElementById(input.id + "-error");
    input.classList.toggle("is-invalid", Boolean(message));
    input.setAttribute("aria-invalid", message ? "true" : "false");
    note.textContent = message || "";
    note.hidden = !message;
  }

  // Returns true when everything is fine. Mirrors the rules the server enforces.
  function validate() {
    var start = readDate(startInput);
    var end = readDate(endInput);
    var price = readPrice();
    var ok = true;

    var startMessage = "";
    if (!start) startMessage = "Choose when the session starts.";
    else if (start <= new Date()) startMessage = "The start time must be in the future.";

    var endMessage = "";
    if (!end) endMessage = "Choose when the session ends.";
    else if (start && end <= start) endMessage = "The end time must be after the start time.";

    var priceMessage = "";
    if (price === null) priceMessage = "Enter a price per hour.";
    else if (limits.min !== null && price < limits.min) priceMessage = "The minimum price is " + money(limits.min) + " per hour.";
    else if (limits.max !== null && price > limits.max) priceMessage = "The maximum price is " + money(limits.max) + " per hour.";

    setFieldError(startInput, startMessage);
    setFieldError(endInput, endMessage);
    setFieldError(priceInput, priceMessage);
    return !(startMessage || endMessage || priceMessage);
  }

  // ---------- live summary ----------

  function updateSummary() {
    var start = readDate(startInput);
    var end = readDate(endInput);
    var price = readPrice();

    if (!start || !end || end <= start) {
      infoDetails.hidden = true;
      infoEmpty.hidden = false;
      return;
    }

    var minutes = Math.round((end - start) / 60000);
    var dateOptions = { weekday: "long", month: "long", day: "numeric", year: "numeric" };
    var timeOptions = { hour: "numeric", minute: "2-digit" };
    var sameDay = start.toDateString() === end.toDateString();

    document.getElementById("info-date").textContent = start.toLocaleDateString(undefined, dateOptions);
    document.getElementById("info-time").textContent = sameDay
      ? start.toLocaleTimeString(undefined, timeOptions) + " – " + end.toLocaleTimeString(undefined, timeOptions)
      : start.toLocaleString(undefined, timeOptions) + " – " + end.toLocaleDateString(undefined, { month: "short", day: "numeric" }) + ", " + end.toLocaleTimeString(undefined, timeOptions);
    document.getElementById("info-length").textContent = formatDuration(minutes);
    document.getElementById("info-price").textContent = price === null ? "—" : money(price) + " per hour";
    document.getElementById("info-total").textContent = price === null ? "—"
      : money(Math.round(price * 100 * minutes / 60) / 100);
    document.getElementById("info-where").textContent = locationSelect.options[locationSelect.selectedIndex]
      ? locationSelect.options[locationSelect.selectedIndex].textContent : "—";

    infoEmpty.hidden = true;
    infoDetails.hidden = false;
  }

  function refresh() {
    if (attempted) validate();
    updateSummary();
  }

  // ---------- load the price limits and location choices ----------

  function loadOptions() {
    fetch(form.getAttribute("data-url"), { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("bad response");
        return response.json();
      })
      .then(function (data) {
        limits.min = parseFloat(data.min_price);
        limits.max = parseFloat(data.max_price);
        limits.suggested = parseFloat(data.suggested_price);

        priceInput.min = limits.min;
        priceInput.max = limits.max;
        priceInput.value = limits.suggested.toFixed(2);
        priceHint.textContent = "Suggested " + money(limits.suggested) + " per hour (the average of current offers). " +
          "Allowed: " + money(limits.min) + " to " + money(limits.max) + ".";

        locationSelect.textContent = "";
        data.location_types.forEach(function (type) {
          var option = document.createElement("option");
          option.value = type.value;
          option.textContent = type.label;
          locationSelect.appendChild(option);
        });

        locationSelect.disabled = false;
        submitButton.disabled = false;
        suggestButton.hidden = false;
        updateSummary();
      })
      .catch(function () {
        showBox(errorBox, "Could not load the form options. Reload the page and try again.");
      });
  }

  // ---------- edit mode ----------

  function clearFieldErrors() {
    setFieldError(startInput, "");
    setFieldError(endInput, "");
    setFieldError(priceInput, "");
  }

  function enterEditMode(slot) {
    editingId = slot.id;
    clearBoxes();
    attempted = false;
    clearFieldErrors();

    startInput.value = toInputValue(new Date(slot.start_time));
    endInput.value = toInputValue(new Date(slot.end_time));
    priceInput.value = Number(slot.price_per_hour).toFixed(2);
    locationSelect.value = slot.location_type;

    formHeading.textContent = "2. Edit session";
    submitButton.textContent = "Save changes";
    cancelEditButton.hidden = false;

    updateSummary();
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    startInput.focus();
  }

  function leaveEditMode() {
    var wasEditing = editingId !== null;
    editingId = null;
    formHeading.textContent = "2. New session";
    submitButton.textContent = "Add session";
    cancelEditButton.hidden = true;

    startInput.value = "";
    endInput.value = "";
    if (limits.suggested !== null) priceInput.value = limits.suggested.toFixed(2);
    locationSelect.selectedIndex = 0;
    attempted = false;
    clearFieldErrors();
    updateSummary();

    if (wasEditing) document.dispatchEvent(new CustomEvent("slot:edit-ended"));
  }

  document.addEventListener("slot:edit", function (event) { enterEditMode(event.detail); });
  document.addEventListener("slot:cancelled", function (event) {
    if (editingId === event.detail.id) leaveEditMode();
  });
  cancelEditButton.addEventListener("click", function () {
    clearBoxes();
    leaveEditMode();
  });

  // ---------- send the slot ----------

  // The update URL in the page has 0 where the slot id goes.
  function slotUrl() {
    if (editingId === null) return form.getAttribute("data-url");
    return form.getAttribute("data-update-url").replace("/0/", "/" + editingId + "/");
  }

  function csrfToken() {
    return form.querySelector("[name=csrfmiddlewaretoken]").value;
  }

  function describeSlot(start, end) {
    return start.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" }) + ", " +
      start.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }) + " – " +
      end.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    clearBoxes();
    attempted = true;
    if (!validate()) {
      var firstBad = form.querySelector(".is-invalid");
      if (firstBad) firstBad.focus();
      return;
    }

    var start = readDate(startInput);
    var end = readDate(endInput);
    // toISOString() sends the exact moment (UTC), so the server never guesses the time zone.
    var body = new URLSearchParams({
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      price_per_hour: priceInput.value.trim(),
      location_type: locationSelect.value
    });

    var wasEditing = editingId !== null;
    submitButton.disabled = true;
    fetch(slotUrl(), {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
      body: body
    })
      .then(function (response) {
        return response.json().then(function (data) { return { ok: response.ok, data: data }; });
      })
      .then(function (result) {
        if (!result.ok) {
          showBox(errorBox, result.data.error || "The session could not be saved.");
          return;
        }
        leaveEditMode();
        showBox(successBox, (wasEditing ? "Session updated: " : "Session added: ") + describeSlot(start, end) + ".");
        // The schedule list listens for this and reloads itself.
        document.dispatchEvent(new CustomEvent("slot:saved", { detail: result.data.slot }));
      })
      .catch(function () {
        showBox(errorBox, "Something went wrong. Please try again.");
      })
      .then(function () {
        submitButton.disabled = false;
      });
  });

  // ---------- wiring ----------

  startInput.min = toInputValue(new Date());

  startInput.addEventListener("change", function () {
    var start = readDate(startInput);
    var end = readDate(endInput);
    if (start && (!end || end <= start)) {
      endInput.value = toInputValue(new Date(start.getTime() + 60 * 60 * 1000));   // default: 1 hour
    }
    refresh();
  });
  [endInput, priceInput, locationSelect].forEach(function (input) {
    input.addEventListener("input", refresh);
    input.addEventListener("change", refresh);
  });

  suggestButton.addEventListener("click", function () {
    if (limits.suggested !== null) {
      priceInput.value = limits.suggested.toFixed(2);
      refresh();
    }
  });

  loadOptions();
})();