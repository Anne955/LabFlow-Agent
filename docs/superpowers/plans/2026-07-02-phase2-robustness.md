# Phase 2: 健壮性提升 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Phase 1 complete (`pico/errors.py` exists with `PicoError`, `SafetyViolationError`, `ToolExecutionError`).

**Goal:** Make provider calls resilient to transient network errors, classify all provider errors into retryable vs. terminal, and make session/run storage self-heal when a JSON file is corrupt instead of crashing the run.

**Architecture:** Extend `pico/errors.py` with `ModelProviderError` subclasses. Add `pico/providers/retry.py` — a zero-dependency exponential-backoff helper that retries only on retryable errors. Map HTTP status codes in `JsonHttpClient._post_json` to the right subclass. Wrap `RunStore`/`SessionStore` JSON reads with a corruption-recovery path that quarantines bad files.

**Tech Stack:** Python 3.10+ stdlib (`urllib`, `time`, `random`, `json`), `unittest`, `ruff`.

## Global Constraints

- Zero external dependencies. Retry uses `time.sleep` + `random.randint` only.
- `ModelProviderError` remains the base the runtime catches; subclasses must stay `issubclass` of it so `runtime.py:109` keeps working unchanged.
- `pytest tests/` green after every task.
- Retry must be deterministic-testable: the `RetryConfig` accepts an injectable `sleep` callable and `random` source so tests don't actually sleep.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `pico/errors.py` | Modify | Add `ProviderConnectionError`, `ProviderRateLimitError`, `ProviderAuthError`, `ProviderResponseError` under `ModelProviderError`. |
| `pico/providers/clients.py` | Modify | `_post_json` maps HTTP 429/5xx/OSError to the right subclass; re-exports unchanged. |
| `pico/providers/retry.py` | Create | `RetryConfig` + `with_retry()` helper (injectable sleep/random). |
| `pico/providers/__init__.py` | Modify | Re-export retry helpers and error subclasses. |
| `pico/config.py` | Modify | Add `DEFAULT_RETRY_CONFIG` constants and env-driven `load_retry_config()`. |
| `pico/providers/clients.py` | Modify | `complete()` methods wrap `_post_json` in `with_retry`. |
| `pico/run_store.py` | Modify | `SessionStore.load` quarantines corrupt files; add `RunStore.load_task_state`. |
| `tests/test_phase2_*.py` | Create | New tests for retry, error mapping, corruption recovery. |

---

## Task 1: Add provider error subclasses

**Files:**
- Modify: `pico/errors.py`

**Interfaces:**
- Produces: `ProviderConnectionError`, `ProviderRateLimitError`, `ProviderAuthError`, `ProviderResponseError`, all subclassing `ModelProviderError` (which must be added too — currently it lives in `pico/providers/clients.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase2_provider_errors.py`:

```python
from __future__ import annotations

import unittest

from pico.errors import (
    ModelProviderError,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
)


class ProviderErrorHierarchyTests(unittest.TestCase):
    def test_all_subclass_model_provider_error(self):
        for cls in (ProviderConnectionError, ProviderRateLimitError, ProviderAuthError, ProviderResponseError):
            self.assertTrue(issubclass(cls, ModelProviderError))

    def test_auth_is_not_connection(self):
        self.assertNotIsSubclass(ProviderAuthError, ProviderConnectionError)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_provider_errors.py -v`
Expected: FAIL — `ImportError: cannot import name 'ModelProviderError' ... from pico.errors`.

- [ ] **Step 3: Add the hierarchy to `pico/errors.py`**

Append to `pico/errors.py`:

```python
class ModelProviderError(PicoError):
    """Base class for all LLM provider failures."""


class ProviderConnectionError(ModelProviderError):
    """Transient network/timeout error — safe to retry."""


class ProviderRateLimitError(ModelProviderError):
    """HTTP 429 — safe to retry with backoff."""


class ProviderAuthError(ModelProviderError):
    """HTTP 401/403 — terminal; do not retry."""


class ProviderResponseError(ModelProviderError):
    """Other non-retryable provider error (4xx except 429, malformed response)."""
```

Then make `pico/providers/clients.py` re-export from `errors` instead of defining its own. In `pico/providers/clients.py`, replace:

```python
class ModelProviderError(RuntimeError):
    pass
```

with:

```python
from ..errors import (
    ModelProviderError,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
)
```

Keep `ModelProviderError` re-exported from `pico.providers` (it already is in `__init__.py`).

- [ ] **Step 4: Run the new test plus existing provider tests**

Run: `python -m pytest tests/test_phase2_provider_errors.py tests/test_providers.py tests/test_runtime.py -v`
Expected: PASS. `ModelProviderError` is now a `PicoError` (subclass of `Exception`), so `runtime.py`'s `except ModelProviderError` still catches it.

- [ ] **Step 5: Lint and commit**

```bash
ruff check pico/errors.py pico/providers/clients.py tests/test_phase2_provider_errors.py
git add pico/errors.py pico/providers/clients.py tests/test_phase2_provider_errors.py
git commit -m "feat(errors): add ModelProviderError subclasses for retry classification"
```

---

## Task 2: Map HTTP errors to the right subclass in `_post_json`

**Files:**
- Modify: `pico/providers/clients.py:69-87` (`JsonHttpClient._post_json`)

**Interfaces:**
- Produces: `_post_json` raises `ProviderRateLimitError` on 429, `ProviderAuthError` on 401/403, `ProviderResponseError` on other 4xx, `ProviderConnectionError` on `OSError`/`TimeoutError`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase2_http_mapping.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import patch
import urllib.error

from pico.errors import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
)
from pico.providers.clients import OpenAICompatibleModelClient, ModelRequest


