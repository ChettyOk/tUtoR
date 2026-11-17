(function () {
  var sections = Array.prototype.slice.call(
    document.querySelectorAll(".profile-section[data-section]")
  );
  var links = Array.prototype.slice.call(
    document.querySelectorAll("[data-profile-section]")
  );
  if (!sections.length || !links.length) return;

  var allowed = { personal: true, password: true, role: true };

  function currentFromUrl() {
    var params = new URLSearchParams(window.location.search);
    var section = params.get("section") || "";
    if (allowed[section]) return section;
    var hash = (window.location.hash || "").replace(/^#/, "");
    if (allowed[hash]) return hash;
    var active = document.querySelector(".profile-section.is-active");
    return active ? active.getAttribute("data-section") : "personal";
  }

  function showSection(section, push) {
    if (!allowed[section]) section = "personal";

    sections.forEach(function (el) {
      var match = el.getAttribute("data-section") === section;
      el.classList.toggle("is-active", match);
      if (match) {
        el.removeAttribute("hidden");
      } else {
        el.setAttribute("hidden", "");
      }
    });

    links.forEach(function (link) {
      var match = link.getAttribute("data-profile-section") === section;
      link.classList.toggle("is-active", match);
      link.setAttribute("aria-pressed", match ? "true" : "false");
    });

    var url = new URL(window.location.href);
    url.searchParams.set("section", section);
    url.hash = "";
    if (push) {
      window.history.pushState({ section: section }, "", url);
    } else {
      window.history.replaceState({ section: section }, "", url);
    }
  }

  links.forEach(function (link) {
    link.addEventListener("click", function () {
      showSection(link.getAttribute("data-profile-section"), true);
    });
  });

  window.addEventListener("popstate", function (event) {
    var section =
      (event.state && event.state.section) || currentFromUrl();
    showSection(section, false);
  });

  showSection(currentFromUrl(), false);
})();
