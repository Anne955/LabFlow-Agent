from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext

FULL_SCRIPT = [
    '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"data/batch_demo_001","batch_id":"batch_demo_001"}}</tool>',
    '<tool>{"name":"inspect_table","args":{"path":"data/batch_demo_001/metadata.csv","max_rows":5}}</tool>',
    '<tool>{"name":"quality_check","args":{"experiment_dir":"data/batch_demo_001","batch_id":"batch_demo_001"}}</tool>',
    '<tool>{"name":"run_preprocess_script","args":{"script_name":"normalize_csv.py","batch_id":"batch_demo_001","input_path":"data/batch_demo_001/spectra/sample_001_raman.csv","output_path":"sample_001_normalized.csv"}}</tool>',
    '<tool>{"name":"summarize_outputs","args":{"batch_id":"batch_demo_001"}}</tool>',
    '<tool>{"name":"generate_report","args":{"batch_id":"batch_demo_001"}}</tool>',
    '<tool>{"name":"export_workflow_log","args":{"batch_id":"batch_demo_001"}}</tool>',
    '<final>done</final>',
]


def seed_batch(root: Path) -> None:
    batch = root / "data" / "batch_demo_001"
    spectra = batch / "spectra"
    spectra.mkdir(parents=True)
    (batch / "metadata.csv").write_text("sample_id,method\nsample_001,raman\n", encoding="utf-8")
    rows = "x,intensity\n" + "\n".join(f"{idx},{idx + 100}" for idx in range(1, 13)) + "\n"
    (spectra / "sample_001_raman.csv").write_text(rows, encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    source_script = Path(__file__).resolve().parents[1] / "scripts" / "normalize_csv.py"
    (scripts / "normalize_csv.py").write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")


class WorkflowTraceTests(unittest.TestCase):
    def test_full_workflow_log_contains_seven_events_with_inputs_and_durations(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            seed_batch(root)
            agent = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=FakeModelClient(FULL_SCRIPT),
                session_store=SessionStore(root),
                run_store=RunStore(root),
                approval="auto",
                max_steps=7,
            )
            self.assertEqual(agent.ask("run full workflow"), "done")
            workflow_log = root / "traces" / "batch_demo_001_workflow_log.json"
            self.assertTrue(workflow_log.is_file())
            data = json.loads(workflow_log.read_text(encoding="utf-8"))
            self.assertEqual(data["event_count"], 7)
            self.assertGreaterEqual(data["total_duration_seconds"], 0)
            tools = [event["tool"] for event in data["events"]]
            self.assertEqual(
                tools,
                [
                    "scan_experiment_dir",
                    "inspect_table",
                    "quality_check",
                    "run_preprocess_script",
                    "summarize_outputs",
                    "generate_report",
                    "export_workflow_log",
                ],
            )
            for event in data["events"]:
                self.assertIn("timestamp", event)
                self.assertIn("run_id", event)
                self.assertIn("session_id", event)
                self.assertIn("batch_id", event)
                self.assertIn("status", event)
                self.assertIn("duration_seconds", event)
                self.assertIsInstance(event["input"], dict)
            self.assertEqual(data["events"][0]["input"]["experiment_dir"], "data/batch_demo_001")


if __name__ == "__main__":
    unittest.main()
