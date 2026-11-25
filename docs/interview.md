# Interview questions

**Why use FastAPI for a server-rendered dashboard?**

FastAPI handles the HTML form and file response alongside the static assets. Jinja2 keeps input and result rendering on the server. The small JavaScript file gives users immediate feedback while automation runs. The form also works with JavaScript disabled.

**How does the application stay responsive with synchronous Playwright?**

The POST handler parses and validates the form, then moves the synchronous workflow into a worker thread. Other requests can still load pages and download previous exports. A process-wide lock rejects overlapping runs with HTTP 409.

**How do you know Save actually created the employee?**

The workflow waits for the Personal Details page, then compares the persisted first name, last name, and employee ID with the requested values. It also checks that the exact employee appears in the unfiltered PIM extraction. A success message requires the extraction and sign-out to finish as well.

**How do you avoid extracting stale rows when you change pages?**

The app reads the current table text, clicks the next-page control, and waits for the rendered page to change. It checks row shapes on each page and compares the aggregate count to the total displayed in PIM. Rows with duplicate IDs are preserved because the demo already contains them.

**What happens when the browser fails after Save?**

The result reports that the save may have reached OrangeHRM if the profile could not be verified. The workflow attempts sign-out and closes the browser. The operator searches for that employee ID before deciding whether to submit again.

**How do you protect credentials and exports?**

Credentials travel in the local POST body and are used to fill the fixed demo site's login form. Snapshots store completed steps, errors, and employee data. A random browser cookie and a matching form token protect submissions and scope access to downloads. CSV cells are escaped by the standard writer and formula-like values are prefixed with an apostrophe.

**Why not use a queue or a database?**

The assignment covers one browser task started from a local dashboard. A worker thread and a non-blocking lock handle this workload, and atomic file writes support result refresh and CSV download. A queue and shared storage would become relevant if runs had to survive server restarts or span multiple workers.

**What is covered by the offline tests and what does the live test add?**

Offline tests verify the application boundary, including validation, results, downloads, isolation, and concurrency. The live test exercises the actual browser selectors, remote employee creation, logout, CSV content, and evidence capture.
