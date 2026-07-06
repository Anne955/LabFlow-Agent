from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pico.config import DEFAULT_CONTEXT_BUDGET
from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext

# An explain_finding prompt: "why is F0001 abnormal for batch_001".
EXPLAIN_PROMPT = "为什么 batch_001 的 F0001 异常"
# A single history turn whose rendered text (## user\n + content) far exceeds the
# 12_000 budget, so truncation always triggers and the history section is always
# the section that gets clipped. 15_000 > budget > smart limit (3_000) > pri limit (2_400).
HISTORY_CONTENT = "H" * 15_000


def _make_pico(root: Path, use_planner: bool = True) -> Pico:
    workspace = WorkspaceContext.build(root)
    pico = Pico(
        workspace=workspace,
        model_client=FakeModelClient([]),
        session_store=SessionStore(root),
        run_store=RunStore(root),
        use_planner=use_planner,
    )
    pico.history = [{"role": "user", "content": HISTORY_CONTENT}]
    return pico


def _history_chars(root: Path, env_value: str | None, use_planner: bool = True) -> int:
    """Run build_prompt_and_metadata under the given truncation env and return history chars."""
    env_override: dict[str, str] = {}
    if env_value is not None:
        env_override["PICO_TRUNCATION_STRATEGY"] = env_value
    with patch.dict(os.environ, env_override, clear=False):
        # Ensure the var is exactly what we want: set or absent.
        if env_value is None:
            os.environ.pop("PICO_TRUNCATION_STRATEGY", None)
        pico = _make_pico(root, use_planner=use_planner)
        _, metadata = pico.build_prompt_and_metadata(EXPLAIN_PROMPT)
    return int(metadata["section_chars"]["history"])


class FollowUp1SmartTruncationTests(unittest.TestCase):
    def test_smart_retains_more_history_than_priority_for_explain_finding(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            smart_history = _history_chars(root, "smart")
            priority_history = _history_chars(root, "priority")
        # Smart (explain_finding) keeps history at 0.25*budget; priority at 0.2*budget.
        self.assertGreater(smart_history, priority_history)
        self.assertEqual(smart_history, int(DEFAULT_CONTEXT_BUDGET * 0.25))
        self.assertEqual(priority_history, int(DEFAULT_CONTEXT_BUDGET * 0.2))

    def test_default_env_truncates_history_at_priority_limit(self):
        # Regression: with no env var set, behavior is unchanged (priority limit).
        with TemporaryDirectory() as d:
            root = Path(d)
            history_chars = _history_chars(root, None)
        self.assertEqual(history_chars, int(DEFAULT_CONTEXT_BUDGET * 0.2))

    def test_smart_with_planner_off_still_uses_detected_intent(self):
        # When the planner is off, the intent comes from detect_intent directly;
        # the explain prompt still resolves to explain_finding, so smart must
        # still keep more history than priority.
        with TemporaryDirectory() as d:
            root = Path(d)
            smart_history = _history_chars(root, "smart", use_planner=False)
            priority_history = _history_chars(root, "priority", use_planner=False)
        self.assertGreater(smart_history, priority_history)
        self.assertEqual(smart_history, int(DEFAULT_CONTEXT_BUDGET * 0.25))


if __name__ == "__main__":
    unittest.main()
