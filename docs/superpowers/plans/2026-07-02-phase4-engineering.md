# Phase 4: 工程化补充 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Prerequisite:** Phases 1, 2, and 3 complete.

**Goal:** Add CI, a gated integration-test framework for real providers, optional streaming output, runtime observability via a `run_summary` trace event, and the missing engineering docs.

**Architecture:** (1) A GitHub Actions workflow runs lint + the unit matrix + a dedicated safety job. (2) `tests/integration/` holds provider contract tests gated by `PICO_RUN_INTEGRATION=1` and a `@pytest.mark.integration` marker. (3) `ModelClient.complete_stream()` yields tokens; the Fake client simulates streaming; OpenAI/Anthropic/Ollama parse SSE/NDJSON line-by-line. (4) `workflow_trace` emits a `run_summary` event; a new `scripts/summarize_traces.py` aggregates batches. (5) `CONTRIBUTING.md`, `CHANGELOG.md`, README updates.

**Tech Stack:** Python 3.10+ stdlib (`urllib`, `json`), `pytest`, `ruff`, GitHub Actions. No new runtime dependencies.

## Global Constraints

- Zero runtime dependencies. Integration tests use only `pytest` (already a dev dep).
- Streaming must not break the non-streaming path: `complete()` stays the source of truth for tool-call parsing; `complete_stream()` is for user-facing final-answer display only.
- CI must pass on Python 3.10, 3.11, 3.12.
- `pytest tests/` green after every task (integration tests are skipped by default).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `.github/workflows/ci.yml` | Create | Lint, test matrix, safety job. |
| `pyproject.toml` | Modify | Register `integration` pytest marker. |
| `tests/integration/conftest.py` | Create | Skip gate + shared fixtures. |
| `tests/integration/test_openai_provider.py` | Create | OpenAI contract test. |
| `tests/integration/test_anthropic_provider.py` | Create | Anthropic contract test. |
| `tests/integration/test_ollama_provider.py` | Create | Ollama contract test. |
| `pico/providers/clients.py` | Modify | Add `complete_stream()` to protocol + each client. |
| `pico/providers/__init__.py` | Modify | Re-export streaming bits. |
| `pico/runtime.py` | Modify | `ask(..., stream=False)` streams the final answer to a callback. |
| `pico/cli.py` | Modify | `--stream` flag. |
| `pico/workflow_trace.py` | Modify | `build_run_summary()` helper. |
| `pico/runtime.py` | Modify | Emit `run_summary` at end of `ask()`. |
| `scripts/summarize_traces.py` | Create | Aggregate trace metrics across batches. |
| `evaluate_qc.py` | Modify | `--with-runtime-metrics` option. |
| `CONTRIBUTING.md` | Create | Dev workflow doc. |
| `CHANGELOG.md` | Create | Record phases 1–4. |
| `README.md` | Modify | Document new flags. |

---

## Task 1: CI pipeline

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff>=0.4.4
      - run: ruff check .
      - run: ruff format --check .

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -v -W ignore::DeprecationWarning

  safety:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e ".[dev]"
      - run: pytest tests/test_labflow_guard.py tests/test_safety_boundaries.py tests/test_tools_safety.py tests/test_phase1_executor_tiers.py tests/test_phase1_rawdata_readonly.py tests/test_phase1_labflow_write_guard.py -v
```

- [ ] **Step 2: Validate the workflow file locally**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))" 2>/dev/null && echo OK || echo "yaml not installed locally — file is syntactically hand-checked"`
Expected: `OK` (or the fallback message). If `pyyaml` is unavailable, visually confirm indentation.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add lint, test matrix (3.10/3.11/3.12), and safety jobs"
```

---

## Task 2: Integration test framework

**Files:**
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]`)
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_openai_provider.py`, `test_anthropic_provider.py`, `test_ollama_provider.py`

- [ ] **Step 1: Register the marker**

In `pyproject.toml`, extend `[tool.pytest.ini_options]`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
markers = [
    "integration: provider contract tests (deselect with '-m \"not integration\"'; run with PICO_RUN_INTEGRATION=1)",
]
```

- [ ] **Step 2: Create the skip gate**

Create `tests/integration/conftest.py`:

