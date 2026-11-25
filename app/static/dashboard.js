const form = document.querySelector("#automation-form");

if (form) {
  const button = form.querySelector("button[type=submit]");
  const buttonLabel = button.textContent;
  const progress = document.querySelector("#run-progress");

  form.addEventListener("submit", (event) => {
    if (button.disabled) {
      event.preventDefault();
      return;
    }
    button.disabled = true;
    button.textContent = "Running automation…";
    progress.textContent = "Keep this tab open while the browser works.";
  });

  window.addEventListener("pageshow", () => {
    button.disabled = false;
    button.textContent = buttonLabel;
    progress.textContent = "";
  });
}
