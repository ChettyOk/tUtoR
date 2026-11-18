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
  var clearFilterBtn = document.querySelector("[data-clear-favorites-filter]");
  var statusEl = document.querySelector("[data-favorite-status]");
  var items = Array.prototype.slice.call(
    document.querySelectorAll("[data-tutor-item]")
  );

  function favoritesOnly() {
    return !!(filterInput && filterInput.checked);
  }

  function syncFilterUrl(onlyFavorites) {
    var url = new URL(window.location.href);
    if (onlyFavorites) {
      url.searchParams.set("favorites", "1");
    } else {
      url.searchParams.delete("favorites");
    }
    window.history.replaceState({}, "", url);
  }

  function announce(message) {
    if (statusEl) statusEl.textContent = message;
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
        visible +
        " tutor" +
        (visible === 1 ? "" : "s") +
        (onlyFavorites ? " favourited" : "");
    }

    if (emptyEl) {
      emptyEl.hidden = !(onlyFavorites && visible === 0);
    }

    if (listRoot) {
      listRoot.classList.toggle("is-filtering-favorites", onlyFavorites);
    }

    syncFilterUrl(onlyFavorites);
  }

  function setFavoriteState(button, isFavorite) {
    var label = button.querySelector("[data-favorite-label]");
    button.classList.toggle("is-active", isFavorite);
    button.setAttribute("aria-pressed", isFavorite ? "true" : "false");
    button.setAttribute(
      "aria-label",
      isFavorite ? "Remove from favourites" : "Add to favourites"
    );
    if (label) {
      label.textContent = isFavorite ? "Favourited" : "Favourite";
    } else {
      button.textContent = isFavorite ? "Favourited" : "Favourite";
    }

    var item = button.closest("[data-tutor-item]");
    if (item) {
      item.setAttribute("data-is-favorite", isFavorite ? "true" : "false");
      item.classList.toggle("is-favorite", isFavorite);
    }

    var card = button.closest(".tutor-card");
    if (card) {
      card.classList.toggle("is-favorite", isFavorite);
    }

    announce(isFavorite ? "Added to favourites." : "Removed from favourites.");
    applyFavoritesFilter();
  }

  document.querySelectorAll("[data-favorite-toggle]").forEach(function (button) {
    var item = button.closest("[data-tutor-item]");
    var isFavorite = button.classList.contains("is-active");
    if (item) {
      item.setAttribute("data-is-favorite", isFavorite ? "true" : "false");
      item.classList.toggle("is-favorite", isFavorite);
    }
    var card = button.closest(".tutor-card");
    if (card) {
      card.classList.toggle("is-favorite", isFavorite);
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
          announce("Could not update favourite. Try again.");
        })
        .finally(function () {
          button.disabled = false;
        });
    });
  });

  if (filterInput) {
    var params = new URLSearchParams(window.location.search);
    if (params.get("favorites") === "1") {
      filterInput.checked = true;
    }
    filterInput.addEventListener("change", applyFavoritesFilter);
  }

  if (clearFilterBtn && filterInput) {
    clearFilterBtn.addEventListener("click", function () {
      filterInput.checked = false;
      applyFavoritesFilter();
      filterInput.focus();
    });
  }

  if (listRoot) {
    applyFavoritesFilter();
  }
})();
