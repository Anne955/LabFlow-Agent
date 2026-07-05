from __future__ import annotations

import unittest
from unittest.mock import patch

from pico.providers.clients import ModelRequest, OpenAICompatibleModelClient
from pico.providers.retry import RetryConfig
from pico.workflow_trace import build_run_summary


class ProviderCallCountTests(unittest.TestCase):
    def _fake_urlopen(self):
        class R:
            def read(self):
                return b'{"choices":[{"message":{"content":"<final>hi</final>"}}],"usage":{}}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return lambda req, timeout: R()

    def test_complete_increments_call_count_and_build_run_summary_reads_it(self):
        client = OpenAICompatibleModelClient(
            model="m",
            base_url="http://x",
            api_key="k",
            timeout=5,
            retry_config=RetryConfig(max_retries=0),
        )
        with patch("urllib.request.urlopen", side_effect=self._fake_urlopen()):
            client.complete(ModelRequest(prompt="hi"))
            client.complete(ModelRequest(prompt="again"))

        self.assertEqual(client.last_metadata["calls"], 2)
        summary = build_run_summary([], "success", client.last_metadata, {})
        self.assertEqual(summary["provider_call_count"], 2)


if __name__ == "__main__":
    unittest.main()
