# Assessment verification

Both pages of the assignment PDF were reviewed. The PDF contains the written requirements and deliverables. It requests screenshots of the completed dashboard and gives the public demo credentials for the person running it.

| PDF requirement | Implementation and verification |
| --- | --- |
| Dashboard built with HTML/CSS and an allowed backend | FastAPI serves the Jinja2 HTML template, CSS, and optional progress script. |
| Login credentials entered in the dashboard | Username and masked password inputs submit to the local server. The Playwright run uses the supplied values. Tests check that credentials are absent from stored results. |
| First name, last name, and employee ID entered in the dashboard | Required controls and server-side field validation. Tests cover missing, oversized, and Unicode values and preserve leading zeros in IDs. |
| A submit button triggers and controls the automation | **Run automation** submits the form. The server validates it and starts one isolated browser run. |
| Open the OrangeHRM demo and log in | Playwright navigates to the fixed demo URL and waits for authenticated navigation. |
| Navigate to PIM | The workflow opens PIM from the authenticated navigation and waits for the employee submenu. |
| Create an employee using submitted values | The Add Employee form receives exactly the validated first name, last name, and ID. |
| Verify creation | The saved Personal Details view must match all three values. The workflow also checks the exact employee against the extracted list. |
| Extract employee list data | The browser reads rendered PIM rows across pages, omits the checkbox and action columns, and checks the total. |
| Log out | The workflow opens the user menu, signs out, and waits for the login page. Browser cleanup runs on failure as well. |
| Display inserted details and success/failure | The dashboard shows verified details, completion status, completed steps, and actionable errors. Tests cover both result states. |
| Optionally display the extracted table | The dashboard previews up to eight rows. The CSV contains the full extraction. |
| Use Python browser automation, explicit waits, exception handling, and per-step logs | Playwright automates the web UI. Bounded waits, error handling, browser cleanup, and Uvicorn logs are in `app/automation.py`. |
| Provide source code, UI files, and the automation script | The source ZIP contains the Python application, HTML/CSS, JavaScript, setup files, tests, and documentation. |
| Provide before and after screenshots and a CSV or Excel file | The ZIP includes the live artifacts under `evidence/`. |

## Recorded results

Verified on 25 November 2026 using Python 3.10.12 and installed Google Chrome in headless mode. The live dashboard created **Riley Demo** with ID **RPA8DAD678**, matched its three fields in the saved profile and extracted list, and showed all seven workflow steps complete after sign-out. PIM reported **144 records across three pages** (50, 50, and 44). The downloaded CSV contains 144 records and the exact employee row once. Refreshing the dashboard result reloaded the existing run.

- [Before execution](../evidence/dashboard-before.png)
- [After successful execution](../evidence/dashboard-after.png)
- [Downloaded employee CSV](../evidence/employees.csv)

All 13 offline tests passed after adding browser startup coverage. A separate live check verified that the dashboard's browser launcher opened the OrangeHRM login page using installed Google Chrome when Playwright Chromium was missing. Earlier live iterations exposed the demo's counter whitespace and duplicate IDs already present in PIM. Those issues were corrected before the successful run. The earlier runs also saved fictional employees to the shared demo.

All 17 offline tests passed. A browser test checked the live step, progress count, retry message, completion, and mobile layout using controlled step timing. A separate read-only OrangeHRM run detected a change from 83 to 84 PIM records, restarted the list read, verified the existing employee in the 84-row export, and signed out.

## Submission checklist

- [ ] Read the [README](../README.md) and practice the workflow using a unique fictional ID.
- [x] Verify the source archive and the three evidence files.
- [ ] Submit the ZIP through the employer’s chosen channel.
