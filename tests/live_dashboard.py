"""Run the dashboard in Chromium against the public demo and capture evidence."""

import argparse
import csv
import getpass
import re
import sys
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--channel", help="Installed Chromium channel, e.g. chrome")
    parser.add_argument("--output", type=Path, default=Path("evidence"))
    parser.add_argument("--employee-id", default=f"RPA{uuid4().hex[:7].upper()}")
    options = parser.parse_args()
    username = input("OrangeHRM demo username: ")
    password = (
        getpass.getpass("OrangeHRM demo password: ")
        if sys.stdin.isatty()
        else input("OrangeHRM demo password: ")
    )
    first_name, last_name = "Riley", "Demo"
    options.output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=options.channel)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(options.url)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.locator("body").evaluate("(body) => body.scrollWidth") <= 390
        page.set_viewport_size({"width": 1440, "height": 1000})
        expect(page.get_by_role("button", name="Run automation")).to_be_visible()
        page.screenshot(path=options.output / "dashboard-before.png", full_page=True)
        for label, value in (
            ("Username", username),
            ("Password", password),
            ("First name", first_name),
            ("Last name", last_name),
            ("Employee ID", options.employee_id),
        ):
            page.get_by_label(label, exact=True).fill(value)

        page.get_by_role("button", name="Run automation").click(no_wait_after=True)
        result = page.locator(".result-body")
        result.wait_for(timeout=360_000)
        if result.get_by_role("alert").count():
            page.screenshot(
                path=options.output / "dashboard-failure.png", full_page=True
            )
            raise RuntimeError(result.inner_text())
        expect(result.get_by_role("status")).to_have_text(
            "Automation completed successfully"
        )
        for value in (options.employee_id, first_name, last_name):
            expect(result.get_by_text(value, exact=True)).to_be_visible()
        expect(page.get_by_text("Sign out", exact=True)).to_have_class("completed")
        with page.expect_download() as pending:
            page.get_by_role("link", name="Download employee CSV").click()
        csv_path = options.output / "employees.csv"
        pending.value.save_as(csv_path)

        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        matched = [row for row in rows if row["Id"] == options.employee_id]
        assert len(matched) == 1, matched
        assert matched[0]["First (& Middle) Name"] == first_name, matched
        assert matched[0]["Last Name"] == last_name, matched
        expect(
            page.get_by_text(re.compile(rf"{len(rows)} records extracted"))
        ).to_be_visible()
        page.screenshot(path=options.output / "dashboard-after.png", full_page=True)

        # Refresh the result URL and verify this does not replay the POST.
        page.reload()
        expect(page.get_by_text("Automation completed successfully")).to_be_visible()
        browser.close()

    print(f"Verified employee {options.employee_id} and {len(rows)} CSV records.")
    print(f"Saved dashboard evidence in {options.output}.")


if __name__ == "__main__":
    main()
