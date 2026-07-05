from __future__ import annotations

import unittest

from pico.errors import PicoError, SafetyViolationError, ToolExecutionError


class ErrorHierarchyTests(unittest.TestCase):
    def test_safety_violation_is_pico_error(self):
        self.assertTrue(issubclass(SafetyViolationError, PicoError))

    def test_tool_execution_carries_error_code(self):
        err = ToolExecutionError("batch missing", error_code="not_found")
        self.assertEqual(err.error_code, "not_found")
        self.assertIn("batch missing", str(err))

    def test_tool_execution_is_pico_error(self):
        self.assertTrue(issubclass(ToolExecutionError, PicoError))


if __name__ == "__main__":
    unittest.main()
