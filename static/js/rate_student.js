// Rate-student modal.
// A finished-but-still-"confirmed" booking is marked completed first, then rated.
(function () {
  "use strict";

  var script = document.currentScript;
  var completeUrl = script.dataset.completeUrl;
  var rateUrl = script.dataset.rateUrl;
  var modalEl = document.getElementById("rate-modal");
  var form = document.getElementById("rate-form");
  var errorEl = document.getElementById("rate-error");
  var submitBtn = document.getElementById("rate-submit");
  var commentEl = document.getElementById("rate-comment");
  var counterEl = document.getElementById("rate-comment-count");
  var toRateList = document.getElementById("to-rate-list");
  var ratedList = document.getElementById("rated-list");
  var modal = new bootstrap.Modal(modalEl);
  var currentCard = null;

  var tokenInput = document.querySelector("[name=csrfmiddlewaretoken]");
  function csrfToken() {
    if (tokenInput && tokenInput.value) return tokenInput.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function urlFor(template, id) {
    return template.replace("/0/", "/" + id + "/");
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken() },
      credentials: "same-origin",
      body: body || null,
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        return { ok: res.ok, status: res.status, data: data };
      });
    });
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function updateCounts() {
    var toRate = toRateList.children.length;
    var rated = ratedList.children.length;
    document.getElementById("to-rate-count").textContent = toRate;
    document.getElementById("rated-count").textContent = rated;
    document.getElementById("to-rate-empty").hidden = toRate > 0;
    document.getElementById("rated-empty").hidden = rated > 0;
  }

  Array.prototype.forEach.call(document.querySelectorAll(".js-open-rate"), function (btn) {
    btn.addEventListener("click", function () {
      currentCard = btn.closest(".rate-card");
      form.reset();
      counterEl.textContent = "0";
      errorEl.hidden = true;
      submitBtn.disabled = false;
      document.getElementById("rate-modal-student").textContent =
        currentCard.querySelector(".rate-student").textContent;
      modal.show();
    });
  });

  form.addEventListener("change", function () {
    errorEl.hidden = true;
  });

  commentEl.addEventListener("input", function () {
    counterEl.textContent = commentEl.value.length;
  });

  modalEl.addEventListener("shown.bs.modal", function () {
    var first = form.querySelector("input[name=stars]");
    if (first) first.focus();
  });

  function markRated(card, stars, comment) {
    card.classList.add("is-rated");
    card.removeAttribute("data-needs-complete");
    var side = card.querySelector(".rate-card-side");
    side.replaceChildren();
    var starsEl = document.createElement("span");
    starsEl.className = "rate-stars";
    starsEl.setAttribute("role", "img");
    starsEl.setAttribute("aria-label", stars + " out of 5 stars");
    for (var i = 1; i <= 5; i++) {
      var s = document.createElement("span");
      s.textContent = "★";
      if (i <= stars) s.className = "on";
      starsEl.appendChild(s);
    }
    side.appendChild(starsEl);
    if (comment) {
      var p = document.createElement("p");
      p.className = "rate-comment";
      p.textContent = comment;
      card.querySelector(".rate-card-main").appendChild(p);
    }
    ratedList.insertBefore(card, ratedList.firstChild);
    updateCounts();
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    errorEl.hidden = true;

    var checked = form.querySelector("input[name=stars]:checked");
    if (!checked) {
      showError("Pick a star rating from 1 to 5.");
      return;
    }
    var stars = parseInt(checked.value, 10);
    var comment = commentEl.value.trim();
    var bookingId = currentCard.dataset.bookingId;
    var needsComplete = currentCard.dataset.needsComplete === "1";

    submitBtn.disabled = true;

    var step = Promise.resolve({ ok: true });
    if (needsComplete) {
      // If the student already completed it, this returns 400; rating still works.
      step = post(urlFor(completeUrl, bookingId));
    }

    step.then(function () {
      var body = new FormData();
      body.append("stars", String(stars));
      body.append("comment", comment);
      return post(urlFor(rateUrl, bookingId), body);
    }).then(function (result) {
      if (!result.ok) {
        showError(result.data.error || "Could not save the rating. Please try again.");
        submitBtn.disabled = false;
        return;
      }
      modal.hide();
      markRated(currentCard, stars, comment);
    }).catch(function () {
      showError("Network problem. Please try again.");
      submitBtn.disabled = false;
    });
  });
})();