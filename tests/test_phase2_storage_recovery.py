from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.run_store import RunStore, SessionStore
from pico.task_state import TaskState


class StorageRecoveryTests(unittest.TestCase):
    def test_session_load_quarantines_corrupt_file(self):
        with TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            path = store.path_for("s1")
            path.write_text("{not valid json", encoding="utf-8")
            loaded = store.load("s1")
            self.assertEqual(loaded.get("id"), "s1")
            quarantined = list(store.root.glob("s1.corrupted.*.json"))
            self.assertEqual(len(quarantined), 1)

    def test_run_load_task_state_recovers(self):
        with TemporaryDirectory() as d:
            store = RunStore(Path(d))
            run_dir = store.run_dir("r1")
            run_dir.mkdir(parents=True)
            (run_dir / "task_state.json").write_text("broken{", encoding="utf-8")
            state = store.load_task_state("r1")
            self.assertIsInstance(state, TaskState)


if __name__ == "__main__":
    unittest.main()
