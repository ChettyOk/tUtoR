(function () {
  "use strict";

  function csrfToken() {
    var input = document.querySelector("[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  var listRoot = document.querySelector("[data-tutor-list]");
  var filterInput = document.querySelector("[data-favorites-filter]");
  var countEl = document.querySelector("[data-tutor-count]");
  var emptyEl = document.querySelector("[data-favorites-empty]");
  var items = Array.prototype.slice.call(
    document.querySelectorAll("[data-tutor-item]")
  );

  function favoritesOnly() {
    return !!(filterInput && filterInput.checked);
  }

  function applyFavoritesFilter() {
    if (!items.length) return;

    var onlyFavorites = favoritesOnly();
    var visible = 0;

    items.forEach(function (item) {
      var isFavorite = item.getAttribute("data-is-favorite") === "true";
      var show = !onlyFavorites || isFavorite;
      item.hidden = !show;
      if (show) visible += 1;
    });

    if (countEl) {
      countEl.textContent =
        visible + " tutor" + (visible === 1 ? "" : "s") +
        (onlyFavorites ? " favourited" : "");
    }

    if (emptyEl) {
      emptyEl.hidden = !(onlyFavorites && visible === 0);
    }
  }

  function setFavoriteState(button, isFavorite) {
    button.classList.toggle("is-active", isFavorite);
    button.setAttribute("aria-pressed", isFavorite ? "true" : "false");
    button.textContent = isFavorite ? "Favourited" : "Favourite";

    var item = button.closest("[data-tutor-item]");
    if (item) {
      item.setAttribute("data-is-favorite", isFavorite ? "true" : "false");
    }

    var card = button.closest("[data-tutor-id]");
    if (card) {
      card.setAttribute("data-is-favorite", isFavorite ? "true" : "false");
    }

    applyFavoritesFilter();
  }

  document.querySelectorAll("[data-favorite-toggle]").forEach(function (button) {
    var item = button.closest("[data-tutor-item]");
    if (item && !item.hasAttribute("data-is-favorite")) {
      item.setAttribute(
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

  if (filterInput) {
    filterInput.addEventListener("change", applyFavoritesFilter);
  }

  if (listRoot) {
    applyFavoritesFilter();
  }
})();
