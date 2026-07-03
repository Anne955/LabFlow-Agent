from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.labflow_tools import tool_generate_report
from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.security import safe_shell_env
from pico.tool_context import ToolContext
from pico.workspace import WorkspaceContext, resolve_in_workspace


def make_context(root: Path) -> ToolContext:
    return ToolContext(
        root=root,
        path_resolver=lambda raw: resolve_in_workspace(root, raw),
        shell_env_provider=safe_shell_env,
    )


class LabFlowReportTests(unittest.TestCase):
    def test_generate_report_from_qc_summary(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            qc = root / "outputs" / "batch_demo_001" / "qc_summary.csv"
            qc.parent.mkdir(parents=True)
            qc.write_text(
                "finding_id,batch_id,sample_id,file,check,severity,status,message,evidence\n"
                "F0001,batch_demo_001,s1,data/batch_demo_001/spectra/s1_raman.csv,negative_intensity,critical,fail,negative intensity,-1\n",
                encoding="utf-8",
            )
            result = tool_generate_report(make_context(root), {"batch_id": "batch_demo_001"})
            self.assertTrue(result.ok)
            report = root / "reports" / "batch_demo_001_qc_report.md"
            self.assertTrue(report.is_file())
            content = report.read_text(encoding="utf-8")
            self.assertIn("LabFlow QC Report", content)
            self.assertIn("数值异常检查", content)
            self.assertIn("negative_intensity", content)

    def test_runtime_auto_exports_workflow_log_after_batch_tool(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = root / "data" / "batch_demo_001"
            (batch / "spectra").mkdir(parents=True)
            (batch / "metadata.csv").write_text("sample_id,method\ns1,raman\n", encoding="utf-8")
            (batch / "spectra" / "s1_raman.csv").write_text("x,intensity\n1,1\n2,2\n3,3\n4,4\n5,5\n6,6\n7,7\n8,8\n9,9\n10,10\n", encoding="utf-8")
            agent = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=FakeModelClient(
                    [
                        '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"data/batch_demo_001"}}</tool>',
                        "<final>done</final>",
                    ]
                ),
                session_store=SessionStore(root),
                run_store=RunStore(root),
                approval="auto",
                max_steps=3,
            )
            agent.ask("scan batch")
            workflow_log = root / "traces" / "batch_demo_001_workflow_log.json"
            self.assertTrue(workflow_log.is_file())
            self.assertIn("scan_experiment_dir", workflow_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
