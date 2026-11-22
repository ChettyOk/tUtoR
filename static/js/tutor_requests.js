
/* Tutor request cards: Accept joins immediately; Decline needs a second click. */
(function () {
  "use strict";

  var section = document.getElementById("requests-section");
  if (!section) return;

  var tokenInput =
    section.querySelector("[name=csrfmiddlewaretoken]") ||
    document.querySelector("[name=csrfmiddlewaretoken]");

  function csrfToken() {
    if (tokenInput && tokenInput.value) return tokenInput.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  Array.prototype.forEach.call(document.querySelectorAll(".treq-card"), function (card) {
    var btn = card.querySelector(".js-interest");
    if (!btn) return;

    var countEl = card.querySelector(".js-count");
    var nounEl = card.querySelector(".js-noun");
    var errorEl = card.querySelector(".req-error");
    var hint = card.querySelector(".js-hint");
    var joinLabel = card.dataset.joinLabel || "Accept";
    var leaveLabel = card.dataset.leaveLabel || "Decline";
    var armed = false;
    var timer = null;

    function clearArm() {
      armed = false;
      btn.classList.remove("is-armed");
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
    }

    function setJoined(joined) {
      clearArm();
      card.classList.toggle("is-joined", joined);
      btn.textContent = joined ? leaveLabel : joinLabel;
      btn.classList.toggle("btn-green", !joined);
      btn.classList.toggle("btn-outline-secondary", joined);
      btn.classList.toggle("btn-find-clear", joined);
      if (hint) hint.hidden = !joined;
    }

    function postInterest(joined) {
      var url = joined ? card.dataset.leaveUrl : card.dataset.joinUrl;
      if (errorEl) errorEl.hidden = true;
      btn.disabled = true;
      btn.textContent = joined ? "Declining…" : "Accepting…";

      fetch(url, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin"
      })
        .then(function (res) {
          return res.json().catch(function () { return {}; }).then(function (body) {
            return { ok: res.ok, status: res.status, body: body };
          });
        })
        .then(function (r) {
          btn.disabled = false;
          if (!r.ok) {
            setJoined(joined);
            if (errorEl) {
              errorEl.textContent = r.status === 400
                ? "This request is no longer open."
                : (r.body.error || "Something went wrong. Please try again.");
              errorEl.hidden = false;
            }
            return;
          }
          if (countEl && nounEl) {
            var n = parseInt(countEl.textContent, 10) || 0;
            // 201 = newly joined, 200 on join = already joined (count unchanged)
            if (!joined && r.status === 201) n += 1;
            if (joined && r.body.removed) n = Math.max(0, n - 1);
            countEl.textContent = n;
            nounEl.textContent = n === 1 ? "tutor" : "tutors";
          }
          setJoined(!joined);
        })
        .catch(function () {
          btn.disabled = false;
          setJoined(joined);
          if (errorEl) {
            errorEl.textContent = "Couldn't reach the server. Check your connection and try again.";
            errorEl.hidden = false;
          }
        });
    }

    btn.addEventListener("click", function () {
      var joined = card.classList.contains("is-joined");
      if (errorEl) errorEl.hidden = true;

      // Accept is one click.
      if (!joined) {
        clearArm();
        postInterest(false);
        return;
      }

      // Decline needs a second confirm click.
      if (!armed) {
        armed = true;
        btn.textContent = "Click again to decline";
        btn.classList.add("is-armed");
        timer = window.setTimeout(function () {
          clearArm();
          btn.textContent = leaveLabel;
        }, 4000);
        return;
      }

      clearArm();
      postInterest(true);
    });
  });
})();
