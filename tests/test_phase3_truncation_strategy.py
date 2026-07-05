from __future__ import annotations

import unittest

from pico.context_manager import PriorityTruncation, SmartTruncation


class TruncationStrategyTests(unittest.TestCase):
    def test_priority_keeps_current_behavior(self):
        strat = PriorityTruncation()
        sections = {
            "prefix": "P" * 5000,
            "suggested_plan": "S" * 200,
            "memory": "M" * 2000,
            "relevant_memory": "R" * 2000,
            "history": "H" * 5000,
            "current_request": "U" * 100,
        }
        out = strat.truncate(sections, budget=8000)
        total = sum(len(v) for v in out.values())
        self.assertLessEqual(total, 8000)

    def test_smart_exists_and_is_strategy(self):
        strat = SmartTruncation(intent="explain_finding")
        sections = {
            "prefix": "P",
            "suggested_plan": "",
            "memory": "M",
            "relevant_memory": "R",
            "history": "H",
            "current_request": "U",
        }
        out = strat.truncate(sections, budget=1000)
        self.assertIn("history", out)


if __name__ == "__main__":
    unittest.main()
