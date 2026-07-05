from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from pico.providers.clients import ModelRequest, OpenAICompatibleModelClient
from pico.providers.retry import RetryConfig


class ProviderRetryIntegrationTests(unittest.TestCase):
    def test_complete_retries_transient_then_returns(self):
        sleeps = []
        config = RetryConfig(
            max_retries=2, base_delay_ms=1, max_delay_ms=2, sleep=sleeps.append, rng=lambda: 0
        )
        client = OpenAICompatibleModelClient(
            model="m", base_url="http://x", api_key="k", timeout=5, retry_config=config
        )

        calls = {"n": 0}

        def fake_urlopen(req, timeout):
            calls["n"] += 1
            if calls["n"] < 2:
                raise urllib.error.HTTPError(
                    "http://x", 500, "err", {}, __import__("io").BytesIO(b"")
                )

            class R:
                def read(self):
                    return b'{"choices":[{"message":{"content":"<final>hi</final>"}}],"usage":{}}'

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            return R()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            resp = client.complete(ModelRequest(prompt="hi"))
        self.assertIn("hi", resp.text)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(len(sleeps), 1)


if __name__ == "__main__":
    unittest.main()
