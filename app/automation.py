import logging
import re
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit

from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    Route,
    expect,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .config import DEMO_URL, Settings
from .models import Employee, ProgressCallback, RunInput, RunResult, WorkflowProgress

LOGGER = logging.getLogger("uvicorn.error.orangehrm")
PROFILE_URL = re.compile(r"/pim/viewPersonalDetails/empNumber/\d+(?:[/?#]|$)")
EMPLOYEE_LIST_URL = re.compile(r"/pim/viewEmployeeList(?:[/?#]|$)")
RECORDS_FOUND = re.compile(r"^\((\d+)\) Records? Found$")
EMPLOYEE_COLUMNS = ("Id", "First (& Middle) Name", "Last Name")
EXPORT_ATTEMPTS = 3
TRANSLATIONS_URL = re.compile(
    rf"^{re.escape(DEMO_URL)}/web/index\.php/core/i18n/messages(?:\?|$)"
)


def request_english_ui(route: Route) -> None:
    """Use OrangeHRM's locale parameter for this browser's UI labels."""
    url = urlsplit(route.request.url)
    query = dict(parse_qsl(url.query, keep_blank_values=True))
    query["locale"] = "en_US"
    route.continue_(url=url._replace(query=urlencode(query)).geturl())


class WorkflowError(Exception):
    """An expected workflow failure with a dashboard-safe explanation."""


class LoginRejected(WorkflowError):
    """OrangeHRM displayed a sign-in error."""


class DuplicateEmployeeId(WorkflowError):
    """OrangeHRM rejected an employee ID already in use."""


class EmployeeListChanged(WorkflowError):
    """The employee count changed while reading the shared demo."""


