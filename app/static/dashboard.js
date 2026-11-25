function initializeWorkflow() {
  const form = document.querySelector("#automation-form");
  if (!form) return;

  const panel = document.querySelector(".workflow");
  const rows = [...panel.querySelectorAll("[data-step]")];
  const button = form.querySelector("button[type=submit]");
  const buttonLabel = button.textContent;
  const meter = panel.querySelector("#workflow-bar");
  const count = panel.querySelector("#workflow-count");
  const status = panel.querySelector("#workflow-status");
  const exportOnly = form.hasAttribute("data-export-only");

  function showProgress({ completed, active, failed, message }) {
    let total = 0;
    let finished = 0;
    let activeIndex;
    let activeLabel;
    for (const row of rows) {
      const step = row.dataset.step;
      row.hidden = exportOnly && row.hasAttribute("data-create-only");
      if (row.hidden) continue;

      total += 1;
      const isComplete = completed.includes(step);
      const isActive = step === active;
      if (isComplete) finished += 1;
      row.classList.toggle("completed", isComplete);
      row.classList.toggle("active", isActive);
      row.classList.toggle("failed", step === failed && !isActive);
      if (isActive) {
        row.setAttribute("aria-current", "step");
        activeIndex = total;
        activeLabel = row.dataset.activeText;
      } else {
        row.removeAttribute("aria-current");
      }
    }
    meter.max = total;
    meter.value = finished;
    count.textContent = `${finished} of ${total} steps complete`;
    const summary = message || (activeLabel
      ? `Step ${activeIndex} of ${total} · ${activeLabel}…`
      : failed ? "Finishing after an error…" : "Running automation…");
    if (status.textContent !== summary) status.textContent = summary;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;
    const data = new URLSearchParams(new FormData(form));
    button.disabled = true;
    button.textContent = "Running automation…";
    showProgress({ completed: [], message: "Starting browser…" });

    let running = true;
    let timer;
    async function poll() {
      try {
        const response = await fetch(panel.dataset.progressUrl, { cache: "no-store" });
        if (response.ok && running) showProgress(await response.json());
      } catch {
        // A transient polling error leaves the latest known progress visible.
      }
      if (running) timer = window.setTimeout(poll, 450);
    }
    timer = window.setTimeout(poll, 150);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { "X-Workflow-Id": panel.dataset.workflowId },
        body: data,
      });
      if (response.redirected) {
        window.location.assign(response.url);
        return;
      }

      const page = new DOMParser().parseFromString(await response.text(), "text/html");
      const main = page.querySelector("main");
      if (!main) throw new Error("Missing dashboard response");
      document.querySelector("main").replaceWith(main);
      initializeWorkflow();
      main.querySelector('[role="alert"]')?.scrollIntoView({ block: "nearest" });
    } catch {
      status.textContent =
        "Could not confirm the run result. Check OrangeHRM before starting again.";
      button.disabled = false;
      button.textContent = buttonLabel;
    } finally {
      running = false;
      window.clearTimeout(timer);
    }
  });

  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  }, { once: true });
}

initializeWorkflow();
