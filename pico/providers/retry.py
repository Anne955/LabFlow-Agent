from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from ..errors import ProviderConnectionError, ProviderRateLimitError

T = TypeVar("T")


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 10_000
    retryable_errors: tuple = (ProviderConnectionError, ProviderRateLimitError)
    sleep: Callable[[float], None] = field(default=time.sleep)
    rng: Callable[[], int] = field(default=lambda: random.randint(0, 250))


def with_retry(
    fn: Callable[[], T],
    config: RetryConfig,
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Call fn(), retrying on retryable errors with exponential backoff + jitter.

    Raises the last error if all attempts are exhausted or a terminal error occurs.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except config.retryable_errors as exc:
            attempt += 1
            if attempt > config.max_retries:
                raise
            if on_retry is not None:
                on_retry(attempt, exc)
            delay_ms = min(
                config.base_delay_ms * (2 ** (attempt - 1)) + config.rng(),
                config.max_delay_ms,
            )
            config.sleep(delay_ms / 1000.0)
