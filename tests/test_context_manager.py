from __future__ import annotations

import unittest

from pico.context_manager import build_prompt
from pico.prompt_prefix import PromptPrefix


class ContextManagerTests(unittest.TestCase):
    def test_context_preserves_current_request_when_over_budget(self):
        prefix = PromptPrefix("prefix" * 200, "h", "w", "t", "now")
        prompt, metadata = build_prompt(
            prefix,
            memory_text="memory" * 200,
            relevant_memory_text="relevant" * 200,
            history_text="history" * 500,
            user_message="IMPORTANT CURRENT REQUEST",
            budget=600,
        )
        self.assertIn("IMPORTANT CURRENT REQUEST", prompt)
        self.assertTrue(metadata["budget_reductions"])
        self.assertIn("current_request", metadata["section_chars"])

    def test_context_section_order(self):
        prefix = PromptPrefix("P", "h", "w", "t", "now")
        prompt, _ = build_prompt(prefix, "M", "R", "H", "C", budget=10_000)
        self.assertLess(prompt.index("<prefix>"), prompt.index("<memory>"))
        self.assertLess(prompt.index("<memory>"), prompt.index("<relevant_memory>"))
        self.assertLess(prompt.index("<relevant_memory>"), prompt.index("<history>"))
        self.assertLess(prompt.index("<history>"), prompt.index("<current_request>"))


if __name__ == "__main__":
    unittest.main()