class OrangeHrmPage:
    """Keep OrangeHRM-specific browser interactions and selectors together."""

    def __init__(self, page: Page, timeout_ms: int) -> None:
        self.page = page
        self.timeout_ms = timeout_ms
        page.set_default_timeout(timeout_ms)
        page.route(TRANSLATIONS_URL, request_english_ui)
        self.pim = page.locator('a[href$="/pim/viewPimModule"]')
        self.user_menu = page.locator(".oxd-userdropdown-tab")
        self.username = page.locator('input[name="username"]')
        self.first_name = page.locator('input[name="firstName"]')
        self.last_name = page.locator('input[name="lastName"]')
        self.employee_id = (
            page.locator(".oxd-input-group")
            .filter(has=page.get_by_text("Employee Id", exact=True))
            .get_by_role("textbox")
        )
        self.save_attempted = False

    def open(self) -> None:
        response = self.page.goto(DEMO_URL, wait_until="commit")
        if response is None or not response.ok:
            raise WorkflowError("OrangeHRM returned an error opening the login page.")
        if urlsplit(self.page.url).netloc != urlsplit(DEMO_URL).netloc:
            raise WorkflowError("OrangeHRM redirected away from the demo site.")
        self.username.wait_for()

    def login(self, request: RunInput) -> None:
        pending = "preparing the login form"
        form = self.page.locator("form").filter(has=self.username)
        error = self.page.locator(".oxd-alert-content-text").filter(visible=True)
        signed_in = self.user_menu.or_(self.pim).filter(visible=True)
        try:
            self.username.fill(request.username)
            self.page.locator('input[name="password"]').fill(request.password)
            pending = "submitting the login form"
            form.locator('button[type="submit"]').click(no_wait_after=True)
            pending = "waiting for the sign-in response"
            # Give the post-login redirect and UI render time to finish after one click.
            signed_in.or_(error).first.wait_for(timeout=self.timeout_ms * 2)
        except PlaywrightTimeoutError as exc:
            LOGGER.warning("OrangeHRM timed out while %s", pending)
            raise WorkflowError(
                "OrangeHRM took too long to respond during sign-in. Try again."
            ) from exc
        if error.is_visible():
            raise LoginRejected(
                "Invalid username or password, Please check your credentials "
                "and try again"
            )

    def open_pim(self) -> None:
        try:
            self.pim.click(no_wait_after=True)
            self.page.wait_for_url(EMPLOYEE_LIST_URL, wait_until="commit")
        except PlaywrightTimeoutError as exc:
            raise WorkflowError(
                "OrangeHRM did not open the PIM employee list in time. Try again."
            ) from exc

    def add_employee(self, employee: Employee) -> None:
        self.page.get_by_role("link", name="Add Employee", exact=True).click()
        self.first_name.fill(employee.first_name)
        self.last_name.fill(employee.last_name)
        self.employee_id.fill(employee.employee_id)
        self.save_attempted = True
        self.page.get_by_role("button", name="Save", exact=True).click()
        heading = self.page.get_by_role("heading", name="Personal Details", exact=True)
        field_error = self.page.locator(".oxd-input-field-error-message")
        heading.or_(field_error).first.wait_for()
        if field_error.first.is_visible() and not heading.is_visible():
            self.save_attempted = False
            if field_error.filter(has_text=re.compile(r"already exists", re.I)).count():
                raise DuplicateEmployeeId(
                    "That employee ID already exists. Use a unique ID."
                )
            raise WorkflowError(
                "OrangeHRM rejected the employee form. Check the details."
            )
        self.page.wait_for_url(PROFILE_URL)

    def verify_employee(self, employee: Employee) -> Employee:
        for control, expected in (
            (self.first_name, employee.first_name),
            (self.last_name, employee.last_name),
            (self.employee_id, employee.employee_id),
        ):
            expect(control).to_have_value(expected, timeout=self.timeout_ms)
        return Employee(
            self.first_name.input_value(),
            self.last_name.input_value(),
            self.employee_id.input_value(),
        )

    def extract_employee_list(
        self, employee: Employee, on_retry: Callable[[], None] | None = None
    ) -> tuple[list[str], list[list[str]]]:
        self.page.get_by_role("link", name="Employee List", exact=True).click()
        for attempt in range(1, EXPORT_ATTEMPTS):
            try:
                return self.read_employee_list(employee)
            except EmployeeListChanged as error:
                LOGGER.warning(
                    "PIM export attempt %d of %d discarded (%s)",
                    attempt,
                    EXPORT_ATTEMPTS,
                    error,
                )
                if on_retry:
                    on_retry()
                self.page.reload(wait_until="commit")
        return self.read_employee_list(employee)

    def read_employee_list(
        self, employee: Employee
    ) -> tuple[list[str], list[list[str]]]:
        cards = self.page.locator(".oxd-table-body .oxd-table-card [role='row']")
        cards.first.wait_for()
        counter = self.page.get_by_text(re.compile(r"Records? Found"))
        match = RECORDS_FOUND.fullmatch(" ".join(counter.inner_text().split()))
        if match is None:
            raise WorkflowError("The employee list record count could not be read.")
        expected_count = int(match[1])

        LOGGER.info("Employee list reports %d records", expected_count)
        headers = self.page.locator(".oxd-table-header [role='columnheader']")
        headers.first.wait_for()
        all_columns = [text.strip() for text in headers.all_inner_texts()]
        indexes = [
            index
            for index, column in enumerate(all_columns)
            if column and column != "Actions"
        ]
        columns = [all_columns[index] for index in indexes]
        if any(column not in columns for column in EMPLOYEE_COLUMNS):
            raise WorkflowError("OrangeHRM changed the employee list columns.")

        table_body = self.page.locator(".oxd-table-body")
        next_page = self.page.locator(".oxd-pagination-page-item").filter(
            has=self.page.locator(".bi-chevron-right")
        )
        rows: list[list[str]] = []
        while len(rows) < expected_count:
            cards.first.wait_for()
            current_rows: list[list[str]] = cards.evaluate_all(
                "(rows) => rows.map(row => Array.from(row.children, "
                "cell => cell.innerText.trim()))"
            )
            if not current_rows or any(
                len(row) != len(all_columns) for row in current_rows
            ):
                raise WorkflowError("The employee list row layout changed.")
            rows.extend([row[index] for index in indexes] for row in current_rows)
            LOGGER.info("Read %d of %d employee records", len(rows), expected_count)
            if " ".join(counter.inner_text().split()) != match[0]:
                raise EmployeeListChanged(
                    "The employee list count changed during extraction."
                )
            if len(rows) < expected_count:
                if not next_page.is_visible():
                    raise EmployeeListChanged(
                        "The employee list ended before the reported count."
                    )
                previous_page = table_body.inner_text()
                next_page.click()
                expect(table_body).not_to_have_text(
                    previous_page, use_inner_text=True, timeout=self.timeout_ms
                )

        if len(rows) != expected_count or next_page.is_visible():
            raise EmployeeListChanged(
                "The employee list count changed during extraction."
            )
        check = [columns.index(name) for name in EMPLOYEE_COLUMNS]
        if not any(
            [row[index] for index in check]
            == [employee.employee_id, employee.first_name, employee.last_name]
            for row in rows
        ):
            raise WorkflowError(
                "The verified employee was missing from the extracted list."
            )
        return columns, rows

    def logout(self) -> None:
        self.user_menu.click()
        self.page.get_by_role("menuitem", name="Logout", exact=True).click()
        self.page.wait_for_url("**/auth/login")
        self.username.wait_for()


