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
- Report language selectable via the `generate_report` tool's `lang` argument (`zh`/`en`, default `zh`).
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
- `PICO_TRUNCATION_STRATEGY=smart` is not yet wired into `build_prompt`: the `SmartTruncation` strategy class and `load_truncation_strategy()` loader exist, but `pico/context_manager.py::build_prompt` still constructs a `PriorityTruncation()` directly when the budget is exceeded, so the `smart` strategy currently has no effect on prompt assembly.
- `--lang` is not yet exposed as a CLI flag; report language is set via the `generate_report` tool argument. A `--lang` CLI option is future work.
