
(function () {
  "use strict";

  var urls = JSON.parse(document.getElementById("request-form-urls").textContent);
  var form = document.getElementById("request-form");
  var filterInput = document.getElementById("rf-filter");
  var select = document.getElementById("rf-course");
  var description = document.getElementById("rf-description");
  var counter = document.getElementById("rf-counter");
  var notice = document.getElementById("rf-existing");
  var errorEl = document.getElementById("rf-error");
  var submitBtn = document.getElementById("rf-submit");
  var maxLength = description.maxLength;

  // The server says whether tutors already offer the course (blocks the request).
  var courseBlocked = false;

  function showError(message) {
    errorEl.textContent = message || "";
    errorEl.hidden = !message;
  }

  function csrfToken() {
    var input = form.querySelector("[name=csrfmiddlewaretoken]");
    if (input && input.value) return input.value;
    var m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  // ----- course filter -----
  // Keep every option so clearing the filter brings them all back.
  var allOptions = Array.prototype.slice.call(select.options);

  function normalise(text) {
    return text.toLowerCase().replace(/\s+/g, "");
  }

  function applyFilter() {
    var needle = normalise(filterInput.value);
    var chosen = select.value;
    var shown = 0;
    select.innerHTML = "";
    allOptions.forEach(function (opt, i) {
      var keep = i === 0 || opt.value === chosen ||
        !needle || normalise(opt.textContent).indexOf(needle) !== -1;
      if (keep) {
        select.appendChild(opt);
        if (i > 0) shown += 1;
      }
    });
    select.value = chosen;
    select.size = needle && shown > 1 ? Math.min(shown + 1, 8) : 1;
  }

  filterInput.addEventListener("input", applyFilter);

  // ----- "tutors already offer this" check -----
  function checkCourse() {
    courseBlocked = false;
    notice.hidden = true;
    submitBtn.disabled = false;
    if (!select.value) return;

    fetch(urls.form_data + "?course_id=" + encodeURIComponent(select.value), {
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" }
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.open_request_exists) {
          courseBlocked = true;
          submitBtn.disabled = true;
          notice.textContent = "You already have an open request for this course.";
          var mine = document.createElement("a");
          mine.href = urls.after;
          mine.textContent = " See your requests";
          notice.appendChild(mine);
          notice.hidden = false;
        } else if (data.can_create_request === false) {
          courseBlocked = true;
          submitBtn.disabled = true;
          var names = (data.existing_tutors || []).map(function (t) {
            return (t.first_name + " " + t.last_name).trim();
          }).slice(0, 3);
          notice.textContent = "Tutors already offer this course" +
            (names.length ? " (" + names.join(", ") + ")" : "") +
            ". Search for them instead of posting a request.";
          var link = document.createElement("a");
          link.href = urls.find + "?q=" + encodeURIComponent(
            select.options[select.selectedIndex].textContent.split(" · ")[0]);
          link.textContent = " Find tutors";
          notice.appendChild(link);
          notice.hidden = false;
        }
      })
      .catch(function () { /* the server checks again on submit */ });
  }

  select.addEventListener("change", checkCourse);

  // ----- description counter -----
  description.addEventListener("input", function () {
    counter.textContent = description.value.length + " / " + maxLength;
  });

  // ----- submit -----
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    showError("");

    if (!select.value) { showError("Choose a course first."); return; }
    if (courseBlocked) { return; }
    if (!description.value.trim()) {
      showError("Describe what you need help with.");
      return;
    }

    var fd = new FormData();
    fd.append("course_id", select.value);
    fd.append("description", description.value.trim());
    fd.append("location_type", form.querySelector("[name=location_type]:checked").value);

    submitBtn.disabled = true;
    var label = submitBtn.textContent;
    submitBtn.textContent = "Posting…";

    fetch(urls.create, {
      method: "POST",
      headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: fd
    })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (r) {
        if (r.status === 201) {
          window.location.href = urls.after;
          return;
        }
        submitBtn.disabled = false;
        submitBtn.textContent = label;
        showError(r.body.error || "Something went wrong. Please try again.");
      })
      .catch(function () {
        submitBtn.disabled = false;
        submitBtn.textContent = label;
        showError("Couldn't reach the server. Check your connection and try again.");
      });
  });

  applyFilter();
  checkCourse();
  description.dispatchEvent(new Event("input"));
})();