from __future__ import annotations

import unittest
import urllib.error
from unittest.mock import patch

from pico.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
)
from pico.providers.clients import ModelRequest, OpenAICompatibleModelClient
from pico.providers.retry import RetryConfig


def make_client():
    # max_retries=0 so retryable errors propagate on the first attempt without
    # sleeping. These tests assert error MAPPING, not retry behavior.
    return OpenAICompatibleModelClient(
        model="m",
        base_url="http://x",
        api_key="k",
        timeout=5,
        retry_config=RetryConfig(max_retries=0),
    )


class HttpMappingTests(unittest.TestCase):
    def _http_error(self, code, body=b""):
        return urllib.error.HTTPError("http://x", code, "err", {}, __import__("io").BytesIO(body))

    def test_429_maps_to_rate_limit(self):
        client = make_client()
        with patch("urllib.request.urlopen", side_effect=self._http_error(429)):
            with self.assertRaises(ProviderRateLimitError):
                client.complete(ModelRequest(prompt="hi"))

    def test_401_maps_to_auth(self):
        client = make_client()
        with patch("urllib.request.urlopen", side_effect=self._http_error(401)):
            with self.assertRaises(ProviderAuthError):
                client.complete(ModelRequest(prompt="hi"))

    def test_500_maps_to_connection(self):
        client = make_client()
        with patch("urllib.request.urlopen", side_effect=self._http_error(500)):
            with self.assertRaises(ProviderConnectionError):
                client.complete(ModelRequest(prompt="hi"))

    def test_400_maps_to_response(self):
        client = make_client()
        with patch("urllib.request.urlopen", side_effect=self._http_error(400)):
            with self.assertRaises(ProviderResponseError):
                client.complete(ModelRequest(prompt="hi"))

    def test_oserror_maps_to_connection(self):
        client = make_client()
        with patch("urllib.request.urlopen", side_effect=OSError("refused")):
            with self.assertRaises(ProviderConnectionError):
                client.complete(ModelRequest(prompt="hi"))


if __name__ == "__main__":
    unittest.main()
