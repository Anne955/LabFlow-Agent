from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class PlannerIntegrationTests(unittest.TestCase):
    def test_planner_on_injects_suggested_plan(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            captured = {}

            class CapturingClient(FakeModelClient):
                def complete(self, request):
                    captured["prompt"] = request.prompt
                    return super().complete(request)

            client = CapturingClient(script=["<final>ok</final>"])
            pico = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
                use_planner=True,
            )
            pico.ask("对 data/batch_001 跑完整 QC")
            self.assertIn("<suggested_plan>", captured["prompt"])

    def test_planner_off_omits_suggested_plan(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            captured = {}

            class CapturingClient(FakeModelClient):
                def complete(self, request):
                    captured["prompt"] = request.prompt
                    return super().complete(request)

            client = CapturingClient(script=["<final>ok</final>"])
            pico = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
                use_planner=False,
            )
            pico.ask("对 data/batch_001 跑完整 QC")
            self.assertNotIn("<suggested_plan>", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
