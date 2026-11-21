/* Student home: cancel a confirmed booking from the booking list.
   Uses the same two-click confirm pattern as my_requests.js. */
(function () {
  "use strict";

  var list = document.querySelector("[data-booking-list]");
  if (!list) return;

  var tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");
  var alertBox = document.getElementById("booking-alert");
  var successBox = document.getElementById("booking-success");

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

  Array.prototype.forEach.call(list.querySelectorAll(".js-cancel-booking"), function (btn) {
    var label = btn.textContent;
    var armed = false;
    var timer = null;
    var row = btn.closest(".student-booking");
    var errorEl = row ? row.querySelector(".booking-error") : null;

    function reset() {
      armed = false;
      btn.textContent = label;
      btn.classList.remove("is-armed");
    }

    btn.addEventListener("click", function () {
      clearBoxes();
      if (errorEl) errorEl.hidden = true;

      if (!armed) {
        armed = true;
        btn.textContent = "Click again to cancel";
        btn.classList.add("is-armed");
        timer = window.setTimeout(reset, 4000);
        return;
      }

      window.clearTimeout(timer);
      btn.disabled = true;
      btn.textContent = "Cancelling…";

      fetch(btn.getAttribute("data-url"), {
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
            if (row) row.remove();
            showBox(successBox, result.data.message || "Booking cancelled.");
            if (!list.querySelector(".student-booking")) {
              var empty = document.createElement("p");
              empty.className = "student-empty mb-0";
              empty.textContent = "No confirmed bookings yet. Book an open time from a tutor below.";
              var body = list.querySelector(".card-body");
              var oldList = list.querySelector(".student-booking-list");
              if (oldList) oldList.remove();
              if (body) body.appendChild(empty);
            }
            return;
          }

          btn.disabled = false;
          reset();
          var message = (result.data && result.data.error) || "Couldn't cancel this booking. Please try again.";
          if (errorEl) {
            errorEl.textContent = message;
            errorEl.hidden = false;
          } else {
            showBox(alertBox, message);
          }
        })
        .catch(function () {
          btn.disabled = false;
          reset();
          var message = "Couldn't reach the server. Check your connection and try again.";
          if (errorEl) {
            errorEl.textContent = message;
            errorEl.hidden = false;
          } else {
            showBox(alertBox, message);
          }
        });
    });
  });
})();
