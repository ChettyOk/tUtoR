// Lets the student pick a time range inside the open window, shows the live
// price, then POSTs to the existing booking endpoint and reacts to the result.
(function () {
  "use strict";

  var dataEl = document.getElementById("booking-data");
  if (!dataEl) return;
  var data = JSON.parse(dataEl.textContent);

  var form = document.getElementById("book-form");
  var startInput = document.getElementById("book-start");
  var endInput = document.getElementById("book-end");
  var courseSelect = document.getElementById("book-course");
  var noteInput = document.getElementById("book-note");
  var noteCounter = document.getElementById("note-counter");
  var submitBtn = document.getElementById("book-submit");
  var timeError = document.getElementById("time-error");
  var formError = document.getElementById("form-error");
  var successBox = document.getElementById("book-success");

  var MIN_MINUTES = 15;
  var winStart = new Date(data.window_start);
  var winEnd = new Date(data.window_end);
  var pricePerHour = parseFloat(data.price_per_hour);

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  // Date -> value for <input type="datetime-local"> (local time, to the minute)
  function toInputValue(d) {
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function fmtDate(d) {
    return d.toLocaleString(undefined, {
      weekday: "short", month: "short", day: "numeric", year: "numeric",
      hour: "numeric", minute: "2-digit"
    });
  }
  function fmtTime(d) {
    return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  function fmtRange(a, b) { return fmtDate(a) + " – " + fmtTime(b); }

  function money(n) { return "$" + n.toFixed(2); }

  function fmtLength(ms) {
    var mins = Math.round(ms / 60000);
    var h = Math.floor(mins / 60);
    var m = mins % 60;
    if (h && m) return h + " h " + m + " min";
    if (h) return h + " h";
    return m + " min";
  }

  // The earliest start we allow: the window start, or if the window has
  // already begun, the next quarter hour from now.
  function earliestStart() {
    var now = new Date();
    if (winStart.getTime() > now.getTime()) return winStart;
    var d = new Date(now.getTime() + 60000);
    d.setSeconds(0, 0);
    var rest = d.getMinutes() % 15;
    if (rest) d.setMinutes(d.getMinutes() + (15 - rest));
    return d;
  }

  // Read an input. If the student left it at the window edge, use the
  // server's exact value so a full-slot booking stays a full-slot booking.
  function readInput(input, edgeDate, edgeString) {
    if (!input.value) return null;
    var d = new Date(input.value);
    if (isNaN(d.getTime())) return null;
    if (Math.abs(d.getTime() - edgeDate.getTime()) < 60000) {
      return { date: edgeDate, iso: edgeString };
    }
    return { date: d, iso: d.toISOString().replace(/\.\d{3}Z$/, "Z") };
  }

  function currentRange() {
    return {
      start: readInput(startInput, winStart, data.window_start),
      end: readInput(endInput, winEnd, data.window_end)
    };
  }

  function validate(range) {
    if (!range.start || !range.end) return "Choose a start and an end time.";
    var s = range.start.date, e = range.end.date;
    if (e <= s) return "The end time must be after the start time.";
    if (s <= new Date()) return "That start time has already passed.";
    if (s < winStart) return "Start can't be before " + fmtDate(winStart) + ".";
    if (e > winEnd) return "End can't be after " + fmtTime(winEnd) + ".";
    if (e - s < MIN_MINUTES * 60000) {
      return "A session must be at least " + MIN_MINUTES + " minutes.";
    }
    return "";
  }

  function showError(el, message) {
    el.textContent = message || "";
    el.hidden = !message;
  }

  function refresh() {
    var range = currentRange();
    var error = validate(range);
    showError(timeError, error);
    submitBtn.disabled = !!error;
    if (!error) {
      var ms = range.end.date - range.start.date;
      document.getElementById("sum-when").textContent = fmtRange(range.start.date, range.end.date);
      document.getElementById("sum-length").textContent = fmtLength(ms);
      document.getElementById("sum-total").textContent =
        money(Math.round(pricePerHour * (ms / 3600000) * 100) / 100);
    } else {
      document.getElementById("sum-when").textContent = "–";
      document.getElementById("sum-length").textContent = "–";
      document.getElementById("sum-total").textContent = "–";
    }
    return !error;
  }

  function csrfToken() {
    var input = form.querySelector("[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showSuccess(body, range) {
    document.getElementById("ok-when").textContent = fmtRange(range.start.date, range.end.date);
    document.getElementById("ok-total").textContent = money(parseFloat(body.session_price));
    document.getElementById("ok-id").textContent = "#" + body.booking_id;
    form.hidden = true;
    successBox.hidden = false;
    successBox.focus();
    successBox.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function showGoneModal() {
    var el = document.getElementById("gone-modal");
    if (window.bootstrap && el) {
      window.bootstrap.Modal.getOrCreateInstance(el).show();
    } else {
      showError(formError, "This time is no longer available. Please pick another time.");
    }
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    showError(formError, "");
    if (!refresh()) return;

    var range = currentRange();
    var fd = new FormData();
    fd.append("start_time", range.start.iso);
    fd.append("end_time", range.end.iso);
    if (courseSelect && courseSelect.value) fd.append("course_id", courseSelect.value);
    fd.append("student_note", noteInput.value.trim());

    submitBtn.disabled = true;
    var oldLabel = submitBtn.textContent;
    submitBtn.textContent = "Booking…";

    fetch(data.post_url, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: fd
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (r) {
        if (r.status === 201) {
          showSuccess(r.body, range);
          return;
        }
        submitBtn.textContent = oldLabel;
        submitBtn.disabled = false;
        if (r.status === 409) {
          showGoneModal();
        } else if (r.status === 401) {
          showError(formError, "Your session expired. Please log in again and retry.");
        } else if (r.status === 403) {
          showError(formError, "Only students can book sessions.");
        } else {
          showError(formError, r.body.error || "Something went wrong. Please try again.");
        }
      })
      .catch(function () {
        submitBtn.textContent = oldLabel;
        submitBtn.disabled = false;
        showError(formError, "Couldn't reach the server. Check your connection and try again.");
      });
  });

  // Set up the form
  startInput.min = endInput.min = toInputValue(winStart);
  startInput.max = endInput.max = toInputValue(winEnd);
  startInput.value = toInputValue(earliestStart());
  endInput.value = toInputValue(winEnd);
  document.getElementById("window-label").textContent = fmtRange(winStart, winEnd);

  [startInput, endInput].forEach(function (el) {
    el.addEventListener("input", refresh);
    el.addEventListener("change", refresh);
  });
  noteInput.addEventListener("input", function () {
    noteCounter.textContent = noteInput.value.length + " / 255";
  });
  refresh();
})();