/* Course picker for the personalisation page.
   Reads the course list from the page, filters it in the browser, and sends the chosen
   course ids back as hidden "courses" inputs. The server will check everything again. */
(function () {
  "use strict";

  var form = document.getElementById("course-picker");
  if (!form) return;

  var courses = JSON.parse(document.getElementById("course-data").textContent);
  var initialIds = JSON.parse(document.getElementById("selected-data").textContent);
  var maxCourses = parseInt(form.getAttribute("data-max"), 10);
  var hasMax = !isNaN(maxCourses);   // no limit for tutors
  var PAGE_SIZE = 20;

  var searchInput = document.getElementById("picker-search");
  var facultySelect = document.getElementById("picker-faculty");
  var resultsList = document.getElementById("picker-results");
  var moreButton = document.getElementById("picker-more");
  var statusLine = document.getElementById("picker-status");
  var selectedList = document.getElementById("picker-selected");
  var emptyNote = document.getElementById("picker-empty");
  var countLabel = document.getElementById("picker-count");
  var jumpCount = document.getElementById("picker-jump-count");
  var limitNote = document.getElementById("picker-limit");
  var hiddenInputs = document.getElementById("picker-inputs");
  var nextButton = document.getElementById("picker-next");

  var byId = {};
  courses.forEach(function (course) {
    // Searchable words: the code like "cs"or "110",the code without a space "cs110" and the course name
    course._flatCode = course.course_code.replace(/\s+/g, "").toLowerCase();
    course._words = (course.course_code + " " + course._flatCode + " " + course.course_name)
      .toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
    byId[course.id] = course;
  });

  var selected = [];
  initialIds.forEach(function (id) {
    if (byId[id] && selected.indexOf(id) === -1) selected.push(id);
  });
  if (hasMax && selected.length > maxCourses) selected = selected.slice(0, maxCourses);

  var shown = PAGE_SIZE;

  function prettyFaculty(name) {
    if (!name) return "Other";
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  // Faculty dropdown
  var faculties = [];
  courses.forEach(function (course) {
    if (faculties.indexOf(course.course_faculty) === -1) faculties.push(course.course_faculty);
  });
  faculties.sort();
  faculties.forEach(function (name) {
    var option = document.createElement("option");
    option.value = name;
    option.textContent = prettyFaculty(name);
    facultySelect.appendChild(option);
  });

  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;   
    return node;
  }

  function atLimit() {
    return hasMax && selected.length >= maxCourses;
  }

  function buildCard(course, inSelectedList) {
    var item = make("li", "course-card" + (inSelectedList ? " is-selected" : ""));
    var info = make("div", "course-info");
    info.appendChild(make("strong", "course-code", course.course_code));
    info.appendChild(make("span", "course-name", course.course_name));
    info.appendChild(make("span", "course-faculty", prettyFaculty(course.course_faculty)));

    var button = make("button");
    button.type = "button";
    if (inSelectedList) {
      button.className = "btn-remove";
      button.textContent = "×";
      button.setAttribute("data-remove", course.id);
      button.setAttribute("aria-label", "Remove " + course.course_code);
    } else {
      var isSelected = selected.indexOf(course.id) !== -1;
      button.className = "btn-add";
      button.textContent = isSelected ? "Added" : "Add";
      button.disabled = isSelected || atLimit();
      button.setAttribute("data-add", course.id);
      button.setAttribute("aria-label", (isSelected ? "Already added: " : "Add ") + course.course_code);
    }
    item.appendChild(info);
    item.appendChild(button);
    return item;
  }

  
  function startsAWord(course, token) {
    return course._words.some(function (word) { return word.indexOf(token) === 0; });
  }

  
  function currentMatches() {
    var tokens = searchInput.value.toLowerCase().split(/\s+/).filter(Boolean);
    var faculty = facultySelect.value;
    if (!tokens.length && !faculty) return null;

    var matches = courses.filter(function (course) {
      if (faculty && course.course_faculty !== faculty) return false;
      return tokens.every(function (token) { return startsAWord(course, token); });
    });

    
    var typed = tokens.join("");
    if (typed) {
      var rank = function (course) {
        if (course._flatCode === typed) return 0;
        if (course._flatCode.indexOf(typed) === 0) return 1;
        return 2;
      };
      matches.sort(function (a, b) { return rank(a) - rank(b); });   
    }
    return matches;
  }

  function renderResults() {
    var matches = currentMatches();
    resultsList.textContent = "";
    moreButton.hidden = true;

    if (!courses.length) {
      statusLine.textContent = "No courses are available yet.";
      return;
    }
    if (matches === null) {
      statusLine.textContent = "Type a course code or name, for example “CS 110” or “calculus”. " + courses.length + " courses available.";
      return;
    }
    if (!matches.length) {
      statusLine.textContent = "No courses match your search.";
      return;
    }

    var visible = matches.slice(0, shown);
    visible.forEach(function (course) {
      resultsList.appendChild(buildCard(course, false));
    });
    statusLine.textContent = "Showing " + visible.length + " of " + matches.length + (matches.length === 1 ? " match." : " matches.");
    moreButton.hidden = visible.length >= matches.length;
  }

  function renderSelected() {
    selectedList.textContent = "";
    selected.forEach(function (id) {
      selectedList.appendChild(buildCard(byId[id], true));
    });
    emptyNote.hidden = selected.length > 0;
    countLabel.textContent = hasMax ? selected.length + " / " + maxCourses : selected.length + " selected";
    jumpCount.textContent = selected.length;
    if (limitNote) limitNote.hidden = !atLimit();
    nextButton.disabled = selected.length === 0;

    // The hidden inputs gets sent to the server
    hiddenInputs.textContent = "";
    selected.forEach(function (id) {
      var input = make("input");
      input.type = "hidden";
      input.name = "courses";
      input.value = id;
      hiddenInputs.appendChild(input);
    });
  }

  function refreshSearch() {
    shown = PAGE_SIZE;
    renderResults();
  }

  searchInput.addEventListener("input", refreshSearch);
  facultySelect.addEventListener("change", refreshSearch);
  searchInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") event.preventDefault();   // Enter will not submit the form
  });

  moreButton.addEventListener("click", function () {
    shown += PAGE_SIZE;
    renderResults();
  });

  resultsList.addEventListener("click", function (event) {
    var button = event.target.closest("[data-add]");
    if (!button || button.disabled) return;
    var id = Number(button.getAttribute("data-add"));
    if (selected.indexOf(id) !== -1 || atLimit()) return;
    selected.push(id);
    renderSelected();
    renderResults();
    if (event.detail === 0) searchInput.focus();   
  });

  selectedList.addEventListener("click", function (event) {
    var button = event.target.closest("[data-remove]");
    if (!button) return;
    var id = Number(button.getAttribute("data-remove"));
    selected = selected.filter(function (other) { return other !== id; });
    renderSelected();
    renderResults();
    if (event.detail === 0) searchInput.focus();
  });

  renderSelected();
  renderResults();
})();
