from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


def make_pico(tmp_path: Path, script: list[str]) -> Pico:
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        workspace=workspace,
        model_client=FakeModelClient(script),
        session_store=SessionStore(tmp_path),
        run_store=RunStore(tmp_path),
        approval="auto",
        max_steps=4,
    )


class RuntimeTests(unittest.TestCase):
    def test_runtime_final_only_writes_artifacts(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            pico = make_pico(tmp_path, ["<final>done</final>"])
            answer = pico.ask("hello")
            self.assertEqual(answer, "done")
            self.assertTrue((tmp_path / ".pico" / "sessions" / f"{pico.session_id}.json").is_file())
            run_dirs = list((tmp_path / ".pico" / "runs").iterdir())
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "task_state.json").is_file())
            self.assertTrue((run_dirs[0] / "trace.jsonl").is_file())
            self.assertTrue((run_dirs[0] / "report.json").is_file())

    def test_runtime_tool_then_final(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "README.md").write_text("# Hello\n", encoding="utf-8")
            pico = make_pico(
                tmp_path,
                [
                    '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"."}}</tool>',
                    "<final>I read it.</final>",
                ],
            )
            answer = pico.ask("read README")
            self.assertEqual(answer, "I read it.")
            self.assertIn("scan_experiment_dir", [item.get("name") for item in pico.history])

    def test_runtime_rejected_tool_can_continue(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            pico = make_pico(
                tmp_path,
                [
                    '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"../outside"}}</tool>',
                    "<final>reported rejection</final>",
                ],
            )
            answer = pico.ask("try bad read")
            self.assertEqual(answer, "reported rejection")
            self.assertTrue(
                any(
                    item.get("role") == "tool" and "path_escape" in item.get("content", "")
                    for item in pico.history
                )
            )

    def test_runtime_step_limit(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "a.txt").write_text("a", encoding="utf-8")
            pico = Pico(
                workspace=WorkspaceContext.build(tmp_path),
                model_client=FakeModelClient(
                    [
                        '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":"."}}</tool>',
                        '<tool>{"name":"scan_experiment_dir","args":{"experiment_dir":".","batch_id":"tmp"}}</tool>',
                    ]
                ),
                session_store=SessionStore(tmp_path),
                run_store=RunStore(tmp_path),
                approval="auto",
                max_steps=1,
            )
            answer = pico.ask("loop")
            self.assertEqual(answer, "")
            run_dir = next((tmp_path / ".pico" / "runs").iterdir())
            self.assertIn('"step_limit_reached"', (run_dir / "task_state.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
