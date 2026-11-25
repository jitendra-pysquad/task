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
from app.models import RunInput, RunResult


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

    def fake_runner(self, request: RunInput, settings: Settings) -> RunResult:
        self.calls.append(request)
        if request.employee.employee_id == "FAIL":
            return RunResult(
                steps=["Open OrangeHRM", "Sign in", "Open PIM"],
                errors=["That employee ID already exists. Use a unique ID."],
            )
        if request.employee.employee_id == "BLOCK":
            self.blocked.set()
            self.release.wait(timeout=5)
        if request.employee.employee_id == "COUNT" and not request.export_only:
            return RunResult(
                employee=request.employee,
                errors=["The employee list count changed during extraction."],
            )
        return RunResult(
            steps=["Open OrangeHRM", "Sign out"],
            employee=request.employee,
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
        self.assertIn("That employee ID already exists.", page.text)
        self.assertNotIn("Download employee CSV", page.text)
        download = await self.client.get(f"{page.url}/employees.csv")
        self.assertEqual(download.status_code, 404)

    async def test_concurrent_submission_reports_busy(self) -> None:
        pending = asyncio.create_task(
            self.client.post("/runs", data={**self.fields, "employee_id": "BLOCK"})
        )
        try:
            self.assertTrue(await asyncio.to_thread(self.blocked.wait, 3))
            result = await self.client.post("/runs", data=self.fields)
            self.assertEqual(result.status_code, 409)
            self.assertIn("An automation is running.", result.text)
            self.assertEqual(len(self.calls), 1)
        finally:
            self.release.set()
            await pending
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
        result = await self.client.post(retry, data=self.fields, follow_redirects=True)
        self.assertIn("Automation completed successfully", result.text)
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.calls[0].export_only)
        self.assertTrue(self.calls[1].export_only)
        self.assertEqual(self.calls[0].employee, self.calls[1].employee)
        download = await self.client.get(f"{result.url}/employees.csv")
        self.assertIn("COUNT,Riley,Demo", download.text)