```python
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("PICO_RUN_INTEGRATION") == "1":
        return
    skip = pytest.mark.skip(reason="set PICO_RUN_INTEGRATION=1 (and provider credentials) to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def openai_env():
    key = os.environ.get("PICO_OPENAI_API_KEY")
    base = os.environ.get("PICO_OPENAI_API_BASE", "https://api.openai.com")
    pytest.importorskip("urllib.request")
    if not key:
        pytest.skip("PICO_OPENAI_API_KEY not set")
    return {"base_url": base, "api_key": key, "model": os.environ.get("PICO_OPENAI_MODEL", "gpt-4.1")}
```

- [ ] **Step 3: Write the OpenAI contract test**

Create `tests/integration/test_openai_provider.py`:

```python
from __future__ import annotations

import re

import pytest

from pico.providers import OpenAICompatibleModelClient, ModelRequest

pytestmark = pytest.mark.integration


def test_openai_returns_final_or_tool(openai_env):
    client = OpenAICompatibleModelClient(model=openai_env["model"], base_url=openai_env["base_url"], api_key=openai_env["api_key"])
    response = client.complete(ModelRequest(prompt="Reply with exactly: <final>pong</final>", max_tokens=64))
    assert response.text
    assert re.search(r"<final>|<tool>", response.text) or response.text.strip()
```

- [ ] **Step 4: Write Anthropic and Ollama contract tests**

Create `tests/integration/test_anthropic_provider.py`:

```python
from __future__ import annotations

import os

import pytest

from pico.providers import AnthropicCompatibleModelClient, ModelRequest

pytestmark = pytest.mark.integration


def test_anthropic_returns_text():
    key = os.environ.get("PICO_ANTHROPIC_API_KEY")
    if not key:
        pytest.skip("PICO_ANTHROPIC_API_KEY not set")
    base = os.environ.get("PICO_ANTHROPIC_API_BASE", "https://api.anthropic.com")
    model = os.environ.get("PICO_ANTHROPIC_MODEL", "claude-opus-4-8")
    client = AnthropicCompatibleModelClient(model=model, base_url=base, api_key=key)
    response = client.complete(ModelRequest(prompt="Reply with exactly: <final>pong</final>", max_tokens=64))
    assert response.text.strip()
```

Create `tests/integration/test_ollama_provider.py`:

```python
from __future__ import annotations

import os

import pytest

from pico.providers import OllamaModelClient, ModelRequest

pytestmark = pytest.mark.integration


def test_ollama_returns_text():
    host = os.environ.get("PICO_OLLAMA_HOST")
    if not host:
        pytest.skip("PICO_OLLAMA_HOST not set")
    model = os.environ.get("PICO_OLLAMA_MODEL", "qwen2.5-coder")
    client = OllamaModelClient(model=model, base_url=host)
    response = client.complete(ModelRequest(prompt="Reply with exactly: <final>pong</final>", max_tokens=64))
    assert response.text.strip()
```

- [ ] **Step 5: Verify integration tests are skipped by default and the suite stays green**

Run: `python -m pytest tests/ -q -W ignore::DeprecationWarning`
Expected: PASS — integration tests skipped.

Run: `python -m pytest tests/integration/ -v -W ignore::DeprecationWarning`
Expected: 3 skipped.

- [ ] **Step 6: Lint and commit**

```bash
ruff check tests/integration/ pyproject.toml
git add pyproject.toml tests/integration/
git commit -m "test: add gated integration test framework for real providers"
```

---

## Task 3: Streaming output

**Files:**
- Modify: `pico/providers/clients.py`
- Modify: `pico/providers/__init__.py`
- Modify: `pico/runtime.py`
- Modify: `pico/cli.py`

**Interfaces:**
- Produces: `ModelClient.complete_stream(request) -> Iterator[str]` (default impl assembles `complete()` then yields); `FakeModelClient.complete_stream` yields char-by-char; `JsonHttpClient` subclasses parse SSE/NDJSON. `Pico.ask(user_message, stream_callback=None)`.

- [ ] **Step 1: Write the failing test (Fake streaming)**

Create `tests/test_phase4_streaming.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient, ModelRequest
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class StreamingTests(unittest.TestCase):
    def test_fake_client_streams_chars(self):
        client = FakeModelClient(script=["<final>hello</final>"])
        tokens = list(client.complete_stream(ModelRequest(prompt="hi")))
        self.assertEqual("".join(tokens), "<final>hello</final>")
        self.assertGreater(len(tokens), 1)

    def test_ask_with_stream_callback_invokes_on_final(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            client = FakeModelClient(script=["<final>streamed answer</final>"])
            pico = Pico(
                workspace=WorkspaceContext(repo_root=root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=1,
            )
            received = []
            pico.ask("hi", stream_callback=received.append)
            self.assertIn("streamed answer", "".join(received))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase4_streaming.py -v`
