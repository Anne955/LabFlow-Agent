from __future__ import annotations

import io
import json
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

_FINAL_RESPONSE = (
    b'{"choices":[{"message":{"content":"<final>done</final>"}}],"usage":{}}'
)


class RetryTraceTests(unittest.TestCase):
    def test_retry_event_emitted_then_success(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            client = OpenAICompatibleModelClient(
                model="m", base_url="http://x", api_key="k", timeout=5,
                retry_config=RetryConfig(
                    max_retries=2, base_delay_ms=1, max_delay_ms=2,
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
            calls = {"n": 0}

            def fake_urlopen(req, timeout):
                calls["n"] += 1
                if calls["n"] < 2:
                    raise urllib.error.HTTPError(
                        "http://x", 500, "err", {}, io.BytesIO(b"")
                    )

                class R:
                    def read(self):
                        return _FINAL_RESPONSE

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False

                return R()

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                pico.ask("hi")

            run_dirs = sorted((root / ".pico" / "runs").iterdir())
            trace_lines = (run_dirs[-1] / "trace.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()
            types = [json.loads(line)["type"] for line in trace_lines if line.strip()]
            self.assertIn("provider_retry", types)


if __name__ == "__main__":
    unittest.main()
