from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from pico.features.memory import LayeredMemory
from pico.workspace import file_freshness


class MemoryTests(unittest.TestCase):
    def test_memory_recent_files_are_deduplicated(self):
        memory = LayeredMemory()
        memory.remember_file("a.py")
        memory.remember_file("b.py")
        memory.remember_file("a.py")
        self.assertEqual(memory.recent_files[:2], ["a.py", "b.py"])

    def test_file_summary_freshness_controls_rendering(self):
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            target = tmp_path / "a.txt"
            target.write_text("hello", encoding="utf-8")
            memory = LayeredMemory()
            memory.set_file_summary("a.txt", "initial summary", file_freshness(target))
            self.assertIn("initial summary", memory.render(tmp_path))
            target.write_text("changed", encoding="utf-8")
            self.assertNotIn("initial summary", memory.render(tmp_path))

    def test_retrieval_candidates_match_terms(self):
        memory = LayeredMemory()
        memory.append_note("Use pytest for verification", tags=["tests"])
        memory.append_note("Use markdown summaries", tags=["docs"])
        results = memory.retrieval_candidates("pytest tests")
        self.assertEqual(results[0].text, "Use pytest for verification")


if __name__ == "__main__":
    unittest.main()
