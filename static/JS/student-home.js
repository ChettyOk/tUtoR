(function () {
  "use strict";

  function csrfToken() {
    var input = document.querySelector("[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function setFavoriteState(button, isFavorite) {
    button.classList.toggle("is-active", isFavorite);
    button.setAttribute("aria-pressed", isFavorite ? "true" : "false");
    button.textContent = isFavorite ? "Favourited" : "Favourite";
    var card = button.closest("[data-tutor-id]");
    if (card) {
      card.setAttribute("data-is-favorite", isFavorite ? "true" : "false");
    }
  }

  document.querySelectorAll("[data-favorite-toggle]").forEach(function (button) {
    var card = button.closest("[data-tutor-id]");
    if (card) {
      card.setAttribute(
        "data-is-favorite",
        button.classList.contains("is-active") ? "true" : "false"
      );
    }

    button.addEventListener("click", function () {
      if (button.disabled) return;
      var url = button.getAttribute("data-toggle-url");
      if (!url) return;

      button.disabled = true;
      fetch(url, {
        method: "POST",
        headers: {
          "X-CSRFToken": csrfToken(),
          Accept: "application/json",
        },
        credentials: "same-origin",
      })
        .then(function (response) {
          return response.json().then(function (data) {
            return { ok: response.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            throw new Error(result.data.error || "Could not update favourite.");
          }
          setFavoriteState(button, !!result.data.is_favorite);
        })
        .catch(function () {
          // Keep the previous state; the next click can retry.
        })
        .finally(function () {
          button.disabled = false;
        });
    });
  });
})();
