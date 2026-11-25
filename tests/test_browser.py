"""Test browser selection without launching a desktop browser."""

import unittest
from unittest.mock import Mock, call

from playwright.sync_api import Error as PlaywrightError

from app.automation import WorkflowError, launch_browser
from app.config import Settings


class BrowserStartupTests(unittest.TestCase):
    def test_uses_installed_chrome_when_managed_browser_is_missing(self) -> None:
        playwright = Mock()
        browser = Mock()
        playwright.chromium.launch.side_effect = [
            PlaywrightError("BrowserType.launch: Executable doesn't exist at path"),
            browser,
        ]

        with self.assertLogs("uvicorn.error.orangehrm"):
            self.assertIs(launch_browser(playwright, Settings()), browser)
        self.assertEqual(
            playwright.chromium.launch.call_args_list,
            [
                call(channel=None, headless=True, timeout=20_000),
                call(channel="chrome", headless=True, timeout=20_000),
            ],
        )

    def test_explains_how_to_install_a_browser_if_both_are_missing(self) -> None:
        playwright = Mock()
        playwright.chromium.launch.side_effect = [
            PlaywrightError("BrowserType.launch: Executable doesn't exist at path"),
            PlaywrightError(
                "BrowserType.launch: Chromium distribution 'chrome' is absent"
            ),
        ]

        with (
            self.assertLogs("uvicorn.error.orangehrm"),
            self.assertRaisesRegex(WorkflowError, "playwright install chromium"),
        ):
            launch_browser(playwright, Settings())

    def test_explicit_channel_failure_does_not_try_other_browsers(self) -> None:
        playwright = Mock()
        playwright.chromium.launch.side_effect = PlaywrightError(
            "BrowserType.launch: Chromium distribution 'chrome' is absent"
        )

        with (
            self.assertLogs("uvicorn.error.orangehrm"),
            self.assertRaisesRegex(WorkflowError, "ORANGEHRM_BROWSER_CHANNEL"),
        ):
            launch_browser(playwright, Settings(browser_channel="chrome"))
        playwright.chromium.launch.assert_called_once_with(
            channel="chrome", headless=True, timeout=20_000
        )
