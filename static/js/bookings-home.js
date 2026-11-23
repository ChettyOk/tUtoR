/* Home pages: cancel a confirmed booking from the booking list.
   Student home uses two-click arming; tutor home uses a confirm modal. */
(function () {
  "use strict";

  var list = document.querySelector("[data-booking-list]");
  if (!list) return;

  var tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");
  var alertBox = document.getElementById("booking-alert");
  var successBox = document.getElementById("booking-success");
  var emptyMessage = list.getAttribute("data-empty-message")
    || "No confirmed bookings yet. Book an open time from a tutor below.";
  var emptyClass = list.getAttribute("data-empty-class") || "student-empty mb-0";
  var confirmModalId = list.getAttribute("data-confirm-modal");
  var confirmModalEl = confirmModalId
    ? document.getElementById(confirmModalId)
    : null;
  var confirmSummary = document.getElementById("cancel-confirm-summary");
  var confirmBtn = document.getElementById("cancel-confirm-submit");
  var pending = null;

  function csrfToken() {
    if (tokenInput && tokenInput.value) return tokenInput.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function showBox(box, text) {
    if (!box) return;
    box.textContent = text;
    box.hidden = false;
  }

  function clearBoxes() {
    if (alertBox) alertBox.hidden = true;
    if (successBox) successBox.hidden = true;
  }

  function isDeadlineError(message) {
    return /cancellation deadline has passed/i.test(message || "");
  }

  function showDeadlineModal(message) {
    var el = document.getElementById("cancel-deadline-modal");
    var body = document.getElementById("cancel-deadline-body");
    if (body && message) body.textContent = message;
    if (window.bootstrap && el) {
      window.bootstrap.Modal.getOrCreateInstance(el).show();
      return true;
    }
    return false;
  }

  function bookingSummary(row, btn) {
    var fromBtn = btn.getAttribute("data-summary");
    if (fromBtn) return fromBtn;
    if (!row) return "this session";
    var strong = row.querySelector(".student-booking-info strong");
    var span = row.querySelector(".student-booking-info span");
    var parts = [];
    if (strong && strong.textContent.trim()) parts.push(strong.textContent.trim());
    if (span && span.textContent.trim()) parts.push(span.textContent.trim());
    return parts.join(" · ") || "this session";
  }

  function removeRow(row) {
    if (row) row.remove();
    if (!list.querySelector(".student-booking")) {
      var empty = document.createElement("p");
      empty.className = emptyClass;
      empty.textContent = emptyMessage;
      var body = list.querySelector(".card-body");
      var oldList = list.querySelector(".student-booking-list");
      if (oldList) oldList.remove();
      if (body) body.appendChild(empty);
    }
  }

  function showError(errorEl, message) {
    if (errorEl) {
      errorEl.textContent = message;
      errorEl.hidden = false;
    } else {
      showBox(alertBox, message);
    }
  }

  function postCancel(btn, row, errorEl) {
    btn.disabled = true;
    var original = btn.textContent;
    btn.textContent = "Cancelling…";

    return fetch(btn.getAttribute("data-url"), {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "X-CSRFToken": csrfToken(),
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest"
      }
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
      })
      .then(function (result) {
        if (result.ok) {
          removeRow(row);
          showBox(successBox, result.data.message || "Booking cancelled.");
          return;
        }

        btn.disabled = false;
        btn.textContent = original;
        btn.classList.remove("is-armed");
        var message = (result.data && result.data.error)
          || "Couldn't cancel this booking. Please try again.";
        if (isDeadlineError(message) && showDeadlineModal(message)) {
          return;
        }
        showError(errorEl, message);
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = original;
        btn.classList.remove("is-armed");
        showError(
          errorEl,
          "Couldn't reach the server. Check your connection and try again."
        );
      });
  }

  function openConfirmModal(btn, row, errorEl) {
    pending = { btn: btn, row: row, errorEl: errorEl };
    if (confirmSummary) {
      confirmSummary.textContent = bookingSummary(row, btn);
    }
    if (window.bootstrap && confirmModalEl) {
      window.bootstrap.Modal.getOrCreateInstance(confirmModalEl).show();
      return true;
    }
    return false;
  }

  if (confirmBtn && confirmModalEl) {
    confirmBtn.addEventListener("click", function () {
      if (!pending) return;
      var current = pending;
      pending = null;
      if (window.bootstrap) {
        window.bootstrap.Modal.getOrCreateInstance(confirmModalEl).hide();
      }
      clearBoxes();
      if (current.errorEl) current.errorEl.hidden = true;
      postCancel(current.btn, current.row, current.errorEl);
    });

    confirmModalEl.addEventListener("hidden.bs.modal", function () {
      pending = null;
    });
  }

  Array.prototype.forEach.call(list.querySelectorAll(".js-cancel-booking"), function (btn) {
    var label = btn.textContent;
    var armed = false;
    var timer = null;
    var row = btn.closest(".student-booking");
    var errorEl = row ? row.querySelector(".booking-error") : null;
    var useModal = !!(confirmModalEl && list.getAttribute("data-confirm-modal"));

    function reset() {
      armed = false;
      btn.textContent = label;
      btn.classList.remove("is-armed");
    }

    btn.addEventListener("click", function () {
      clearBoxes();
      if (errorEl) errorEl.hidden = true;

      if (useModal) {
        if (!openConfirmModal(btn, row, errorEl)) {
          // Fallback if Bootstrap is unavailable.
          if (!armed) {
            armed = true;
            btn.textContent = "Click again to cancel";
            btn.classList.add("is-armed");
            timer = window.setTimeout(reset, 4000);
            return;
          }
          window.clearTimeout(timer);
          postCancel(btn, row, errorEl).then(reset);
        }
        return;
      }

      if (!armed) {
        armed = true;
        btn.textContent = "Click again to cancel";
        btn.classList.add("is-armed");
        timer = window.setTimeout(reset, 4000);
        return;
      }

      window.clearTimeout(timer);
      postCancel(btn, row, errorEl).then(function () {
        if (btn.isConnected) reset();
      });
    });
  });
})();
