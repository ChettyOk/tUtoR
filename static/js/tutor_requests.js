
(function () {
  "use strict";

  var tokenInput = document.querySelector("#requests-section [name=csrfmiddlewaretoken]");

  function csrfToken() {
    if (tokenInput && tokenInput.value) return tokenInput.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  Array.prototype.forEach.call(document.querySelectorAll(".treq-card"), function (card) {
    var btn = card.querySelector(".js-interest");
    var countEl = card.querySelector(".js-count");
    var nounEl = card.querySelector(".js-noun");
    var errorEl = card.querySelector(".req-error");
    var hint = card.querySelector(".js-hint");

    function setJoined(joined) {
      card.classList.toggle("is-joined", joined);
      btn.textContent = joined ? "Withdraw offer" : "I can help";
      btn.classList.toggle("btn-green", !joined);
      btn.classList.toggle("btn-find-clear", joined);
      hint.hidden = !joined;
    }

    btn.addEventListener("click", function () {
      var joined = card.classList.contains("is-joined");
      var url = joined ? card.dataset.leaveUrl : card.dataset.joinUrl;
      errorEl.hidden = true;
      btn.disabled = true;

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
            errorEl.textContent = r.status === 400
              ? "This request is no longer open."
              : (r.body.error || "Something went wrong. Please try again.");
            errorEl.hidden = false;
            return;
          }
          var n = parseInt(countEl.textContent, 10) || 0;
          // 201 = newly joined, 200 on join = already joined (count unchanged)
          if (!joined && r.status === 201) n += 1;
          if (joined && r.body.removed) n = Math.max(0, n - 1);
          countEl.textContent = n;
          nounEl.textContent = n === 1 ? "tutor" : "tutors";
          setJoined(!joined);
        })
        .catch(function () {
          btn.disabled = false;
          errorEl.textContent = "Couldn't reach the server. Check your connection and try again.";
          errorEl.hidden = false;
        });
    });
  });
})();