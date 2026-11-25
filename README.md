# OrangeHRM employee onboarding

A local FastAPI dashboard drives the OrangeHRM public demo through a browser. Enter the demo credentials and a fictional employee’s first name, last name, and ID. One submission opens OrangeHRM, signs in, creates and verifies the employee in PIM, extracts the employee list, and signs out.

The result includes the verified employee, completed steps, a list preview, and a downloadable CSV. A failed run identifies the failing stage. If OrangeHRM may have accepted the save, the result tells you to check PIM before retrying.

## Stack

Python 3.10+, FastAPI, Uvicorn, Jinja2, HTML/CSS, a small amount of vanilla JavaScript, and Playwright for Chromium. Tests use the standard-library `unittest` runner and HTTPX.

## Setup

From the project root in Bash, activate the existing virtual environment. For a fresh checkout, create it first with `python3 -m venv venv`.

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
```

The dashboard can use an existing Google Chrome installation. To install the Playwright-managed browser, run `python -m playwright install chromium`. The dashboard prefers that browser when it is available and tries Google Chrome if the Chromium executable is missing. On Linux, if Chromium reports missing system libraries, use `python -m playwright install --with-deps chromium`.

## Run the dashboard

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

1. Open [the local dashboard](http://127.0.0.1:8000).
2. Enter the demo username and password from the assignment PDF. Use fictional names and an unused employee ID of up to 10 characters.
3. Click **Run automation** and keep the tab open. The **Workflow** panel shows the active browser step and the number of steps completed. If PIM changes during extraction, the panel shows when the export is retrying.
4. Confirm the result displays the verified employee and the **Sign out** step. Use **Download employee CSV** for the full list. To preserve leading zeros in spreadsheet software, import the ID column as text.

If the result says **Employee verified · export incomplete**, enter your demo credentials on that result page and click **Retry export**. The retry reads the PIM list for the employee already recorded in the run.

To change the optional runtime settings:

```bash
cp .env.example .env
set -a
source .env
set +a
```

| Setting | Default | Purpose |
| --- | --- | --- |
| `ORANGEHRM_TIMEOUT_MS` | `20000` | Per-operation browser timeout in milliseconds. Accepts 1000–120000. |
| `ORANGEHRM_HEADLESS` | `true` | Set to `false` to watch the OrangeHRM browser locally. |
| `ORANGEHRM_BROWSER_CHANNEL` | Automatic | Tries Playwright Chromium, then installed Google Chrome if Chromium is missing. Set to `chrome` to select Google Chrome directly. |

Credentials are entered in the dashboard for each run. The optional environment file configures browser behavior.

## Test and capture evidence

```bash
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q app tests
python -m unittest discover -s tests -v
```

The automated suite tests form validation, credential handling, CSRF, run isolation, concurrent submission, failure rendering, safe CSV generation, and the result URL's refresh behavior. It uses a fake workflow and requires no network or browser.

To verify the real site, keep the dashboard running in one terminal and run this command in another:

```bash
python tests/live_dashboard.py --output runtime/live-evidence
# Add --channel chrome if you are using installed Google Chrome.
```

The live check prompts for the demo credentials, submits the actual dashboard form, creates a fictional employee with a generated ID, checks the verified employee and sign-out status, and downloads the CSV. It checks the exact employee row and matches the dashboard's record count to the CSV. It also captures screenshots and checks that refreshing the result page preserves the completed run.

## Project layout

```text
app/
  main.py             FastAPI routes, form handling, and run coordination
  automation.py       Playwright page interactions and workflow
  artifacts.py        Per-run snapshots and CSV serialization
  config.py           Browser settings
  models.py           Form validation and result types
  static/             CSS and progress behavior
  templates/          Server-rendered dashboard
tests/
  test_automation.py  Export recovery and read-only retry tests
  test_browser.py     Browser selection and startup error tests
  test_dashboard.py   Route and workflow boundary tests
  test_models.py      Validation and CSV edge-case tests
  live_dashboard.py   Opt-in live browser test and evidence capture
docs/
  verification.md     PDF checklist, results, and submission checklist
  interview.md        Implementation questions and answers
evidence/             Screenshots and CSV from a live run
.env.example
.gitignore
requirements.txt
requirements-dev.txt
README.md
```

## Implementation decisions

- **Browser lifecycle.** Playwright runs in a thread so FastAPI can serve the dashboard during a run. Every run has a fresh browser context. After signing in, the workflow attempts sign-out even if a later step fails. The context and browser close in cleanup blocks.
- **Readiness and verification.** Actions wait on UI elements and page transitions. After Save, the workflow reads the profile’s three fields and checks them against the request. It then reads rendered PIM columns and pages, checks the displayed total, and verifies that the new employee is present in the extraction.
- **Run state.** A single server process allows one active run at a time. The POST redirects to a result URL so refreshing cannot resubmit the form. The browser’s random cookie scopes access to the run and its CSV. Result snapshots under `runtime/runs/` are written atomically.
- **Data handling.** The submitted credentials are used in memory for sign-in. Snapshots, CSVs, URLs, and application step logs omit them. HTML output is escaped and CSV cells that start like spreadsheet formulas are neutralized. The target URL is fixed in code.

## Known limitations

- The shared demo can change while a list is being read. If the reported count changes, the app restarts the list read from page one, up to three attempts total. If it still cannot complete the export, the verified employee remains on the result page with a read-only retry option. Demo downtime, resets, and UI changes can also affect a run.
- Employee creation is a remote action. If the response is lost after Save, the app cannot safely determine whether to repeat it. Search PIM for the ID first. Use a new ID for each planned run.
- The dashboard is intended for one local Uvicorn worker. Result files stay on disk until you clear `runtime/runs/`. Browser access to a run ends when its session cookie is cleared.

See the [verification and submission checklist](docs/verification.md) and [interview questions](docs/interview.md).
