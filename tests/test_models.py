"""Form and CSV edge cases that do not require a browser."""

import unittest

from app.artifacts import spreadsheet_cell
from app.models import validate_form


class FormValidationTests(unittest.TestCase):
    def test_normalizes_names_without_coercing_id_or_password(self) -> None:
        credentials = " with whitespace "
        request, values, errors = validate_form(
            {
                "username": " Demo ",
                "password": credentials,
                "first_name": "  Zoë  ",
                "last_name": "D’Angelo",
                "employee_id": " 00021 ",
            }
        )
        assert request is not None
        self.assertEqual(errors, {})
        self.assertEqual(request.username, "Demo")
        self.assertEqual(request.password, credentials)
        self.assertNotIn("password", values)
        self.assertNotIn(credentials, repr(request))
        self.assertEqual(request.employee.first_name, "Zoë")
        self.assertEqual(request.employee.last_name, "D’Angelo")
        self.assertEqual(request.employee.employee_id, "00021")

    def test_missing_values_and_control_characters(self) -> None:
        request, values, errors = validate_form(
            {
                "first_name": "Ril\x00ey",
                "password": " ",
                "last_name": [],
            }
        )
        self.assertIsNone(request)
        self.assertEqual(len(errors), 5)
        self.assertIn("control characters", errors["first_name"])
        self.assertNotIn("password", values)

    def test_neutralizes_spreadsheet_formulas_without_changing_plain_text(self) -> None:
        for value in ["=2+2", " +2", "-2", "@SUM(A1)", "\tname", "＝foo"]:
            with self.subTest(value=value):
                self.assertEqual(spreadsheet_cell(value), "'" + value)
        self.assertEqual(spreadsheet_cell("00021"), "00021")
        self.assertEqual(spreadsheet_cell("Núñez, Smith"), "Núñez, Smith")