def make_client():
    return OpenAICompatibleModelClient(model="m", base_url="http://x", api_key="k", timeout=5)


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_http_mapping.py -v`
Expected: FAIL — current code raises plain `ModelProviderError` for all HTTP errors and `OSError`.

- [ ] **Step 3: Rewrite the except block in `_post_json`**

Replace the `try/except` in `_post_json` (current lines 76-87) with:

```python
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                raise ProviderRateLimitError(f"HTTP 429 from {url}: {detail}") from exc
            if exc.code in (401, 403):
                raise ProviderAuthError(f"HTTP {exc.code} from {url}: {detail}") from exc
            if 500 <= exc.code < 600:
                raise ProviderConnectionError(f"HTTP {exc.code} from {url}: {detail}") from exc
            raise ProviderResponseError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except (OSError, TimeoutError) as exc:
            raise ProviderConnectionError(f"request failed for {url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"non-JSON response from {url}: {raw[:500]}") from exc
```

- [ ] **Step 4: Run the new test plus provider tests**

Run: `python -m pytest tests/test_phase2_http_mapping.py tests/test_providers.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check pico/providers/clients.py tests/test_phase2_http_mapping.py
git add pico/providers/clients.py tests/test_phase2_http_mapping.py
git commit -m "feat(providers): map HTTP status codes to typed provider errors"
```

---

## Task 3: Create the retry helper

**Files:**
- Create: `pico/providers/retry.py`

**Interfaces:**
- Produces: `RetryConfig(max_retries, base_delay_ms, max_delay_ms, retryable_errors, sleep, rng)` and `with_retry(fn, config, on_retry=None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase2_retry.py`:

```python
from __future__ import annotations

import unittest

from pico.errors import ProviderConnectionError, ProviderAuthError
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
        config = RetryConfig(max_retries=4, base_delay_ms=1000, max_delay_ms=500, sleep=sleeps.append, rng=lambda: 0)

        def fn():
            raise ProviderConnectionError("x")

        with self.assertRaises(ProviderConnectionError):
            with_retry(fn, config)
        for delay in sleeps:
            self.assertLessEqual(delay, 500)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_retry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pico.providers.retry'`.

- [ ] **Step 3: Write `pico/providers/retry.py`**

```python
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


def with_retry(fn: Callable[[], T], config: RetryConfig, on_retry: Callable[[int, BaseException], None] | None = None) -> T:
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
            delay_ms = min(config.base_delay_ms * (2 ** (attempt - 1)) + config.rng(), config.max_delay_ms)
            config.sleep(delay_ms / 1000.0)
```

- [ ] **Step 4: Re-export from the providers package**

In `pico/providers/__init__.py`, add to the imports from `.clients` and add a new import line:

```python
from .retry import RetryConfig, with_retry
```

and extend `__all__` with `"RetryConfig"`, `"with_retry"`, plus the four new error classes if not already present:

```python
    "ProviderAuthError",
    "ProviderConnectionError",
    "ProviderRateLimitError",
    "ProviderResponseError",
```

(Import them from `..errors` via `from ..errors import (...)` at the top of `__init__.py`.)

- [ ] **Step 5: Run the new test**

Run: `python -m pytest tests/test_phase2_retry.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/providers/retry.py pico/providers/__init__.py tests/test_phase2_retry.py
git add pico/providers/retry.py pico/providers/__init__.py tests/test_phase2_retry.py
git commit -m "feat(providers): add RetryConfig and with_retry backoff helper"
```

---

## Task 4: Apply retry to provider `complete()` calls

**Files:**
- Modify: `pico/providers/clients.py` (`OllamaModelClient`, `OpenAICompatibleModelClient`, `AnthropicCompatibleModelClient`)
- Modify: `pico/config.py`

**Interfaces:**
- Consumes: `with_retry`, `RetryConfig` from Task 3.
- Produces: each provider's `complete()` retries `_post_json` per a `RetryConfig` stored on the client; `runtime.py` is unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase2_provider_retry_integration.py`:

```python
from __future__ import annotations

import unittest
from unittest.mock import patch
import urllib.error

from pico.errors import ProviderConnectionError
from pico.providers.clients import OpenAICompatibleModelClient, ModelRequest
from pico.providers.retry import RetryConfig


class ProviderRetryIntegrationTests(unittest.TestCase):
    def test_complete_retries_transient_then_returns(self):
        sleeps = []
        config = RetryConfig(max_retries=2, base_delay_ms=1, max_delay_ms=2, sleep=sleeps.append, rng=lambda: 0)
        client = OpenAICompatibleModelClient(model="m", base_url="http://x", api_key="k", timeout=5, retry_config=config)

        calls = {"n": 0}

        def fake_urlopen(req, timeout):
            calls["n"] += 1
            if calls["n"] < 2:
                raise urllib.error.HTTPError("http://x", 500, "err", {}, __import__("io").BytesIO(b""))

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_provider_retry_integration.py -v`
Expected: FAIL — `OpenAICompatibleModelClient.__init__` does not accept `retry_config`, and no retry happens.

- [ ] **Step 3: Add `retry_config` to `JsonHttpClient` and wrap `complete()`**

In `pico/providers/clients.py`, add the import at top:

```python
from .retry import RetryConfig, with_retry
```

In `JsonHttpClient.__init__`, add parameter and storage. Change the signature and body:

```python
    def __init__(self, model: str, base_url: str, api_key: str | None = None, timeout: int = 60, retry_config: RetryConfig | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retry_config = retry_config or RetryConfig()
        self.last_metadata: dict[str, Any] = {}
```

In each of the three subclasses' `complete()` methods, wrap the `raw = self._post_json(...)` call. For `OpenAICompatibleModelClient.complete`, replace:

```python
        raw = self._post_json("/v1/chat/completions", payload, headers)
```

with:

```python
        raw = with_retry(lambda: self._post_json("/v1/chat/completions", payload, headers), self.retry_config)
```

Do the equivalent for `OllamaModelClient` (`"/api/generate"`) and `AnthropicCompatibleModelClient` (`"/v1/messages"`).

- [ ] **Step 4: Add env-driven defaults in `config.py`**

Append to `pico/config.py`:

```python
DEFAULT_RETRY_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY_MS = 500
DEFAULT_RETRY_MAX_DELAY_MS = 10_000


def load_retry_config():
    from .providers.retry import RetryConfig

    return RetryConfig(
        max_retries=int(env_or(str(DEFAULT_RETRY_MAX_RETRIES), "PICO_MAX_RETRIES")),
        base_delay_ms=int(env_or(str(DEFAULT_RETRY_BASE_DELAY_MS), "PICO_RETRY_BASE_DELAY_MS")),
        max_delay_ms=int(env_or(str(DEFAULT_RETRY_MAX_DELAY_MS), "PICO_RETRY_MAX_DELAY_MS")),
    )
```

- [ ] **Step 5: Run the new test plus provider and runtime tests**

Run: `python -m pytest tests/test_phase2_provider_retry_integration.py tests/test_providers.py tests/test_runtime.py -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/providers/clients.py pico/config.py tests/test_phase2_provider_retry_integration.py
git add pico/providers/clients.py pico/config.py tests/test_phase2_provider_retry_integration.py
git commit -m "feat(providers): retry transient failures with exponential backoff"
```

---

## Task 5: Storage corruption recovery

**Files:**
- Modify: `pico/run_store.py` (`SessionStore.load`, add `RunStore.load_task_state`)

**Interfaces:**
- Produces: `SessionStore.load(session_id)` returns a fresh empty session dict if the file is corrupt (and quarantines the bad file as `<id>.corrupted.<ms>.json`); `RunStore.load_task_state(run_id)` does the same.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase2_storage_recovery.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.run_store import RunStore, SessionStore
from pico.task_state import TaskState


class StorageRecoveryTests(unittest.TestCase):
    def test_session_load_quarantines_corrupt_file(self):
        with TemporaryDirectory() as d:
            store = SessionStore(Path(d))
            path = store.path_for("s1")
            path.write_text("{not valid json", encoding="utf-8")
            loaded = store.load("s1")
            self.assertEqual(loaded.get("id"), "s1")
            quarantined = list(store.root.glob("s1.corrupted.*.json"))
            self.assertEqual(len(quarantined), 1)

    def test_run_load_task_state_recovers(self):
        with TemporaryDirectory() as d:
            store = RunStore(Path(d))
            run_dir = store.run_dir("r1")
            run_dir.mkdir(parents=True)
            (run_dir / "task_state.json").write_text("broken{", encoding="utf-8")
            state = store.load_task_state("r1")
            self.assertIsInstance(state, TaskState)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_storage_recovery.py -v`
Expected: FAIL — `SessionStore.load` raises `json.JSONDecodeError`; `RunStore` has no `load_task_state`.

- [ ] **Step 3: Add a quarantine helper and update `SessionStore.load`**

In `pico/run_store.py`, add import `import time` at the top (after `import json`). Add a module-level helper:

```python
def _quarantine(path: Path) -> None:
    """Rename a corrupt file aside so the next read starts clean. Never raises."""
    try:
        stamp = int(time.time() * 1000)
        path.rename(path.with_name(f"{path.stem}.corrupted.{stamp}{path.suffix}"))
    except OSError:
        pass
```

Replace `SessionStore.load` (current lines 33-35) with:

```python
    def load(self, session_id: str) -> dict[str, Any]:
        path = self.path_for(session_id)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _quarantine(path)
            return {"id": session_id, "history": [], "memory": {}}
```

Add `load_task_state` to `RunStore` (after `write_task_state`):

```python
    def load_task_state(self, run_id: str) -> TaskState:
        path = self.run_dir(run_id) / "task_state.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskState.from_dict(data)
        except (OSError, json.JSONDecodeError):
            _quarantine(path)
            return TaskState.create("recovered task")
```

- [ ] **Step 4: Add `TaskState.from_dict` if missing**

Check `pico/task_state.py`. If `TaskState` already has a `from_dict` classmethod, skip. Otherwise add:

```python
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskState":
        state = cls.create(str(data.get("task_id") or data.get("request") or "recovered task"))
        state.run_id = str(data.get("run_id", state.run_id))
        state.status = str(data.get("status", state.status))
        state.attempts = int(data.get("attempts", 0))
        state.tool_steps = int(data.get("tool_steps", 0))
        state.final_answer = str(data.get("final_answer", ""))
        return state
```

(Read `pico/task_state.py` first to match the real attribute names before writing this.)

- [ ] **Step 5: Run the new test plus the stores suite**

Run: `python -m pytest tests/test_phase2_storage_recovery.py tests/test_stores.py -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/run_store.py pico/task_state.py tests/test_phase2_storage_recovery.py
git add pico/run_store.py pico/task_state.py tests/test_phase2_storage_recovery.py
git commit -m "feat(stores): quarantine corrupt JSON and recover with fresh state"
```

---

## Task 6: Record retries and errors in the trace

**Files:**
- Modify: `pico/runtime.py:100-112` (the `except ModelProviderError` block)

**Interfaces:**
- Produces: when a provider call retries, a `provider_retry` trace event is emitted; the final terminal error keeps the existing `model_error` event.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase2_retry_trace.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import urllib.error

from pico.providers import FakeModelClient
from pico.providers.clients import OpenAICompatibleModelClient
from pico.providers.retry import RetryConfig
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class RetryTraceTests(unittest.TestCase):
    def test_retry_event_emitted_then_success(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            client = OpenAICompatibleModelClient(
                model="m", base_url="http://x", api_key="k", timeout=5,
                retry_config=RetryConfig(max_retries=2, base_delay_ms=1, max_delay_ms=2, sleep=lambda _s: None, rng=lambda: 0),
            )
            pico = Pico(
                workspace=WorkspaceContext(repo_root=root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
            )
            calls = {"n": 0}

            def fake_urlopen(req, timeout):
                calls["n"] += 1
                if calls["n"] < 2:
                    raise urllib.error.HTTPError("http://x", 500, "err", {}, __import__("io").BytesIO(b""))

                class R:
                    def read(self):
                        return b'{"choices":[{"message":{"content":"<final>done</final>"}}],"usage":{}}'

                    def __enter__(self):
                        return self

                    def __exit__(self, *a):
                        return False

                return R()

            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                pico.ask("hi")

            run_id = pico.run_store.root  # placeholder; read the latest run dir instead
            run_dirs = sorted((root / ".pico" / "runs").iterdir())
            trace_lines = (run_dirs[-1] / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            types = [__import__("json").loads(line)["type"] for line in trace_lines if line.strip()]
            self.assertIn("provider_retry", types)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase2_retry_trace.py -v`
Expected: FAIL — no `provider_retry` event is emitted.

- [ ] **Step 3: Wire `on_retry` into the runtime**

This requires the runtime to pass an `on_retry` callback. The cleanest minimal change: give `Pico` a `retry_callback` that emits a trace event, and have provider clients call it. However, the clients call `with_retry` internally without runtime knowledge. 

Simplest approach that satisfies the test without rewiring client construction: add a `last_retry_events: list` attribute on the client's `retry_config`-bound callback. But the runtime owns the trace.

**Adjusted approach:** expose retry events via the client. Add `self.retry_events: list[dict] = []` to `JsonHttpClient.__init__`. Pass an `on_retry` to `with_retry` that appends to `self.retry_events`:

```python
        raw = with_retry(
            lambda: self._post_json("/v1/chat/completions", payload, headers),
            self.retry_config,
            on_retry=lambda attempt, exc: self.retry_events.append({"attempt": attempt, "error": str(exc)}),
        )
```

Then in `runtime.py`, after a successful `model_client.complete(...)`, flush any pending retry events to the trace. In `runtime.py`, after the `model_completed` emit block (after line 117), insert:

```python
            for evt in getattr(self.model_client, "retry_events", [])[:]:
                self.emit_trace(task_state.run_id, "provider_retry", evt)
            if hasattr(self.model_client, "retry_events"):
                self.model_client.retry_events.clear()
```

- [ ] **Step 4: Run the new test plus the runtime suite**

Run: `python -m pytest tests/test_phase2_retry_trace.py tests/test_runtime.py -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check pico/providers/clients.py pico/runtime.py tests/test_phase2_retry_trace.py
git add pico/providers/clients.py pico/runtime.py tests/test_phase2_retry_trace.py
git commit -m "feat(runtime): emit provider_retry trace events"
```

---

## Phase 2 Acceptance

- [ ] `python -m pytest tests/ -q` fully green.
- [ ] `ruff check .` clean.
- [ ] A transient HTTP 500 is retried up to `max_retries` times before failing (verified by test).
- [ ] HTTP 401 fails immediately with no retry (verified by test).
- [ ] A corrupt `sessions/<id>.json` is quarantined and `SessionStore.load` returns a fresh session instead of crashing (verified by test).
- [ ] `provider_retry` events appear in `trace.jsonl` when a retry occurs.
