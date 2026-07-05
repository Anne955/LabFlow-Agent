# Changelog

## [Unreleased] — 2026-07-02 systematic improvements

### Breaking changes
- `ModelProviderError` now subclasses `PicoError` (which subclasses `Exception`) instead of
  `RuntimeError`. The runtime's own `except ModelProviderError` handler is unaffected, but
  external callers that relied on `except RuntimeError` to catch provider failures must switch
  to `except ModelProviderError` (or `except PicoError`). All provider error subclasses
  (`ProviderConnectionError`, `ProviderRateLimitError`, `ProviderAuthError`,
  `ProviderResponseError`) inherit from `ModelProviderError` and so are affected too.

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
- Report language selectable via the `generate_report` tool's `lang` argument (`zh`/`en`, default `zh`).
- Pluggable, env-selectable `TruncationStrategy` (`PICO_TRUNCATION_STRATEGY`=`priority` default or `smart`). `smart` is intent-aware: it reads the detected intent (from the planner, or `detect_intent` when the planner is off) and, for `explain_finding`, trims history last and raises its budget share to 0.25 (vs 0.2 under `priority`), retaining more context for explanations.
- Tools reorganized into `pico/tools/` package; old paths are deprecation shims.

### Phase 4: Engineering
- GitHub Actions CI (lint + 3.10/3.11/3.12 matrix + safety job).
- Gated integration-test framework (`tests/integration/`, `PICO_RUN_INTEGRATION=1`).
- `complete_stream()` + `--stream` flag (final-answer replay streaming).
- Real-client `complete_stream` SSE/NDJSON line parsers extracted to module-level functions (`parse_ollama_stream_line`, `parse_openai_stream_line`, `parse_anthropic_stream_line`) and covered by fixture-based unit tests.
- `run_summary` trace event; `scripts/summarize_traces.py`; `--with-runtime-metrics`.
- `--lang zh|en` CLI flag now available; threads CLI → `Pico.report_lang` → `ToolContext.default_report_lang` → `generate_report` default. The `generate_report` tool's `lang` argument still takes precedence when passed.
- `CONTRIBUTING.md`, this changelog, README updates.

### Known limitations
- `complete_stream()` is provisional: the runtime does not invoke it (the `--stream` flag replays the assembled final answer) and the streaming HTTP path does not use `with_retry`. The real-client SSE/NDJSON line parsers are unit-tested in `tests/test_followup2_stream_parsers.py`.
- `--stream` replays the assembled final answer rather than parsing `<final>` from a live token stream.