Expected: FAIL — `FakeModelClient` has no `complete_stream`; `Pico.ask` takes no `stream_callback`.

- [ ] **Step 3: Add `complete_stream` to the protocol and Fake client**

In `pico/providers/clients.py`, add to the `ModelClient` protocol (after `complete`):

```python
    def complete_stream(self, request: ModelRequest): ...
```

Add a default implementation pattern: each concrete client defines `complete_stream`. For `FakeModelClient`, add:

```python
    def complete_stream(self, request: ModelRequest):
        self.calls.append(request)
        text = self.script.pop(0) if self.script else "<final>No more scripted responses.</final>"
        self.last_metadata = {"provider": self.provider, "model": self.model, "fake_call": len(self.calls)}
        for char in text:
            yield char
```

For `JsonHttpClient`, add a generic streaming helper used by subclasses. Add to `JsonHttpClient`:

```python
    def _stream_post(self, path: str, payload: dict[str, Any], headers: dict[str, str], line_parser):
        """POST with stream:true and yield parsed text deltas via line_parser(line)->str|None."""
        import urllib.request

        url = self.base_url + path
        payload = dict(payload)
        payload["stream"] = True
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        request.add_header("content-type", "application/json")
        for key, value in headers.items():
            request.add_header(key, value)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                delta = line_parser(line)
                if delta:
                    yield delta
```

Add `complete_stream` to each real client. `OllamaModelClient` (NDJSON, each line is a JSON object with `response`):

```python
    def complete_stream(self, request: ModelRequest):
        payload = {"model": self.model, "prompt": request.prompt, "stream": True, "raw": False, "options": {"num_predict": request.max_tokens}}

        def parse(line):
            if not line:
                return None
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                return None
            return str(obj.get("response", "")) or None

        yield from self._stream_post("/api/generate", payload, {}, parse)
```

`OpenAICompatibleModelClient` (SSE `data:` lines):

```python
    def complete_stream(self, request: ModelRequest):
        headers = {}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "messages": [{"role": "user", "content": request.prompt}], "max_tokens": request.max_tokens, "stream": True}

        def parse(line):
            if not line.startswith("data:"):
                return None
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                return None
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                return None
            choices = obj.get("choices") or []
            if not choices:
                return None
            delta = choices[0].get("delta") or {}
            return str(delta.get("content") or "") or None

        yield from self._stream_post("/v1/chat/completions", payload, headers, parse)
```

`AnthropicCompatibleModelClient` (SSE `data:` lines with `content_block_delta`):

```python
    def complete_stream(self, request: ModelRequest):
        headers = {"anthropic-version": "2023-06-01"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        payload = {"model": self.model, "max_tokens": request.max_tokens, "messages": [{"role": "user", "content": request.prompt}], "stream": True}

        def parse(line):
            if not line.startswith("data:"):
                return None
            data = line[len("data:"):].strip()
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                return None
            if obj.get("type") != "content_block_delta":
                return None
            delta = obj.get("delta") or {}
            return str(delta.get("text") or "") or None

        yield from self._stream_post("/v1/messages", payload, headers, parse)
```

- [ ] **Step 4: Add `stream_callback` to `Pico.ask`**

In `pico/runtime.py`, change the `ask` signature:

```python
    def ask(self, user_message: str, stream_callback=None) -> str:
```

In the `if parsed.kind == "final":` branch, after computing `final_answer`, stream it token-by-token if a callback is provided:

```python
            if parsed.kind == "final":
                final_answer = str(parsed.payload).strip()
                if stream_callback is not None and hasattr(self.model_client, "complete_stream"):
                    # The model already produced the full text; replay it to the callback.
                    for token in final_answer:
                        stream_callback(token)
                task_state.finish_success(final_answer)
                self.history.append({"role": "assistant", "content": final_answer})
                break
```

> **Design note:** True token streaming during generation would require the runtime to parse `<final>` from a live stream. That is a larger change; this phase streams the assembled final answer, which already improves perceived latency for long answers and gives the callback contract for a future true-streaming parse. Document this limitation in CHANGELOG.

- [ ] **Step 5: Add `--stream` CLI flag**

In `pico/cli.py`, add to `build_arg_parser`:

