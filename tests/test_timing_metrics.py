from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.workflow_trace import build_workflow_log


class TimingMetricsTests(unittest.TestCase):
    def test_workflow_log_sums_tool_durations(self):
        with TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            events = [
                {
                    "id": "evt_1",
                    "type": "tool_finished",
                    "created_at": "2026-01-01T00:00:00Z",
                    "run_id": "run_1",
                    "payload": {
                        "name": "scan_experiment_dir",
                        "input": {"experiment_dir": "data/batch_demo_001"},
                        "duration_seconds": 0.25,
                        "result": {
                            "ok": True,
                            "metadata": {"batch_id": "batch_demo_001"},
                            "affected_paths": [],
                            "error_code": None,
                        },
                    },
                },
                {
                    "id": "evt_2",
                    "type": "tool_finished",
                    "created_at": "2026-01-01T00:00:01Z",
                    "run_id": "run_1",
                    "payload": {
                        "name": "quality_check",
                        "input": {"batch_id": "batch_demo_001"},
                        "duration_seconds": 0.75,
                        "result": {
                            "ok": True,
                            "metadata": {"batch_id": "batch_demo_001"},
                            "affected_paths": ["outputs/batch_demo_001/qc_summary.csv"],
                            "error_code": None,
                        },
                    },
                },
            ]
            trace.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
            log = build_workflow_log(trace, "batch_demo_001", "run_1", "session_1")
            self.assertEqual(log["event_count"], 2)
            self.assertAlmostEqual(log["total_duration_seconds"], 1.0)
            self.assertEqual(log["events"][1]["duration_seconds"], 0.75)


if __name__ == "__main__":
    unittest.main()
