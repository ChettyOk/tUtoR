/* Code for client-side validation, show/hide password, double-submit guard.*/

(function () {
  "use strict";

  // Show / hide password buttons
  document.querySelectorAll("[data-toggle-password]").forEach(function (button) {
    var input = document.querySelector(button.getAttribute("data-toggle-password"));
    if (!input) return;
    button.addEventListener("click", function () {
      var reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      button.textContent = reveal ? "Hide" : "Show";
      button.setAttribute("aria-pressed", reveal ? "true" : "false");
    });
  });

  // "Confirm password" must match the first password field
  document.querySelectorAll("[data-match]").forEach(function (confirm) {
    var original = document.querySelector(confirm.getAttribute("data-match"));
    var feedback = confirm.parentElement.querySelector(".invalid-feedback");
    if (!original) return;
    var defaultMessage = feedback ? feedback.textContent.trim() : "";
    var mismatchMessage = confirm.getAttribute("data-mismatch") || "Values do not match.";

    function check() {
      var mismatch = confirm.value !== "" && confirm.value !== original.value;
      confirm.setCustomValidity(mismatch ? mismatchMessage : "");
      if (feedback && mismatch) feedback.textContent = mismatchMessage;
      if (feedback && !mismatch) feedback.textContent = defaultMessage;
    }
    confirm.addEventListener("input", check);
    original.addEventListener("input", check);
  });

  // Clear an error sent by the server as soon as the person edits that field
  document.querySelectorAll("input.is-invalid").forEach(function (input) {
    input.addEventListener("input", function () {
      input.classList.remove("is-invalid");
    });
  });

  // Validate on submit, then stop double clicks from sending the form twice
  document.querySelectorAll("form.needs-validation").forEach(function (form) {
    var submit = form.querySelector("[type=submit]");
    var submitLabel = submit ? submit.textContent : "";

    form.addEventListener("submit", function (event) {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
        form.classList.add("was-validated");
        var firstInvalid = form.querySelector(":invalid");
        if (firstInvalid) firstInvalid.focus();
        return;
      }
      if (submit) {
        submit.disabled = true;
        submit.textContent = submit.getAttribute("data-loading") || "Please wait…";
      }
    });

    // Coming back with the browser's Back button must not leave the button disabled
    window.addEventListener("pageshow", function (event) {
      if (event.persisted && submit) {
        submit.disabled = false;
        submit.textContent = submitLabel;
      }
    });
  });
})();