def launch_browser(playwright: Playwright, settings: Settings) -> Browser:
    """Prefer Playwright Chromium and use installed Chrome if it is missing."""
    channels = (
        (settings.browser_channel,) if settings.browser_channel else (None, "chrome")
    )
    for channel in channels:
        browser_name = channel or "Playwright Chromium"
        try:
            browser = playwright.chromium.launch(
                channel=channel, headless=settings.headless, timeout=settings.timeout_ms
            )
        except PlaywrightError as error:
            reason = str(error).partition("\n")[0]
            LOGGER.warning("Could not launch %s: %s", browser_name, reason)
            if channel is None and "Executable doesn't exist" in reason:
                continue
            if settings.browser_channel:
                raise WorkflowError(
                    f"Could not start the configured browser ({browser_name}). "
                    "Check that it is installed, or clear "
                    "ORANGEHRM_BROWSER_CHANNEL."
                ) from error
            if channel is None:
                raise WorkflowError(
                    "Playwright Chromium could not start. Check the terminal logs."
                ) from error
        else:
            LOGGER.info("Launched %s", browser_name)
            return browser
    raise WorkflowError(
        "No usable browser found. Install Chromium with "
        "'python -m playwright install chromium', then try again."
    )


def run_automation(
    request: RunInput, settings: Settings, on_progress: ProgressCallback | None = None
) -> RunResult:
    """Execute one isolated run and always release browser resources."""
    result = RunResult(
        employee=request.employee if request.export_only else None,
        export_only=request.export_only,
    )
    action = "Launch browser"
    site: OrangeHrmPage | None = None
    authenticated = False

    def publish(active: str | None = None, message: str | None = None) -> None:
        if on_progress:
            on_progress(
                WorkflowProgress(
                    tuple(result.steps), active, result.failed_step, message
                )
            )

    def begin(step: str) -> str:
        publish(step)
        return step

    def completed(step: str) -> None:
        result.steps.append(step)
        LOGGER.info("Completed step: %s", step)
        publish()

    def retry_export() -> None:
        publish("Extract employee list", "Employee verified. Retrying export…")

    try:
        publish(message="Starting browser…")
        with sync_playwright() as playwright:
            browser = launch_browser(playwright, settings)
            try:
                context = browser.new_context()
                try:
                    site = OrangeHrmPage(context.new_page(), settings.timeout_ms)
                    try:
                        action = begin("Open OrangeHRM")
                        site.open()
                        completed(action)
                        action = begin("Sign in")
                        site.login(request)
                        authenticated = True
                        completed(action)
                        action = begin("Open PIM")
                        site.open_pim()
                        completed(action)
                        if not request.export_only:
                            action = begin("Add employee")
                            site.add_employee(request.employee)
                            completed(action)
                            action = begin("Verify employee details")
                            result.employee = site.verify_employee(request.employee)
                            completed(action)
                        action = begin("Extract employee list")
                        result.columns, result.rows = site.extract_employee_list(
                            request.employee, on_retry=retry_export
                        )
                        completed(action)
                    except Exception:
                        result.failed_step = action
                        raise
                    finally:
                        if authenticated or site.user_menu.is_visible():
                            try:
                                publish("Sign out")
                                site.logout()
                                completed("Sign out")
                            except (PlaywrightError, AssertionError) as error:
                                result.failed_step = result.failed_step or "Sign out"
                                LOGGER.warning(
                                    "Sign out failed (%s)", type(error).__name__
                                )
                                result.errors.append(
                                    "Could not verify sign out. "
                                    "The browser session was closed."
                                )
                finally:
                    context.close()
            finally:
                browser.close()
    except WorkflowError as error:
        result.login_rejected = isinstance(error, LoginRejected)
        result.duplicate_employee_id = isinstance(error, DuplicateEmployeeId)
        LOGGER.warning("Step failed: %s (%s)", action, error)
        result.errors.insert(0, str(error))
    except (PlaywrightError, AssertionError) as error:
        LOGGER.warning("Step failed: %s (%s)", action, type(error).__name__)
        result.errors.insert(
            0, f"{action} could not be completed. Check the demo and server logs."
        )
    except Exception as error:
        LOGGER.error("Unexpected failure during %s (%s)", action, type(error).__name__)
        result.errors.insert(
            0, f"An unexpected error occurred during: {action.lower()}."
        )
    if site and site.save_attempted and result.employee is None:
        result.errors.append(
            "The save may have reached OrangeHRM. "
            "Check the employee ID in PIM before retrying."
        )
    if result.errors and not result.failed_step and action not in result.steps:
        result.failed_step = "Open OrangeHRM" if action == "Launch browser" else action
    publish()
    return result
