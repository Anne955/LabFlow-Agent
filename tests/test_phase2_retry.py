from __future__ import annotations

import unittest

from pico.errors import ProviderAuthError, ProviderConnectionError
from pico.providers.retry import RetryConfig, with_retry


class RetryTests(unittest.TestCase):
    def test_retries_on_retryable_then_succeeds(self):
        calls = []

        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise ProviderConnectionError("transient")
            return "ok"

        sleeps = []
        config = RetryConfig(max_retries=3, base_delay_ms=10, max_delay_ms=100, sleep=sleeps.append)
        result = with_retry(fn, config)
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(sleeps), 2)  # slept before attempt 2 and 3

    def test_does_not_retry_terminal_error(self):
        calls = []

        def fn():
            calls.append(1)
            raise ProviderAuthError("bad key")

        config = RetryConfig(max_retries=3, sleep=lambda _ms: None)
        with self.assertRaises(ProviderAuthError):
            with_retry(fn, config)
        self.assertEqual(len(calls), 1)

    def test_gives_up_after_max_retries(self):
        calls = []

        def fn():
            calls.append(1)
            raise ProviderConnectionError("down")

        config = RetryConfig(max_retries=2, base_delay_ms=1, max_delay_ms=2, sleep=lambda _ms: None)
        with self.assertRaises(ProviderConnectionError):
            with_retry(fn, config)
        self.assertEqual(len(calls), 3)  # initial + 2 retries

    def test_backoff_is_capped(self):
        sleeps = []
        config = RetryConfig(
            max_retries=4, base_delay_ms=1000, max_delay_ms=500, sleep=sleeps.append, rng=lambda: 0
        )

        def fn():
            raise ProviderConnectionError("x")

        with self.assertRaises(ProviderConnectionError):
            with_retry(fn, config)
        for delay in sleeps:
            self.assertLessEqual(delay, 500)


if __name__ == "__main__":
    unittest.main()