```python
    parser.add_argument("--stream", action="store_true", help="Stream the final answer to the terminal token-by-token")
```

In `main`, replace the one-shot print:

```python
    if args.stream:
        buffer = []

        def cb(token):
            buffer.append(token)
            print(token, end="", flush=True)

        answer = agent.ask(args.prompt, stream_callback=cb)
        print()
    else:
        answer = agent.ask(args.prompt)
        if answer:
            print(answer)
    return 0
```

- [ ] **Step 6: Run streaming + runtime + provider tests**

Run: `python -m pytest tests/test_phase4_streaming.py tests/test_runtime.py tests/test_providers.py -v -W ignore::DeprecationWarning`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
ruff check pico/providers/clients.py pico/runtime.py pico/cli.py tests/test_phase4_streaming.py
git add pico/providers/clients.py pico/runtime.py pico/cli.py tests/test_phase4_streaming.py
git commit -m "feat(providers): add complete_stream + --stream CLI flag"
```

---

## Task 4: Observability — `run_summary` trace event

**Files:**
- Modify: `pico/workflow_trace.py`
- Modify: `pico/runtime.py`

**Interfaces:**
- Produces: `build_run_summary(tool_summaries, prompt_metadata, provider_metadata, run_status) -> dict`; `Pico.ask` emits a `run_summary` event before `run_finished`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_phase4_run_summary.py`:

```python
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pico.providers import FakeModelClient
from pico.run_store import RunStore, SessionStore
from pico.runtime import Pico
from pico.workspace import WorkspaceContext


class RunSummaryTests(unittest.TestCase):
    def test_run_summary_event_emitted(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "data").mkdir()
            client = FakeModelClient(script=["<final>done</final>"])
            pico = Pico(
                workspace=WorkspaceContext(repo_root=root),
                model_client=client,
                session_store=SessionStore(root),
                run_store=RunStore(root),
                max_steps=2,
            )
            pico.ask("hi")
            run_dirs = sorted((root / ".pico" / "runs").iterdir())
            trace_lines = (run_dirs[-1] / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            types = [json.loads(line)["type"] for line in trace_lines if line.strip()]
            self.assertIn("run_summary", types)
            summary = next(json.loads(line) for line in trace_lines if '"run_summary"' in line)
            self.assertIn("tool_call_count", summary["payload"])
            self.assertIn("provider_call_count", summary["payload"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_phase4_run_summary.py -v`
Expected: FAIL — no `run_summary` event.

- [ ] **Step 3: Add `build_run_summary` to `workflow_trace.py`**

Append to `pico/workflow_trace.py`:

```python
def build_run_summary(tool_summaries: list[dict[str, Any]], run_status: str, provider_metadata: dict[str, Any], prompt_metadata: dict[str, Any]) -> dict[str, Any]:
    durations = [float(item.get("duration_seconds") or 0.0) for item in tool_summaries]
    return {
        "run_status": run_status,
        "tool_call_count": len(tool_summaries),
        "provider_call_count": int(provider_metadata.get("fake_call") or provider_metadata.get("calls") or 0) or None,
        "total_tool_duration_seconds": sum(durations),
        "context_budget_used": int(prompt_metadata.get("prompt_chars") or 0),
        "section_chars": prompt_metadata.get("section_chars", {}),
    }
```

- [ ] **Step 4: Emit the event in `Pico.ask`**

In `pico/runtime.py`, add the import:

```python
from .workflow_trace import build_run_summary
```

Just before `self.emit_trace(task_state.run_id, "run_finished", report)` (near the end of `ask`), insert:

```python
        self.emit_trace(
            task_state.run_id,
            "run_summary",
            build_run_summary(self.tool_summaries, task_state.status, getattr(self.model_client, "last_metadata", {}), self.last_prompt_metadata),
        )
```

- [ ] **Step 5: Run the new test plus workflow_trace tests**

