from __future__ import annotations

import json
import unittest

from pico.run_store import RunStore, SessionStore
from pico.task_state import TaskState


class StoreTests(unittest.TestCase):
    def test_run_store_writes_artifacts(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            from pathlib import Path

            tmp_path = Path(directory)
            store = RunStore(tmp_path)
            state = TaskState.create("do it")
            run_dir = store.start_run(state)
            store.append_trace(state.run_id, {"type": "event"})
            state.finish_success("done")
            store.write_task_state(state)
            store.write_report(state.run_id, {"status": state.status})

            self.assertTrue((run_dir / "task_state.json").is_file())
            self.assertTrue((run_dir / "trace.jsonl").is_file())
            self.assertTrue((run_dir / "report.json").is_file())
            self.assertEqual(json.loads((run_dir / "task_state.json").read_text())["status"], "completed")
            self.assertEqual(json.loads((run_dir / "report.json").read_text())["status"], "completed")

    def test_session_store_save_load_latest(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            store = SessionStore(tmp_path)
            store.save({"id": "session_a", "history": [], "memory": {}})
            loaded = store.load("session_a")
            self.assertEqual(loaded["id"], "session_a")
            self.assertEqual(store.latest(), "session_a")


if __name__ == "__main__":
    unittest.main()
