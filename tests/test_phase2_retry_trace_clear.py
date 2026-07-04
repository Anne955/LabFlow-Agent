from __future__ import annotations

import io
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pico.providers.clients import OpenAICompatibleModelClient
from pico.providers.retry import RetryConfig
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class RetryTraceClearTests(unittest.TestCase):
    def test_retry_events_cleared_after_terminal_provider_failure(self):
        """A terminal ModelProviderError must clear retry_events so stale
        events from the exhausted retry do not leak into the next ask() run's
        trace (wrong-run attribution)."""
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            # max_retries=1: one retry populates retry_events via on_retry,
            # then retries exhaust and complete() raises ProviderConnectionError
            # (a ModelProviderError) - the terminal-failure path under test.
            client = OpenAICompatibleModelClient(
                model="m", base_url="http://x", api_key="k", timeout=5,
                retry_config=RetryConfig(
                    max_retries=1, base_delay_ms=1, max_delay_ms=2,
                    sleep=lambda _s: None, rng=lambda: 0,
                ),
            )
            pico = Pico(
                workspace=WorkspaceContext.build(root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
            )

            def fake_urlopen(req, timeout):
                raise urllib.error.HTTPError(
                    "http://x", 500, "err", {}, io.BytesIO(b"")
                )

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                pico.ask("hi")

            # Without the fix, retry_events would still hold the stale entry
            # from the exhausted retry and leak into the next run's trace.
            self.assertEqual(client.retry_events, [])


if __name__ == "__main__":
    unittest.main()
