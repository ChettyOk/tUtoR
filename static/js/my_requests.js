// My requests page: two-click "Withdraw request" button.
(function () {
  "use strict";

  var tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");

  function csrfToken() {
    if (tokenInput && tokenInput.value) return tokenInput.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  Array.prototype.forEach.call(document.querySelectorAll(".js-withdraw"), function (btn) {
    var label = btn.textContent;
    var armed = false;
    var timer = null;
    var errorEl = btn.parentNode.querySelector(".req-error");

    function reset() {
      armed = false;
      btn.textContent = label;
      btn.classList.remove("is-armed");
    }

    btn.addEventListener("click", function () {
      errorEl.hidden = true;

      // First click only asks "are you sure?"; it resets after a few seconds.
      if (!armed) {
        armed = true;
        btn.textContent = "Click again to withdraw";
        btn.classList.add("is-armed");
        timer = window.setTimeout(reset, 4000);
        return;
      }

      window.clearTimeout(timer);
      btn.disabled = true;
      btn.textContent = "Withdrawing…";

      fetch(btn.dataset.url, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin"
      })
        .then(function (res) {
          return res.json().catch(function () { return {}; }).then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (r) {
          if (r.ok) {
            window.location.reload();
            return;
          }
          btn.disabled = false;
          reset();
          errorEl.textContent = r.body.error || "Couldn't withdraw this request. Please try again.";
          errorEl.hidden = false;
        })
        .catch(function () {
          btn.disabled = false;
          reset();
          errorEl.textContent = "Couldn't reach the server. Check your connection and try again.";
          errorEl.hidden = false;
        });
    });
  });
})();