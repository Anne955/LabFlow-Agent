from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.errors import SafetyViolationError
from pico.labflow_tools import tool_generate_report
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import resolve_in_workspace


def make_ctx(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class LabFlowWriteGuardTests(unittest.TestCase):
    def test_generate_report_refuses_findings_path_inside_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs" / "batch_001").mkdir(parents=True)
            fake_findings = root / "data" / "batch_001" / "qc_summary.csv"
            fake_findings.parent.mkdir(parents=True)
            fake_findings.write_text("finding_id\nF0001\n", encoding="utf-8")
            ctx = make_ctx(root)
            with self.assertRaises(SafetyViolationError):
                tool_generate_report(
                    ctx,
                    {
                        "batch_id": "batch_001",
                        "findings_path": str(fake_findings.relative_to(root)),
                    },
                )


if __name__ == "__main__":
    unittest.main()