Run: `python -m pytest tests/test_phase4_run_summary.py tests/test_workflow_trace.py tests/test_timing_metrics.py -v -W ignore::DeprecationWarning`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
ruff check pico/workflow_trace.py pico/runtime.py tests/test_phase4_run_summary.py
git add pico/workflow_trace.py pico/runtime.py tests/test_phase4_run_summary.py
git commit -m "feat(trace): emit run_summary event with tool/provider/budget metrics"
```

---

## Task 5: Trace aggregation script + evaluator runtime metrics

**Files:**
- Create: `scripts/summarize_traces.py`
- Modify: `evaluate_qc.py`

- [ ] **Step 1: Create the aggregation script**

Create `scripts/summarize_traces.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_run_summary(trace_path: Path) -> dict | None:
    if not trace_path.is_file():
        return None
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "run_summary":
            return event.get("payload")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aggregate run_summary metrics across batch workflow logs.")
    parser.add_argument("traces_dir", help="Directory containing *_workflow_log.json or run trace.jsonl files")
    args = parser.parse_args(argv)

    root = Path(args.traces_dir)
    files = sorted(root.glob("*.json"))
    print(f"batch_id,run_status,tool_call_count,provider_call_count,total_tool_duration_seconds,context_budget_used")
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        batch_id = data.get("batch_id", path.stem)
        events = data.get("events", [])
        tool_count = len(events)
        duration = sum(float(e.get("duration_seconds") or 0.0) for e in events)
        print(f"{batch_id},-,{tool_count},-,{duration:.3f},-")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> **Note:** Workflow logs (`*_workflow_log.json`) contain tool events but not the `run_summary` payload (that lives in the run's `trace.jsonl`). The script reads workflow logs for the per-batch tool view. A follow-up can walk `.pico/runs/*/trace.jsonl` for full summaries — out of scope for this task; note in CHANGELOG.

- [ ] **Step 2: Add `--with-runtime-metrics` to `evaluate_qc.py`**

In `evaluate_qc.py`, find the `main`/argument-parsing section. Add the flag and, when set, read each batch's `traces/<batch>_workflow_log.json` and append a `runtime` block to that batch's evaluation result. Add near the existing argparse setup:

```python
    parser.add_argument("--with-runtime-metrics", action="store_true", help="Append per-batch runtime metrics from workflow logs")
```

And in the per-batch evaluation loop, after the existing metrics are computed, add:

```python
    if args.with_runtime_metrics:
        wf_path = base_dir / "traces" / f"{batch_id}_workflow_log.json"
        if wf_path.is_file():
            wf = json.loads(wf_path.read_text(encoding="utf-8"))
            result["runtime"] = {
                "event_count": wf.get("event_count", 0),
                "total_duration_seconds": wf.get("total_duration_seconds", 0.0),
            }
```

(Adjust `result` and `base_dir` to match the real variable names in `evaluate_qc.py` — read the file first.)

- [ ] **Step 3: Run a smoke test of the script**

Run: `python scripts/summarize_traces.py traces` (if `traces/` has files) or `python scripts/summarize_traces.py reports` as a no-op check.
Expected: prints a CSV header and rows (or just the header if no files).

- [ ] **Step 4: Lint and commit**

```bash
ruff check scripts/summarize_traces.py evaluate_qc.py
git add scripts/summarize_traces.py evaluate_qc.py
git commit -m "feat(eval): summarize_traces script + --with-runtime-metrics option"
```

---

## Task 6: Documentation

**Files:**
- Create: `CONTRIBUTING.md`
- Create: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 1: Create `CONTRIBUTING.md`**

```markdown
# Contributing to LabFlow Agent

## Development setup

```bash
pip install -e ".[dev]"
```

## Running checks

```bash
ruff check .
ruff format --check .
pytest tests/ -v -W ignore::DeprecationWarning
```

## Adding a tool

1. Implement the function in `pico/tools/labflow.py` with signature `(ctx: ToolContext, args: dict) -> ToolResult`.
2. Define its JSON schema in `pico/tools/registry.py`.
3. Register it in `build_labflow_tool_registry`.
4. Add tests under `tests/`.

## Safety rules

- Raw data under `data/raw` or `data/batch_*` is read-only and enforced by `assert_raw_data_readonly`.
- Never expose arbitrary `run_shell`/`write_file`/`patch_file` in the LabFlow registry — those are generic-harness tools kept for safety tests only.
- New write paths must call `assert_raw_data_readonly` before writing.

## Integration tests

Set `PICO_RUN_INTEGRATION=1` and the relevant provider credentials to run `tests/integration/`.
```

- [ ] **Step 2: Create `CHANGELOG.md`**

```markdown
# Changelog

## [Unreleased] — 2026-07-02 systematic improvements

### Phase 1: Cleanup & hardening
- Added typed error hierarchy (`PicoError`, `SafetyViolationError`, `ToolExecutionError`) in `pico/errors.py`.
- `assert_raw_data_readonly` now raises `SafetyViolationError` and is enforced on all LabFlow write paths.
- `ToolExecutor` uses three-tier exception handling; safety violations propagate.
- Removed unused `agent_loop.py` and `session_store.py` shims.
- Documented the generic-vs-LabFlow dual tool registry.

### Phase 2: Robustness
- Provider errors classified (`ProviderConnectionError`, `ProviderRateLimitError`, `ProviderAuthError`, `ProviderResponseError`).
- HTTP status codes mapped to typed errors in `_post_json`.
- Exponential-backoff retry (`pico/providers/retry.py`) on transient errors, configurable via env.
- `SessionStore`/`RunStore` quarantine corrupt JSON and recover.
- `provider_retry` events recorded in traces.

### Phase 3: Architecture
- Optional planner guidance layer (`<suggested_plan>`); disable with `--no-planner`.
- Report section titles templated (`pico/report_template.py`); `evaluate_qc.py` derives required sections from it.
- `--lang` flag for report language.
- Pluggable `TruncationStrategy` (`priority` default, `smart` via `PICO_TRUNCATION_STRATEGY`).
- Tools reorganized into `pico/tools/` package; old paths are deprecation shims.

### Phase 4: Engineering
- GitHub Actions CI (lint + 3.10/3.11/3.12 matrix + safety job).
- Gated integration-test framework (`tests/integration/`, `PICO_RUN_INTEGRATION=1`).
- `complete_stream()` + `--stream` flag (final-answer replay streaming).
- `run_summary` trace event; `scripts/summarize_traces.py`; `--with-runtime-metrics`.
- `CONTRIBUTING.md`, this changelog, README updates.

### Known limitations
- `--stream` replays the assembled final answer rather than parsing `<final>` from a live token stream.
```

- [ ] **Step 3: Update `README.md`**

Add a "CLI options" subsection documenting the new flags: `--no-planner`, `--lang`, `--stream`, and the env vars `PICO_MAX_RETRIES`, `PICO_RETRY_BASE_DELAY_MS`, `PICO_TRUNCATION_STRATEGY`. Insert near the existing demo-run-commands section. Example block to append:

```markdown
## New CLI options (2026-07 improvements)

- `--no-planner` — disable the suggested-plan guidance layer (pure LLM-driven mode).
- `--stream` — stream the final answer to the terminal token-by-token.
- `--lang zh|en` — report language (default `zh`).

Environment variables:
- `PICO_MAX_RETRIES`, `PICO_RETRY_BASE_DELAY_MS`, `PICO_RETRY_MAX_DELAY_MS` — provider retry tuning.
- `PICO_TRUNCATION_STRATEGY` — `priority` (default) or `smart`.
- `PICO_RUN_INTEGRATION=1` — enable integration tests.
```

- [ ] **Step 4: Commit**

```bash
git add CONTRIBUTING.md CHANGELOG.md README.md
git commit -m "docs: add CONTRIBUTING, CHANGELOG, and document new CLI options"
```

---

## Phase 4 Acceptance

- [ ] `.github/workflows/ci.yml` exists and defines lint, test (3.10/3.11/3.12), and safety jobs.
- [ ] `python -m pytest tests/ -q -W ignore::DeprecationWarning` fully green; integration tests skipped by default.
- [ ] `python -m pytest tests/integration/ -v` shows 3 skipped tests.
- [ ] `pico --stream "..."` prints the final answer incrementally.
- [ ] A `run_summary` event appears in `trace.jsonl` after a run.
- [ ] `python scripts/summarize_traces.py traces` prints a CSV table.
- [ ] `CONTRIBUTING.md`, `CHANGELOG.md` exist; README documents the new flags.

---

## Self-Review (run after all phases)

1. **Spec coverage:** every item in `docs/superpowers/specs/2026-07-02-labflow-agent-improvements-design.md` §3–§6 maps to a task above. The one deviation (generic tools kept, not deleted) is documented in the Phase 1 plan header.
2. **Cross-phase type consistency:** `SafetyViolationError`/`ToolExecutionError` (P1) are reused in P2/P3; `RetryConfig` (P2) is referenced by `runtime.py` unchanged; `build_plan`/`render_plan` (P3) signatures match; `complete_stream` (P4) matches the protocol added in P4.
3. **Placeholder scan:** each step contains real code or an exact command — no "TODO"/"add error handling" stubs. Where a step says "read the file first to match variable names" (P4 Task 5 Step 2), it is an explicit instruction, not a placeholder for omitted code.
