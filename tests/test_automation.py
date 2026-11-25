"""Recovery tests for changes to the shared PIM list."""

import unittest
from unittest.mock import Mock, patch

from app.automation import EmployeeListChanged, OrangeHrmPage, run_automation
from app.config import Settings
from app.models import Employee, RunInput


class ExportRecoveryTests(unittest.TestCase):
    employee = Employee("Riley", "Demo", "9001")

    def test_count_change_restarts_only_the_list_read(self) -> None:
        page = Mock()
        site = OrangeHrmPage(page, timeout_ms=1_000)
        output = (["Id"], [["9001"]])
        with (
            patch.object(
                site,
                "read_employee_list",
                side_effect=[EmployeeListChanged("Count changed"), output],
            ) as read,
            self.assertLogs("uvicorn.error.orangehrm"),
        ):
            on_retry = Mock()
            self.assertEqual(
                site.extract_employee_list(self.employee, on_retry), output
            )
        on_retry.assert_called_once()
        self.assertEqual(read.call_count, 2)
        page.reload.assert_called_once_with(wait_until="commit")

    def test_export_only_never_calls_add_employee(self) -> None:
        request = RunInput("user", "password", self.employee, export_only=True)
        with (
            patch("app.automation.sync_playwright"),
            patch("app.automation.launch_browser") as launch,
            patch("app.automation.OrangeHrmPage") as browser_page,
        ):
            site = browser_page.return_value

            def extract(employee, on_retry):
                on_retry()
                return ["Id"], [["9001"]]

            site.extract_employee_list.side_effect = extract
            updates = []
            result = run_automation(request, Settings(), updates.append)
        self.assertTrue(result.successful)
        site.add_employee.assert_not_called()
        self.assertEqual(site.extract_employee_list.call_args.args, (self.employee,))
        self.assertIn(
            "Employee verified. Retrying export…", [u.message for u in updates]
        )
        self.assertEqual(updates[-1].completed, tuple(result.steps))
        site.logout.assert_called_once()
        launch.return_value.close.assert_called_once()

    def test_failed_export_stays_marked_during_sign_out(self) -> None:
        request = RunInput("user", "password", self.employee, export_only=True)
        with (
            patch("app.automation.sync_playwright"),
            patch("app.automation.launch_browser"),
            patch("app.automation.OrangeHrmPage") as browser_page,
            self.assertLogs("uvicorn.error.orangehrm"),
        ):
            browser_page.return_value.extract_employee_list.side_effect = (
                EmployeeListChanged("Count changed")
            )
            updates = []
            result = run_automation(request, Settings(), updates.append)
        sign_out = next(update for update in updates if update.active == "Sign out")
        self.assertEqual(sign_out.failed, "Extract employee list")
        self.assertEqual(result.failed_step, "Extract employee list")
        self.assertIn("Sign out", updates[-1].completed)
