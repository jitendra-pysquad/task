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
            self.assertEqual(site.extract_employee_list(self.employee), output)
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
            site.extract_employee_list.return_value = (["Id"], [["9001"]])
            result = run_automation(request, Settings())
        self.assertTrue(result.successful)
        site.add_employee.assert_not_called()
        site.extract_employee_list.assert_called_once_with(self.employee)
        site.logout.assert_called_once()
        launch.return_value.close.assert_called_once()
