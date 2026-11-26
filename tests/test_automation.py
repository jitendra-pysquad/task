"""Recovery tests for changes to the shared PIM list."""

import unittest
from unittest.mock import Mock, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.automation import (
    EMPLOYEE_LIST_URL,
    DuplicateEmployeeId,
    EmployeeListChanged,
    OrangeHrmPage,
    WorkflowError,
    request_english_ui,
    run_automation,
)
from app.config import Settings
from app.models import Employee, RunInput


class SignInTests(unittest.TestCase):
    def test_browser_requests_english_without_losing_other_parameters(self) -> None:
        route = Mock()
        base_url = "https://opensource-demo.orangehrmlive.com/web/index.php"
        route.request.url = f"{base_url}/core/i18n/messages?locale=fr_FR&version=1"
        request_english_ui(route)
        route.continue_.assert_called_once_with(
            url=f"{base_url}/core/i18n/messages?locale=en_US&version=1"
        )

    def test_slow_sign_in_submits_once_and_waits_for_a_visible_outcome(self) -> None:
        page = Mock()
        site = OrangeHrmPage(page, timeout_ms=20_000)
        outcome = site.user_menu.or_.return_value.filter.return_value.or_.return_value
        outcome.first.wait_for.side_effect = PlaywrightTimeoutError("Timed out")
        request = RunInput("user", "test-password", Employee("Riley", "Demo", "9001"))

        with (
            self.assertLogs("uvicorn.error.orangehrm") as logs,
            self.assertRaisesRegex(WorkflowError, "took too long to respond"),
        ):
            site.login(request)

        page.locator.return_value.filter.return_value.locator.assert_called_once_with(
            'button[type="submit"]'
        )
        submit = page.locator.return_value.filter.return_value.locator.return_value
        submit.click.assert_called_once_with(no_wait_after=True)
        outcome.first.wait_for.assert_called_once_with(timeout=40_000)
        self.assertIn("waiting for the sign-in response", logs.output[0])
        self.assertNotIn("test-password", logs.output[0])


class PimNavigationTests(unittest.TestCase):
    def test_pim_navigation_uses_the_link_destination_instead_of_its_label(
        self,
    ) -> None:
        page = Mock()
        site = OrangeHrmPage(page, timeout_ms=20_000)

        site.open_pim()

        page.locator.assert_any_call('a[href$="/pim/viewPimModule"]')
        site.pim.click.assert_called_once_with(no_wait_after=True)
        page.wait_for_url.assert_called_once_with(
            EMPLOYEE_LIST_URL, wait_until="commit"
        )


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

    def test_duplicate_id_is_reported_as_a_correctable_add_employee_error(self) -> None:
        request = RunInput("user", "password", self.employee)
        settings = Settings()
        with (
            patch("app.automation.sync_playwright"),
            patch("app.automation.launch_browser"),
            patch("app.automation.OrangeHrmPage") as browser_page,
            self.assertLogs("uvicorn.error.orangehrm"),
        ):
            site = browser_page.return_value
            site.save_attempted = False
            site.add_employee.side_effect = DuplicateEmployeeId("ID already in use.")
            result = run_automation(request, settings)
        self.assertTrue(result.duplicate_employee_id)
        self.assertEqual(result.failed_step, "Add employee")
        self.assertIsNone(result.employee)
        site.verify_employee.assert_not_called()
        site.logout.assert_called_once()
