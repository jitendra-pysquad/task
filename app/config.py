"""Runtime configuration for the local dashboard."""

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_URL = "https://opensource-demo.orangehrmlive.com"


@dataclass(frozen=True)
class Settings:
    timeout_ms: int = 20_000
    headless: bool = True
    browser_channel: str | None = None
    run_directory: Path = ROOT / "runtime" / "runs"

    @classmethod
    def from_environment(cls) -> "Settings":
        timeout = int(os.getenv("ORANGEHRM_TIMEOUT_MS", "20000"))
        if not 1_000 <= timeout <= 120_000:
            raise ValueError("ORANGEHRM_TIMEOUT_MS must be 1000–120000.")
        headless = os.getenv("ORANGEHRM_HEADLESS", "true").lower()
        if headless not in {"true", "false"}:
            raise ValueError("ORANGEHRM_HEADLESS must be true or false.")
        return cls(
            timeout_ms=timeout,
            headless=headless == "true",
            browser_channel=os.getenv("ORANGEHRM_BROWSER_CHANNEL") or None,
        )
