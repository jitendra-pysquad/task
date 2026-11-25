"""Store run results locally and render spreadsheet-safe CSV downloads."""

import csv
import json
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from uuid import UUID

from .models import Employee, RunResult


def save_result(directory: Path, owner: str, run_id: UUID, result: RunResult) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{run_id}.json"
    temporary = path.with_suffix(".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as file:
            json.dump({"owner": owner, "result": asdict(result)}, file)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def load_result(directory: Path, owner: str, run_id: UUID) -> RunResult | None:
    try:
        with (directory / f"{run_id}.json").open(encoding="utf-8") as file:
            snapshot = json.load(file)
    except FileNotFoundError:
        return None

    if snapshot["owner"] != owner:
        return None
    data = snapshot["result"]
    if data["employee"] is not None:
        data["employee"] = Employee(**data["employee"])
    return RunResult(**data)


def spreadsheet_cell(value: str) -> str:
    """Prevent untrusted cell content from executing as a formula in Excel."""
    if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(
        ("=", "+", "-", "@", "＝", "＋", "－", "＠")
    ):
        return "'" + value
    return value


def employee_csv(result: RunResult) -> bytes:
    """Return UTF-8 with BOM for spreadsheet compatibility."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(spreadsheet_cell(column) for column in result.columns)
    writer.writerows([spreadsheet_cell(value) for value in row] for row in result.rows)
    return output.getvalue().encode("utf-8-sig")
