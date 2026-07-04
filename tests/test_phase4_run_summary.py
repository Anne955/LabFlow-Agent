from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class RunSummaryTests(unittest.TestCase):
    def test_run_summary_event_emitted(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            client = FakeModelClient(script=["<final>done</final>"])
            pico = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=2,
            )
            pico.ask("hi")
            run_dirs = sorted((root / ".pico" / "runs").iterdir())
            trace_lines = (run_dirs[-1] / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            types = [json.loads(line)["type"] for line in trace_lines if line.strip()]
            self.assertIn("run_summary", types)
            summary = next(json.loads(line) for line in trace_lines if '"run_summary"' in line)
            self.assertIn("tool_call_count", summary["payload"])
            self.assertIn("provider_call_count", summary["payload"])


if __name__ == "__main__":
    unittest.main()
