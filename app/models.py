"""Validated form input and automation result types."""

from dataclasses import dataclass, field
from typing import Callable, Mapping

FIELD_LIMITS = {
    "username": 255,
    "password": 255,
    "first_name": 30,
    "last_name": 30,
    "employee_id": 10,
}
FIELD_LABELS = {
    "username": "Username",
    "password": "Password",
    "first_name": "First name",
    "last_name": "Last name",
    "employee_id": "Employee ID",
}
WORKFLOW_STEPS = {
    "Open OrangeHRM": "Opening OrangeHRM",
    "Sign in": "Signing in",
    "Open PIM": "Opening PIM",
    "Add employee": "Adding employee",
    "Verify employee details": "Verifying employee details",
    "Extract employee list": "Extracting employee list",
    "Sign out": "Signing out",
}
EXPORT_ONLY_STEPS = tuple(
    step
    for step in WORKFLOW_STEPS
    if step not in {"Add employee", "Verify employee details"}
)


@dataclass(frozen=True)
class WorkflowProgress:
    completed: tuple[str, ...] = ()
    active: str | None = None
    failed: str | None = None
    message: str | None = None


ProgressCallback = Callable[[WorkflowProgress], None]


@dataclass(frozen=True)
class Employee:
    first_name: str
    last_name: str
    employee_id: str


@dataclass(frozen=True)
class RunInput:
    username: str = field(repr=False)
    password: str = field(repr=False)
    employee: Employee
    export_only: bool = False


@dataclass
class RunResult:
    steps: list[str] = field(default_factory=list)
    employee: Employee | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    failed_step: str | None = None
    export_only: bool = False
    login_rejected: bool = False
    duplicate_employee_id: bool = False

    @property
    def successful(self) -> bool:
        return not self.errors and self.employee is not None and bool(self.rows)


def validate_form(
    data: Mapping[str, object],
    existing_employee: Employee | None = None,
) -> tuple[RunInput | None, dict[str, str], dict[str, str]]:
    """Validate form fields and return only safe-to-redisplay values."""
    values: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name, limit in FIELD_LIMITS.items():
        if existing_employee is not None and name not in {"username", "password"}:
            continue
        raw = data.get(name)
        value = raw if isinstance(raw, str) else ""
        if name != "password":
            value = value.strip()
        values[name] = value
        if not value.strip():
            errors[name] = f"Enter a {FIELD_LABELS[name].lower()}."
        elif len(value) > limit:
            errors[name] = f"Use {limit} characters or fewer."
        elif name != "password" and any(ord(char) < 32 for char in value):
            errors[name] = "Remove control characters."

    password = values.pop("password")
    if errors:
        return None, values, errors

    employee = existing_employee or Employee(
        values["first_name"], values["last_name"], values["employee_id"]
    )
    return (
        RunInput(
            values["username"],
            password,
            employee,
            export_only=existing_employee is not None,
        ),
        values,
        errors,
    )
