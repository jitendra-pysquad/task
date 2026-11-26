"""Route tests with an isolated artifact directory and a fake browser runner."""

import asyncio
import csv
import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from threading import Event

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import (
    EXPORT_ONLY_STEPS,
    WORKFLOW_STEPS,
    ProgressCallback,
    RunInput,
    RunResult,
    WorkflowProgress,
)


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "runs"
        self.calls: list[RunInput] = []
        self.blocked = Event()
        self.release = Event()
        self.addCleanup(self.release.set)
        self.app = create_app(Settings(run_directory=self.directory), self.fake_runner)
        self.client = AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://testserver"
        )
        self.addAsyncCleanup(self.client.aclose)
        page = await self.client.get("/")
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text)
        assert csrf is not None
        self.fields = {
            "csrf": csrf[1],
            "username": "test-user",
            "password": "test-password-007",
            "first_name": "Riley",
            "last_name": "Demo",
            "employee_id": "000027",
        }

    def fake_runner(
        self, request: RunInput, settings: Settings, on_progress: ProgressCallback
    ) -> RunResult:
        self.calls.append(request)
        if request.password == "rejected-password":
            return RunResult(
                steps=["Open OrangeHRM"],
                errors=["Invalid username or password"],
                failed_step="Sign in",
                export_only=request.export_only,
                login_rejected=True,
            )
        if request.employee.employee_id == "FAIL":
            return RunResult(
                steps=["Open OrangeHRM", "Sign in", "Open PIM"],
                errors=["OrangeHRM rejected the employee form."],
            )
        if request.employee.employee_id == "DUP":
            return RunResult(
                steps=["Open OrangeHRM", "Sign in", "Open PIM", "Sign out"],
                errors=["That employee ID already exists. Use a unique ID."],
                failed_step="Add employee",
                duplicate_employee_id=True,
            )
        if request.employee.employee_id == "BLOCK":
            on_progress(WorkflowProgress(("Open OrangeHRM",), active="Sign in"))
            self.blocked.set()
            self.release.wait(timeout=5)
        if request.employee.employee_id == "COUNT" and not request.export_only:
            return RunResult(
                employee=request.employee,
                errors=["The employee list count changed during extraction."],
            )
        return RunResult(
            steps=list(EXPORT_ONLY_STEPS if request.export_only else WORKFLOW_STEPS),
            employee=request.employee,
            export_only=request.export_only,
            columns=["Id", "First (& Middle) Name", "Last Name"],
            rows=[
                [
                    request.employee.employee_id,
                    request.employee.first_name,
                    request.employee.last_name,
                ],
                ["000026", "=1+1", "<script>alert(1)</script>"],
            ],
        )

    async def test_success_download_refresh_and_credential_redaction(self) -> None:
        page = await self.client.post("/runs", data=self.fields)
        self.assertEqual(page.status_code, 303)
        run = page.headers["location"]
        for _ in range(2):
            result = await self.client.get(run)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.headers["cache-control"], "no-store")
            self.assertIn("Automation completed successfully", result.text)
            self.assertIn("000027", result.text)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", result.text)
            self.assertNotIn(self.fields["password"], result.text)

        download = await self.client.get(f"{run}/employees.csv")
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["content-disposition"])
        rows = list(csv.reader(io.StringIO(download.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1], ["000027", "Riley", "Demo"])
        self.assertEqual(rows[2][1], "'=1+1")
        self.assertEqual(len(self.calls), 1)

        snapshot = next(self.directory.glob("*.json")).read_text()
        self.assertNotIn(self.fields["password"], snapshot)
        self.assertNotIn(self.fields["username"], snapshot)
        self.assertEqual(
            json.loads(snapshot)["result"]["employee"]["employee_id"], "000027"
        )

    async def test_duplicate_employee_id_keeps_form_and_focuses_id(self) -> None:
        page = await self.client.post(
            "/runs", data={**self.fields, "employee_id": "DUP"}
        )
        self.assertEqual(page.status_code, 422)
        self.assertIn('id="employee-id-alert" role="alert"', page.text)
        self.assertIn("Employee ID already in use", page.text)
        self.assertNotIn("Run result", page.text)
        for field in ("username", "first_name", "last_name"):
            self.assertIn(f'value="{self.fields[field]}"', page.text)
        self.assertIn('value="DUP"', page.text)
        self.assertNotIn(self.fields["password"], page.text)
        self.assertIn('aria-describedby="employee-id-alert" autofocus', page.text)
        self.assertIn('class="failed">Add employee', page.text)
        self.assertIn('class="completed">Sign out', page.text)

        snapshot = next(self.directory.glob("*.json")).read_text()
        self.assertNotIn(self.fields["password"], snapshot)
        self.assertNotIn(self.fields["username"], snapshot)
        self.assertIsNone(json.loads(snapshot)["result"]["employee"])

    async def test_results_and_csv_are_bound_to_the_browser(self) -> None:
        run = (await self.client.post("/runs", data=self.fields)).headers["location"]
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://testserver"
        ) as other:
            await other.get("/")
            self.assertEqual((await other.get(run)).status_code, 404)
            self.assertEqual((await other.get(f"{run}/employees.csv")).status_code, 404)

    async def test_invalid_form_never_starts_browser(self) -> None:
        page = await self.client.post(
            "/runs",
            data={**self.fields, "last_name": " ", "employee_id": "ABCDEFGHIJK"},
        )
        self.assertEqual(page.status_code, 422)
        self.assertIn("Enter a last name.", page.text)
        self.assertIn("Use 10 characters or fewer.", page.text)
        self.assertNotIn(self.fields["password"], page.text)
        self.assertEqual(self.calls, [])

    async def test_rejected_login_keeps_form_and_failed_step(self) -> None:
        page = await self.client.post(
            "/runs", data={**self.fields, "password": "rejected-password"}
        )
        self.assertEqual(page.status_code, 422)
        self.assertIn('id="login-alert" role="alert"', page.text)
        self.assertIn("Configure run", page.text)
        self.assertNotIn("Run result", page.text)
        for field in ("username", "first_name", "last_name", "employee_id"):
            self.assertIn(f'value="{self.fields[field]}"', page.text)
        self.assertNotIn("rejected-password", page.text)
        self.assertIn('aria-describedby="login-alert" autofocus', page.text)
        self.assertIn('class="completed">Open OrangeHRM', page.text)
        self.assertIn('class="failed">Sign in', page.text)
        self.assertIn("1 of 7 steps complete", page.text)
        self.assertEqual(len(self.calls), 1)

    async def test_csrf_rejected_before_automation(self) -> None:
        page = await self.client.post("/runs", data={**self.fields, "csrf": "é"})
        self.assertEqual(page.status_code, 403)
        self.assertEqual(self.calls, [])

    async def test_oversized_form_rejected_before_automation(self) -> None:
        page = await self.client.post(
            "/runs", data={**self.fields, "password": "x" * 16_384}
        )
        self.assertEqual(page.status_code, 413)
        self.assertEqual(self.calls, [])

    async def test_workflow_failure_has_no_download(self) -> None:
        page = await self.client.post(
            "/runs", data={**self.fields, "employee_id": "FAIL"}, follow_redirects=True
        )
        self.assertIn("Automation failed", page.text)
        self.assertIn("OrangeHRM rejected the employee form.", page.text)
        self.assertNotIn("Download employee CSV", page.text)
        download = await self.client.get(f"{page.url}/employees.csv")
        self.assertEqual(download.status_code, 404)

    async def test_concurrent_submission_reports_busy(self) -> None:
        page = await self.client.get("/")
        workflow = re.search(r'data-workflow-id="([^"]+)"', page.text)
        assert workflow is not None
        path = f"/workflow-progress/{workflow[1]}"
        pending = asyncio.create_task(
            self.client.post(
                "/runs",
                data={**self.fields, "employee_id": "BLOCK"},
                headers={"X-Workflow-Id": workflow[1]},
            )
        )
        try:
            self.assertTrue(await asyncio.to_thread(self.blocked.wait, 3))
            progress = await self.client.get(path)
            self.assertEqual(progress.headers["cache-control"], "no-store")
            self.assertEqual(progress.json()["active"], "Sign in")
            self.assertEqual(progress.json()["completed"], ["Open OrangeHRM"])
            async with AsyncClient(
                transport=ASGITransport(app=self.app), base_url="http://testserver"
            ) as other:
                await other.get("/")
                self.assertEqual((await other.get(path)).status_code, 404)
            result = await self.client.post("/runs", data=self.fields)
            self.assertEqual(result.status_code, 409)
            self.assertIn("An automation is running.", result.text)
            self.assertEqual(len(self.calls), 1)
        finally:
            self.release.set()
            await pending
        self.assertEqual((await self.client.get(path)).status_code, 404)
        self.assertEqual(
            (await self.client.post("/runs", data=self.fields)).status_code, 303
        )

    async def test_retry_exports_the_existing_verified_employee(self) -> None:
        original = await self.client.post(
            "/runs", data={**self.fields, "employee_id": "COUNT"}, follow_redirects=True
        )
        self.assertIn("Employee verified · export incomplete", original.text)
        self.assertIn("Retry export", original.text)
        retry = f"{original.url}/retry"
        async with AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://testserver"
        ) as other:
            self.assertEqual(
                (await other.post(retry, data=self.fields)).status_code, 404
            )
        self.assertEqual(
            (
                await self.client.post(retry, data={**self.fields, "csrf": "wrong"})
            ).status_code,
            403,
        )
        rejected = await self.client.post(
            retry, data={**self.fields, "password": "rejected-password"}
        )
        self.assertEqual(rejected.status_code, 422)
        self.assertIn('id="login-alert" role="alert"', rejected.text)
        self.assertIn("Verified employee", rejected.text)
        self.assertIn("1 of 5 steps complete", rejected.text)
        self.assertIn("Retry export", rejected.text)
        result = await self.client.post(retry, data=self.fields, follow_redirects=True)
        self.assertIn("Automation completed successfully", result.text)
        self.assertIn("5 of 5 steps complete", result.text)
        self.assertEqual(len(self.calls), 3)
        self.assertFalse(self.calls[0].export_only)
        self.assertTrue(self.calls[1].export_only)
        self.assertEqual(self.calls[0].employee, self.calls[1].employee)
        download = await self.client.get(f"{result.url}/employees.csv")
        self.assertIn("COUNT,Riley,Demo", download.text)
